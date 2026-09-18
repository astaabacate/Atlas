"""
Provedor de corrida concorrente (AutoProvider).

Dispara a requisição simultaneamente para todos os corredores configurados com o mesmo
timeout. O primeiro que responder com sucesso vence e os demais são cancelados.

Quando todos falham, o erro devolve o resumo de TODOS os corredores (deduplicado e sem
HTML), mais a instrução do que configurar — em vez de vazar uma parede de HTML no Discord.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from typing import Any

from llm.base import ChatProvider, LLMResponse, ProviderError, compact_error_text
from llm.free_providers import (
    KNOWN_GATEWAYS,
    build_free_runners,
    build_gateway_provider,
    descrever_pool,
)
from llm.key_providers import AnthropicProvider

logger = logging.getLogger("farol.llm.auto")

MAX_ERRORS_IN_MESSAGE = 6

# Quantas ondas de corrida tentar antes de desistir do turno e quanto esperar entre elas.
# Os gratuitos compartilham o IP do runner, então uma segunda tentativa curta costuma salvar
# quando o erro é fila cheia (HTTP 429). Configurável por LLM_RACE_WAVES / LLM_RACE_DELAY.
DEFAULT_MAX_WAVES = 2
DEFAULT_WAVE_DELAY = 0.8

# Quanto tempo um corredor fica "de castigo" depois de estourar o limite.
BENCH_ON_RATE_LIMIT = 30.0
BENCH_ON_ERROR = 15.0


def _env_int(nome: str, padrao: int, minimo: int, maximo: int) -> int:
    try:
        valor = int(os.environ.get(nome, "") or padrao)
    except (TypeError, ValueError):
        return padrao
    return max(minimo, min(maximo, valor))


def _env_float(nome: str, padrao: float) -> float:
    try:
        valor = float(os.environ.get(nome, "") or padrao)
    except (TypeError, ValueError):
        return padrao
    return max(0.0, valor)


class LLMUnavailableError(RuntimeError):
    """
    Todos os corredores falharam neste turno.

    `transient` diz se vale a pena a pessoa tentar de novo na hora (fila cheia/limite) —
    o bot usa isso para responder algo amigável em vez de despejar o erro técnico.
    """

    def __init__(self, message: str, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient

    def resumo_para_usuario(self) -> str:
        """Uma linha em PT-BR para mandar no Discord."""
        if self.transient:
            return ("🤖 Os modelos gratuitos estão com a fila cheia agora (limite de uso). "
                    "Tente de novo em alguns segundos — já tentei mais de uma vez.")
        return ("🤖 Não consegui falar com nenhum modelo de linguagem agora. "
                "Tente de novo em instantes.")


class AutoProvider(ChatProvider):
    name = "auto"

    def __init__(self, providers: list[ChatProvider] | None = None) -> None:
        self.providers: list[ChatProvider] = providers if providers is not None else []
        self.last_winner: str = ""
        # True quando o vencedor da última corrida usou function calling nativo.
        self.last_winner_native_tools: bool = False
        # Corredores "de castigo" (nome -> instante em que podem voltar).
        self._benched: dict[str, float] = {}
        self.max_waves = _env_int("LLM_RACE_WAVES", DEFAULT_MAX_WAVES, minimo=1, maximo=5)
        self.wave_delay = _env_float("LLM_RACE_DELAY", DEFAULT_WAVE_DELAY)
        self.last_failure_transient = False

    # ---------------------------------------------------------------- factory
    @classmethod
    def create_default(
        cls,
        api_key: str = "",
        custom_provider: str = "",
        custom_model: str = "",
        custom_base_url: str = "",
        custom_models: list[str] | None = None,
        disable_free: bool = False,
        env: dict[str, str] | None = None,
    ) -> AutoProvider:
        """
        Monta a corrida:
        1. provedor com chave (LLM_PROVIDER/LLM_BASE_URL/LLM_MODEL/LLM_API_KEY), se configurado;
        2. POOL DE CAPACIDADE GRATUITA (`FREE_PROVIDERS`): anônimos sempre + os que têm a
           chave gratuita cadastrada, salvo DISABLE_FREE_LLMS=1.

        O pool é o único caminho sem chave paga. Os corredores antigos (llm7, OVH,
        Pollinations) foram REMOVIDOS do código: falhavam juntos (429/modelo aposentado)
        e derrubavam o bot. GitHub Models aposentado e OpenCode Zen pago também ficaram de fora.
        """
        runners: list[ChatProvider] = []
        provider_name = (custom_provider or "auto").strip().lower()

        if provider_name not in ("", "auto", "none"):
            if provider_name == "anthropic":
                # Anthropic usa /v1/messages + x-api-key (não é OpenAI-compatível).
                from llm.free_providers import resolve_gateway_key

                key = resolve_gateway_key("anthropic", api_key, env if env is not None else {})
                if not key:
                    raise ValueError(
                        "LLM_PROVIDER='anthropic' exige chave de API. "
                        "Cadastre o secret ANTHROPIC_API_KEY (ou LLM_API_KEY) no GitHub Actions."
                    )
                runners.append(
                    AnthropicProvider(
                        api_key=key,
                        model=custom_model or "claude-3-5-haiku-20241022",
                        base_url=custom_base_url or "https://api.anthropic.com/v1",
                    )
                )
            else:
                runners.append(
                    build_gateway_provider(
                        provider=provider_name,
                        api_key=api_key,
                        model=custom_model,
                        base_url=custom_base_url,
                        models=custom_models,
                        env=env,
                    )
                )

        if not disable_free:
            runners.extend(build_free_runners(env=env))
            ativos, faltando = descrever_pool(env=env)
            logger.info("Pool gratuito ativo: %s", ativos or "(nenhum)")
            if faltando:
                logger.warning(
                    "Fora do pool por falta de credencial: %s. Cadastre o secret no GitHub "
                    "Actions (Settings -> Secrets and variables -> Actions) para ampliar a corrida.",
                    "; ".join(faltando),
                )

        if not runners:
            raise ValueError(
                "Nenhum provedor de LLM configurado. Cadastre uma chave gratuita no GitHub "
                f"Actions (opções: {', '.join(sorted(KNOWN_GATEWAYS))}) ou libere o pool "
                "gratuito removendo DISABLE_FREE_LLMS."
            )

        return cls(providers=runners)

    # ---------------------------------------------------------------- helpers
    def describe(self) -> str:
        """Resumo legível dos corredores configurados (para logs e mensagens de erro)."""
        return ", ".join(
            f"{p.name}{'/tools' if getattr(p, 'supports_tools', False) else ''}" for p in self.providers
        )

    def tool_capable(self) -> list[ChatProvider]:
        return [p for p in self.providers if getattr(p, "supports_tools", False)]

    # ------------------------------------------------------------------- chat
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        timeout: float = 60.0,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        if not self.providers:
            raise RuntimeError("Nenhum corredor LLM configurado na corrida.")

        erros: list[str] = []
        transitorio = False
        limite = time.monotonic() + max(5.0, timeout)

        for onda in range(1, self.max_waves + 1):
            restante = limite - time.monotonic()
            if restante <= 1.0:
                break

            # Primeira onda: só quem não estourou limite há pouco. Última onda ("modo
            # desespero"): todo mundo, inclusive os de castigo — melhor tentar do que falhar.
            candidatos = self._candidatos(ultima_onda=onda == self.max_waves)
            if not candidatos:
                break

            timeout_onda = min(timeout, max(10.0, restante * 0.8))
            vencedor, erros_onda, transitorio_onda = await self._correr_onda(
                candidatos, messages, tools, timeout_onda, max_tokens
            )
            erros.extend(erros_onda)
            transitorio = transitorio or transitorio_onda

            if vencedor is not None:
                nome, nativo, resposta = vencedor
                self.last_winner = nome
                self.last_winner_native_tools = nativo
                self.last_failure_transient = False
                logger.info("Corrida de LLMs vencida por: %s", nome)
                return resposta

            if onda < self.max_waves:
                pausa = min(self.wave_delay * onda, max(0.0, limite - time.monotonic()))
                if pausa > 0:
                    await asyncio.sleep(pausa + random.uniform(0, 0.3))
                logger.info("Corrida de LLMs: onda %d sem vencedor, tentando de novo", onda)

        self.last_failure_transient = transitorio
        raise LLMUnavailableError(self.build_failure_message(erros), transient=transitorio)

    def _candidatos(self, ultima_onda: bool) -> list[ChatProvider]:
        """Corredores disponíveis agora; na última onda entram até os que estão de castigo."""
        if ultima_onda:
            return list(self.providers)
        agora = time.monotonic()
        return [p for p in self.providers if self._benched.get(p.name, 0.0) <= agora]

    async def _correr_onda(
        self,
        candidatos: list[ChatProvider],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        timeout: float,
        max_tokens: int,
    ) -> tuple[tuple[str, bool, LLMResponse] | None, list[str], bool]:
        """
        Dispara todos os candidatos em paralelo, numa passada só.

        Devolve (vencedor, erros, transitorio): o primeiro que responder vence e os demais são
        cancelados; se ninguém responder, os erros alimentam o diagnóstico e o castigo.
        """
        tarefas: dict[asyncio.Task[tuple[str, bool, LLMResponse]], ChatProvider] = {
            asyncio.create_task(self._run_candidate(p, messages, tools, timeout, max_tokens)): p
            for p in candidatos
        }
        erros: list[str] = []
        transitorio = False

        pendentes = set(tarefas)
        try:
            while pendentes:
                concluidas, pendentes = await asyncio.wait(pendentes, return_when=asyncio.FIRST_COMPLETED)
                vencedores: list[tuple[str, bool, LLMResponse]] = []
                for tarefa in concluidas:
                    provider = tarefas[tarefa]
                    try:
                        nome, nativo, resp = tarefa.result()
                    except Exception as exc:  # noqa: BLE001 - falha de um corredor é dado, não crash
                        # Classificar mesmo quando outro venceu: é assim que o 429 vira castigo.
                        erros.append(self._anotar_falha(provider, exc))
                        if not isinstance(exc, ProviderError) or exc.is_transient:
                            transitorio = True
                        continue
                    if resp and (resp.content or resp.has_tool_calls):
                        vencedores.append((nome, nativo, resp))
                    else:
                        erros.append(f"{provider.name}: resposta vazia")
                if vencedores:
                    return vencedores[0], erros, transitorio
        finally:
            for tarefa in pendentes:
                tarefa.cancel()
            if pendentes:
                await asyncio.gather(*pendentes, return_exceptions=True)

        return None, erros, transitorio

    def _anotar_falha(self, provider: ChatProvider, exc: BaseException) -> str:
        """Classifica a falha do corredor e decide se ele merece um tempo de castigo."""
        if isinstance(exc, ProviderError):
            if exc.is_rate_limited:
                self._castigar(provider.name, exc.retry_after or BENCH_ON_RATE_LIMIT)
            elif exc.is_transient:
                self._castigar(provider.name, BENCH_ON_ERROR)
        return f"{provider.name}: {exc}"

    async def _run_candidate(
        self,
        provider: ChatProvider,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        timeout: float,
        max_tokens: int,
    ) -> tuple[str, bool, LLMResponse]:
        resp = await provider.chat(
            messages=messages,
            tools=tools,
            timeout=timeout,
            max_tokens=max_tokens,
        )
        return provider.name, bool(getattr(provider, "supports_tools", False)), resp

    def _castigar(self, nome: str, segundos: float) -> None:
        """Evita insistir num corredor que acabou de estourar o limite."""
        ate = time.monotonic() + max(1.0, segundos)
        if ate > self._benched.get(nome, 0.0):
            logger.info("Corredor %s de castigo por %.0fs", nome, segundos)
            self._benched[nome] = ate

    def castigados(self) -> list[str]:
        """Nomes dos corredores de castigo agora (diagnóstico)."""
        agora = time.monotonic()
        return [p.name for p in self.providers if self._benched.get(p.name, 0.0) > agora]

    def build_failure_message(self, errors: list[str]) -> str:
        """Mensagem curta e acionável quando a corrida inteira falha."""
        unique: list[str] = []
        for err in errors:
            # Remove HTML de páginas de erro e limita cada item a uma linha curta.
            line = compact_error_text(err, limit=180)
            if line not in unique:
                unique.append(line)

        shown = unique[:MAX_ERRORS_IN_MESSAGE]
        extra = len(unique) - len(shown)
        partes = [
            f"Nenhum dos {len(self.providers)} provedores de LLM respondeu "
            f"({self.describe()}) depois de {self.max_waves} tentativa(s)."
        ]
        if shown:
            partes.append("Erros: " + " | ".join(shown) + (f" | +{extra} outros" if extra > 0 else ""))
        partes.append(
            "Os gratuitos compartilham o IP do servidor e estouram limite com facilidade. "
            "Para acabar com isso, cadastre uma chave GRATUITA (Groq, Gemini ou OpenRouter — sem cartão) "
            f"nos segredos do GitHub Actions: LLM_API_KEY + LLM_PROVIDER ({', '.join(sorted(KNOWN_GATEWAYS))})."
        )
        return " ".join(partes)

    async def close(self) -> None:
        for p in self.providers:
            try:
                await p.close()
            except Exception:
                pass
