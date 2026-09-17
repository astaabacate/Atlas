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
from typing import Any

from llm.base import ChatProvider, LLMResponse, compact_error_text
from llm.free_providers import (
    KNOWN_GATEWAYS,
    build_anonymous_runners,
    build_gateway_provider,
)
from llm.key_providers import AnthropicProvider

logger = logging.getLogger("farol.llm.auto")

MAX_ERRORS_IN_MESSAGE = 6


class AutoProvider(ChatProvider):
    name = "auto"

    def __init__(self, providers: list[ChatProvider] | None = None) -> None:
        self.providers: list[ChatProvider] = providers if providers is not None else []
        self.last_winner: str = ""
        # True quando o vencedor da última corrida usou function calling nativo.
        self.last_winner_native_tools: bool = False

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
        2. corredores anônimos (llm7, OVH, Pollinations), salvo DISABLE_FREE_LLMS=1.

        Nota: GitHub Models foi aposentado em 30/07/2026, então GITHUB_TOKEN não gera mais
        corredor LLM. OpenCode Zen virou pago. Ambos saíram da corrida padrão.
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
            runners.extend(build_anonymous_runners(env=env))

        if not runners:
            raise ValueError(
                "Nenhum provedor de LLM configurado. Defina LLM_PROVIDER + LLM_API_KEY "
                f"(opções: {', '.join(sorted(KNOWN_GATEWAYS))}) ou libere os corredores "
                "gratuitos removendo DISABLE_FREE_LLMS."
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

        async def _run_candidate(provider: ChatProvider) -> tuple[str, bool, LLMResponse]:
            resp = await provider.chat(
                messages=messages,
                tools=tools,
                timeout=timeout,
                max_tokens=max_tokens,
            )
            return provider.name, bool(getattr(provider, "supports_tools", False)), resp

        tasks: list[asyncio.Task[tuple[str, bool, LLMResponse]]] = [
            asyncio.create_task(_run_candidate(p)) for p in self.providers
        ]

        errors: list[str] = []
        winner_name: str | None = None
        winner_native = False
        winner_response: LLMResponse | None = None

        try:
            for fut in asyncio.as_completed(tasks):
                try:
                    p_name, p_native, resp = await fut
                except Exception as exc:
                    errors.append(str(exc))
                    continue
                if resp and (resp.content or resp.has_tool_calls):
                    winner_name = p_name
                    winner_native = p_native
                    winner_response = resp
                    break
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        if winner_response is not None:
            self.last_winner = winner_name or ""
            self.last_winner_native_tools = winner_native
            logger.info("Corrida de LLMs vencida por: %s", winner_name)
            return winner_response

        raise RuntimeError(self.build_failure_message(errors))

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
        parts = [
            f"Nenhum dos {len(self.providers)} provedores de LLM respondeu "
            f"({self.describe()})."
        ]
        if shown:
            parts.append("Erros: " + " | ".join(shown) + (f" | +{extra} outros" if extra > 0 else ""))
        parts.append(
            "Como resolver: cadastre uma chave em LLM_API_KEY e o provedor em LLM_PROVIDER "
            f"({', '.join(sorted(KNOWN_GATEWAYS))}) nos segredos/variáveis do GitHub Actions."
        )
        return " ".join(parts)

    async def close(self) -> None:
        for p in self.providers:
            try:
                await p.close()
            except Exception:
                pass
