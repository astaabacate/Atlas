"""
Provedores LLM via HTTP no padrão OpenAI Chat Completions.

Dois grupos vivem aqui:
1. POOL DE CAPACIDADE GRATUITA (`FREE_PROVIDERS`): provedores com free tier real, sem cartão —
   o corredor anônimo `kilo` (sem cadastro) e os que entram quando a chave gratuita é cadastrada
   (Gemini, Groq, Mistral, NVIDIA, Z.ai, Cloudflare, Ollama, OpenRouter, ModelScope, SiliconFlow,
   Cohere). O pool é o único caminho sem chave paga.
2. Gateways (mesmos do pool para uso direto via LLM_PROVIDER, mais os pagos: OpenAI, DeepSeek,
   Anthropic, OpenCode Zen, e qualquer endpoint OpenAI-compatível via LLM_BASE_URL).

Histórico importante (o motivo de vários corredores antigos terem sumido):
- GitHub Models: endpoint Azure (models.inference.ai.azure.com) desligado em 17/10/2025 e o
  serviço GitHub Models foi aposentado por completo em 30/07/2026. Não existe mais corrida
  gratuita com GITHUB_TOKEN, por isso o corredor foi removido.
- OpenCode Zen: passou a exigir login + cartão + chave paga (401 "Invalid API key" com
  "Bearer opencode"). Saiu da lista de anônimos; funciona como gateway com chave via LLM_*.
- Blackbox (api.blackbox.ai/chat/completions): 404 (HTML) — caminho inexistente.
- Kilo: o gateway NÃO fica em /v1 (dava 404) e sim em **api.kilo.ai/api/gateway** — com acesso
  anônimo oficial (200 req/h por IP). É o corredor sem chave do pool atual.
- llm7, OVH (kepler) e Pollinations: REMOVIDOS do código em 17/09/2026. Os três falhavam juntos
  (429 "queue full"/"rate limit" e modelo aposentado) e derrubavam a corrida inteira; não são mais
  classe, corredor, fallback nem config.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

import aiohttp

from llm.base import (
    separar_raciocinio,
    ChatProvider,
    LLMResponse,
    ProviderError,
    ToolCall,
    build_tool_protocol_notice,
    compact_error_text,
    parse_openai_tool_calls,
    sanitize_messages_for_plain_text,
)

logger = logging.getLogger("farol.llm.free")

# Auto-descoberta de modelos: com que frequência consultar e quantos candidatos manter.
MODEL_REFRESH_INTERVAL = 1800.0   # 30 min
MAX_DISCOVERED_MODELS = 6

# Cooldown padrão depois de um 429 (o header Retry-After manda quando existir).
DEFAULT_COOLDOWN = 45.0
# Repetição com mais espaço quando o modelo devolve vazio por teto de tokens (raciocínio).
MIN_AMPLIACAO_TOKENS = 1024
MAX_AMPLIACAO_TOKENS = 8192
MAX_INLINE_RETRY_WAIT = 2.5


def _parse_retry_after(headers: Any) -> float | None:
    """Lê o header Retry-After (segundos). Ignora formatos de data e valores absurdos."""
    try:
        valor = (headers or {}).get("Retry-After")
    except Exception:  # noqa: BLE001 - headers duck-typed
        return None
    if not valor:
        return None
    try:
        segundos = float(str(valor).strip())
    except (TypeError, ValueError):
        return None
    if segundos <= 0:
        return None
    return min(segundos, 300.0)


def _extract_model_ids(data: Any) -> list[str]:
    """Aceita os formatos comuns de /models: {"data": [{"id": ...}]} ou [{"name": ...}]."""
    itens: list[Any] = []
    if isinstance(data, dict):
        for chave in ("data", "models", "result"):
            if isinstance(data.get(chave), list):
                itens = data[chave]
                break
    elif isinstance(data, list):
        itens = data

    ids: list[str] = []
    for item in itens:
        if isinstance(item, str):
            ids.append(item)
        elif isinstance(item, dict):
            for chave in ("id", "name", "model"):
                valor = item.get(chave)
                if isinstance(valor, str) and valor:
                    ids.append(valor)
                    break
    return ids


def _looks_like_chat_model(model_id: str) -> bool:
    """Descarta embeddings/áudio/imagem: não servem para conversar com ferramentas."""
    baixo = model_id.lower()
    bloqueados = ("embed", "whisper", "tts", "audio", "speech", "dall", "image", "flux", "sdxl", "stable-")
    return not any(bloco in baixo for bloco in bloqueados)

SessionFactory = Callable[[], aiohttp.ClientSession]


def looks_like_html(body: str) -> bool:
    """Detecta páginas de erro HTML (404 de CDN/gateway) em vez de JSON de API."""
    head = (body or "")[:300].lower()
    return bool(re.search(r"<(!doctype|html|head|body)", head))


def default_session_factory() -> aiohttp.ClientSession:
    return aiohttp.ClientSession()


class OpenAICompatibleHttpProvider(ChatProvider):
    """
    Provedor genérico compatível com OpenAI Chat Completions.

    Recursos:
    - Lista de modelos com fallback automático (modelo indisponível → tenta o próximo).
    - Quando o provedor não suporta `tools`, injeta um protocolo de texto (```tool {...}```)
      e sanitiza o histórico (role=tool → role=user), para o agente continuar agindo.
    - Se o provedor rejeitar o schema de tools, degrada sozinho para o protocolo de texto.
    """

    def __init__(
        self,
        name: str,
        endpoint_url: str,
        models: list[str] | None = None,
        default_model: str = "",
        headers: dict[str, str] | None = None,
        supports_tools: bool = False,
        session_factory: SessionFactory | None = None,
        models_url: str = "",
        auto_discover: bool = True,
        discovery_can_replace: bool = True,
        cooldown: float = DEFAULT_COOLDOWN,
    ) -> None:
        candidate_models = [m for m in (models or []) if m]
        if default_model and default_model not in candidate_models:
            candidate_models.insert(0, default_model)
        if not candidate_models:
            raise ValueError(f"Provedor {name} exige ao menos um modelo configurado.")

        self.name = name
        self.endpoint_url = endpoint_url
        # Tempo de castigo próprio do provedor (vem da ficha do pool).
        self.cooldown = max(1.0, float(cooldown))
        self.models = candidate_models
        # Lista original, para nunca ficar sem candidato depois de uma descoberta estranha.
        self.configured_models = list(candidate_models)
        self.headers = dict(headers or {})
        self.supports_tools = supports_tools
        self._session_factory = session_factory or default_session_factory
        self._session: aiohttp.ClientSession | None = None
        # Marcado em runtime quando o provedor recusou `tools` — evita repetir o erro.
        self.native_tools_rejected = False

        # Auto-descoberta de modelos: provedores gratuitos trocam de catálogo sem avisar
        # (já aconteceu com um corredor antigo devolvendo 400 "Model ... is currently unavailable").
        self.models_url = models_url or (
            endpoint_url[: -len("/chat/completions")] + "/models"
            if endpoint_url.endswith("/chat/completions")
            else ""
        )
        self.auto_discover = auto_discover
        self.discovery_can_replace = discovery_can_replace
        self._models_refreshed_at = 0.0

        # Depois de um 429, o provedor fica "de castigo" por um tempo para não queimar a
        # corrida inteira (os gratuitos compartilham o IP do runner).
        self.cooldown_until = 0.0

    @property
    def cooling_down(self) -> bool:
        return self.cooldown_until > time.monotonic()

    def _start_cooldown(self, seconds: float) -> None:
        self.cooldown_until = max(self.cooldown_until, time.monotonic() + max(1.0, seconds))

    async def refresh_models(self, force: bool = False) -> list[str]:
        """
        Busca a lista de modelos do provedor e reordena os candidatos.

        Mantém os configurados que ainda existem (na ordem original, para preservar
        preferências) e completa com os descobertos que parecem servir para chat.
        """
        if not self.models_url or (self.auto_discover is False and not force):
            return self.models
        agora = time.monotonic()
        if not force and (agora - self._models_refreshed_at) < MODEL_REFRESH_INTERVAL:
            return self.models

        try:
            session = await self._get_session()
            timeout = aiohttp.ClientTimeout(total=15.0)
            async with session.get(self.models_url, headers=self.headers, timeout=timeout) as resp:
                if resp.status != 200:
                    return self.models
                data = await resp.json(content_type=None)
        except Exception as exc:  # noqa: BLE001 - descoberta é otimização, nunca obrigação
            logger.debug("[%s] não consegui listar modelos (%s); sigo com a lista configurada", self.name, exc)
            return self.models

        ids = _extract_model_ids(data)
        if not ids:
            return self.models

        disponiveis = set(ids)
        mantidos = [m for m in self.configured_models if m in disponiveis]
        novos = [m for m in ids if m not in mantidos and _looks_like_chat_model(m)]
        if not mantidos and not self.discovery_can_replace:
            # Catálogo num namespace diferente do esperado (aliases em vez de nomes reais):
            # melhor manter a lista que funciona do que apostar em ids desconhecidos.
            self._models_refreshed_at = agora
            return self.models
        candidatos = (mantidos + novos)[:MAX_DISCOVERED_MODELS] or self.configured_models
        if candidatos != self.models:
            logger.info("[%s] catálogo atualizado: %s", self.name, ", ".join(candidatos))
        self.models = candidatos
        self._models_refreshed_at = agora
        return self.models

    # ------------------------------------------------------------------ infra
    @property
    def default_model(self) -> str:
        return self.models[0]

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = self._session_factory()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # -------------------------------------------------------------- mensagens
    def _uses_native_tools(self, tools: list[dict[str, Any]] | None) -> bool:
        return bool(tools) and self.supports_tools and not self.native_tools_rejected

    def build_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        max_tokens: int,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Monta o corpo da requisição e devolve também as mensagens efetivamente enviadas."""
        use_native = self._uses_native_tools(tools)

        if use_native:
            outgoing = list(messages)
        else:
            outgoing = sanitize_messages_for_plain_text(messages)
            if tools:
                outgoing = [*outgoing, {"role": "system", "content": build_tool_protocol_notice(tools)}]

        payload: dict[str, Any] = {
            "model": model,
            "messages": outgoing,
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }
        if use_native:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload, outgoing

    # ------------------------------------------------------------------ chat
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        timeout: float = 60.0,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        session = await self._get_session()
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "FarolDiscordBot/1.0",
            **self.headers,
        }
        client_timeout = aiohttp.ClientTimeout(total=timeout)

        # Catálogo pode ter mudado (provedor gratuito troca modelo sem avisar).
        if self.auto_discover and not self.models:
            await self.refresh_models()
        elif self.auto_discover and self._models_refreshed_at == 0.0:
            await self.refresh_models()

        last_error: ProviderError | None = None
        retry_429_usado = False
        # Modelo que voltou vazio por teto de tokens ganha UMA repetição com o dobro de espaço.
        ampliados: set[str] = set()
        # Percorre por índice: quando o catálogo é redescoberto no meio do caminho, a
        # varredura recomeça já sem o modelo morto.
        modelos = list(self.models)
        indice = 0
        while indice < len(modelos):
            model = modelos[indice]
            indice += 1
            payload, _ = self.build_payload(messages, tools, model, max_tokens)
            try:
                resposta = await self._post(session, payload, headers, client_timeout, model)
                self.cooldown_until = 0.0
                return resposta
            except ProviderError as exc:
                last_error = exc

                if exc.is_rate_limited:
                    espera = exc.retry_after if exc.retry_after is not None else self.cooldown
                    self._start_cooldown(espera)
                    # Uma segunda tentativa rápida resolve fila momentânea ("Queue full for IP").
                    if not retry_429_usado:
                        retry_429_usado = True
                        pausa = min(espera, MAX_INLINE_RETRY_WAIT)
                        logger.debug("[%s] %s; tentando de novo em %.1fs", self.name, exc.raw_message[:80], pausa)
                        await asyncio.sleep(pausa)
                        try:
                            resposta = await self._post(session, payload, headers, client_timeout, model)
                            self.cooldown_until = 0.0
                            return resposta
                        except ProviderError as retry_exc:
                            last_error = retry_exc
                            if retry_exc.is_rate_limited:
                                self._start_cooldown(retry_exc.retry_after or self.cooldown)
                                raise
                            exc = retry_exc

                if exc.is_empty_response and not exc.truncated:
                    # Vazio "seco" (roteador grátis costuma fazer isso): passar a vez na hora.
                    # Repetir o mesmo modelo só soma a latência dele de novo — e tem fila atrás.
                    logger.debug("[%s] %s devolveu resposta vazia; passando para o próximo modelo",
                                 self.name, model)
                    continue

                if exc.is_empty_response and exc.truncated and model not in ampliados:
                    ampliados.add(model)
                    max_tokens = min(max(max_tokens * 2, MIN_AMPLIACAO_TOKENS), MAX_AMPLIACAO_TOKENS)
                    logger.debug("[%s] %s devolveu nada no teto de tokens; repetindo com %d",
                                 self.name, model, max_tokens)
                    indice -= 1
                    continue

                if exc.is_empty_response:
                    # Já repetiu este modelo e continua vazio: tenta o próximo do corredor.
                    logger.debug("[%s] %s segue vazio; trocando de modelo", self.name, model)
                    continue

                if exc.is_tools_rejection and not self.native_tools_rejected:
                    # O provedor não engole o schema: tenta de novo via protocolo de texto.
                    logger.debug("[%s] tools recusados, degradando para protocolo de texto", self.name)
                    self.native_tools_rejected = True
                    fallback_payload, _ = self.build_payload(messages, tools, model, max_tokens)
                    try:
                        resposta = await self._post(session, fallback_payload, headers, client_timeout, model)
                        self.cooldown_until = 0.0
                        return resposta
                    except ProviderError as retry_exc:
                        last_error = retry_exc
                        continue

                if exc.is_model_problem:
                    # O catálogo mudou: descobre os modelos válidos e recomeça a varredura.
                    novos = await self.refresh_models(force=True)
                    limpos = [m for m in (novos or self.models) if m != model]
                    if limpos:
                        logger.debug("[%s] modelo %s indisponível; catálogo agora é %s",
                                     self.name, model, ", ".join(limpos[:3]))
                        self.models = limpos
                        modelos = list(limpos)
                        indice = 0
                        continue

                raise
        raise last_error or ProviderError(self.name, "falha sem detalhe", model=self.default_model)

    async def _post(
        self,
        session: aiohttp.ClientSession,
        payload: dict[str, Any],
        headers: dict[str, str],
        client_timeout: aiohttp.ClientTimeout,
        model: str,
    ) -> LLMResponse:
        try:
            async with session.post(
                self.endpoint_url,
                json=payload,
                headers=headers,
                timeout=client_timeout,
            ) as resp:
                body = await resp.text()
                if resp.status != 200:
                    raise ProviderError(
                        provider=self.name,
                        message=f"{self.name}: HTTP {resp.status} ({model}) — {compact_error_text(body)}",
                        status=resp.status,
                        model=model,
                        html_body=looks_like_html(body),
                        retry_after=_parse_retry_after(getattr(resp, "headers", None)),
                    )
                try:
                    data = await resp.json(content_type=None)
                except Exception as exc:
                    raise ProviderError(
                        provider=self.name,
                        message=f"{self.name}: resposta não-JSON ({model}) — {compact_error_text(body)}",
                        model=model,
                    ) from exc
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                provider=self.name,
                message=f"{self.name}: falha de rede — {type(exc).__name__}: {compact_error_text(str(exc))}",
                model=model,
            ) from exc

        choices = data.get("choices") or []
        if not choices:
            raise ProviderError(
                provider=self.name,
                message=f"{self.name}: resposta sem choices ({model}) — {compact_error_text(str(data))}",
                model=model,
            )

        msg = choices[0].get("message") or {}
        content = msg.get("content") or ""
        tool_calls: list[ToolCall] = []
        if msg.get("tool_calls"):
            tool_calls = parse_openai_tool_calls(msg["tool_calls"])
        concluiu_por_limite = str(choices[0].get("finish_reason") or "").lower() == "length"

        # Gateways grátis às vezes devolvem o rascunho interno no content (ou num campo
        # separado). Rascunho não é resposta: vale o que vier depois do "final answer".
        if msg.get("reasoning_content") or msg.get("reasoning"):
            logger.debug("[%s] %s devolveu raciocínio em campo separado", self.name, model)
        rascunho, resposta = separar_raciocinio(content)
        if rascunho:
            logger.info("[%s] %s mandou rascunho interno (%d chars); resposta útil: %d chars",
                        self.name, model, len(rascunho), len(resposta))
            content = resposta

        if not content and not tool_calls:
            # Modelos de raciocínio (grátis, via gateway) gastam o teto inteiro "pensando" e
            # devolvem nada. Não é resposta: é pedido de mais espaço — quem chama decide.
            raise ProviderError(
                provider=self.name,
                message=(
                    f"{self.name}: resposta vazia ({model}"
                    + (" — teto de tokens)" if concluiu_por_limite else ")")
                ),
                model=model,
                empty_response=True,
                truncated=concluiu_por_limite,
            )
        return LLMResponse(content=content, tool_calls=tool_calls)


# ---------------------------------------------------------------------------
# POOL DE CAPACIDADE GRATUITA (FREE_PROVIDERS)
#
# Cada ficha diz onde o provedor fica, como entrar (anônimo ou chave gratuita),
# quanto oferece de contexto/cota e se já respondeu na sonda ao vivo.
#
# REGRAS DO POOL (decididas com o dono do bot):
#   1. Só entra provedor com free tier REAL: sem cartão de crédito, sem trial que
#      expira, sem "créditos" que acabam.
#   2. Nada de burlar limite, CAPTCHA, IP ou criar conta falsa — se o provedor
#      limita por organização, aceitamos o limite.
#   3. `llm7`, `ovh` e `pollinations` foram REMOVIDOS do código (falhavam juntos
#      com 429/modelo aposentado e derrubavam a corrida).
#   4. `validado=True` só depois de o corredor responder 200 na sonda real
#      (`scripts/smoke_llm.py`); o resto aparece como ⚠️ e não conta como ativo.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FreeProviderSpec:
    """Ficha de um provedor gratuito do pool."""

    nome: str
    base_url: str
    modelos: tuple[str, ...]
    key_env: str = ""              # "" = acesso anônimo (sem cadastro)
    contexto: str = ""
    cota: str = ""
    supports_tools: bool = False
    supports_models: bool = True   # expõe GET /models (a corrida usa para descobrir catálogo)
    conta_id_env: str = ""         # provedores que exigem ID da conta na URL
    headers: tuple[tuple[str, str], ...] = ()
    cooldown: float = 45.0
    validado: bool = False         # 200 confirmado na sonda ao vivo (reports/smoke-llm.md)
    observacao: str = ""

    @property
    def status(self) -> str:
        """🟢 só com 200 confirmado ao vivo; senão 🟡 (gratuito confirmado, não testado)."""
        return "🟢 TESTADA E FUNCIONANDO" if self.validado else "🟡 GRATUITA CONFIRMADA, MAS NÃO TESTADA"


FREE_PROVIDERS: tuple[FreeProviderSpec, ...] = (
    # -- sem cadastro nenhum -------------------------------------------------
    FreeProviderSpec(
        nome="kilo",
        base_url="https://api.kilo.ai/api/gateway",
        # Lista conferida no catálogo AO VIVO (GET /api/gateway/models, sem credencial):
        # reports/kilo-modelos-free.md (21 ":free" de 380).
        #
        # ORDEM = MEDIÇÃO, não chute: o smoke mede cada modelo 3× por rodada e guarda o
        # histórico em reports/kilo-latencia-historico.json; a mediana e a taxa de resposta com
        # conteúdo estão em reports/kilo-latencia-modelos.md. Critério (confiabilidade antes de
        # velocidade — de nada adianta ir rápido e devolver vazio):
        #   1) maior taxa de rodadas com conteúdo na frente (mediana de 4 rodadas × 3 amostras);
        #   2) empate de taxa → menor mediana de latência;
        #   3) quem nunca devolveu conteúdo fica no fim, como reserva, e pode subir no próximo
        #      smoke (a lista é revisada a cada rodada medida);
        #   4) o roteador `kilo-auto` é sempre o último (só existe para o caso de todos os
        #      nomeados falharem).
        # Medido em 18/09 (8 rodadas, 3 amostras por rodada — reports/kilo-latencia-modelos.md).
        # Entre os que acertam sempre, o mais rápido vem primeiro: a mediana do nex caiu para
        # 1,21 s (era 2,13 s com 4 rodadas) e ele assumiu a ponta do ultra (1,93 s).
        modelos=(
            "nex-agi/nex-n2.5-pro:free",                  # 100% · 1,21 s · 262K
            "nvidia/nemotron-3-ultra-550b-a55b:free",     # 100% · 1,93 s · 1M
            "nvidia/nemotron-3.5-lightning:free",         # 100% · 2,48 s · 1M
            "nvidia/nemotron-3-super-120b-a12b:free",     #  88% · 0,84 s · 262K
            "dots-studio/dots-3-note-preview:free",       #  88% · 1,45 s · 512K
            # -- responderam com conteúdo na maioria das rodadas: entram quando os de cima
            #    falham, mas ainda não são primeira escolha.
            "liquid/lfm-2.5-2.6b:free",                   #  75% · 0,84 s · 65.536 (emergência)
            "stepfun/step-3.7-flash:free",                #  75% · 2,22 s · 262K
            "cohere/north-mini-code:free",                #  62% · 0,81 s · 256K
            # -- 8ª rodada (06:29): o qwen devolveu conteúdo pela primeira vez (12% = 1/8), então
            #    ele sobe acima dos que nunca devolveram — a regra é não gastar a vez com quem não
            #    responde enquanto houver quem responda.
            "qwen/qwen3.8-27b:free",                      #  12% · 1,06 s · 262.144
            # -- reservas: ainda não devolveram conteúdo em nenhuma rodada medida.
            "thinkingmachines/inkling-small:free",        # 1.048.576
            "poolside/laguna-s-2.1:free",                 # 262.144
            "kilo-auto/free",                             # roteador do gateway (por último)
        ),
        headers=(("Authorization", "Bearer anonymous"),),
        contexto="262K nos rápidos · 1M nas reservas · 65K mínimo",
        cota="200 req/h por IP (anônimo)",
        supports_tools=True,
        # 200 confirmado na sonda ao vivo (reports/smoke-llm.md): GET /models 200 (380 modelos),
        # chat PT + tools nativo + fallback textual + 3 chamadas consecutivas OK.
        validado=True,
        observacao="único corredor do pool sem chave; catálogo público em /models (isFree)",
    ),
    # -- chave gratuita no GitHub Actions (secret) ---------------------------
    FreeProviderSpec(
        nome="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        modelos=("gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"),
        key_env="GEMINI_API_KEY",
        contexto="1M",
        cota="10-15 RPM / 250-1.500 req por dia (por projeto)",
        supports_tools=True,
        observacao="chave em aistudio.google.com/apikey; dados do tier gratis podem treinar",
    ),
    FreeProviderSpec(
        nome="groq",
        base_url="https://api.groq.com/openai/v1",
        modelos=("openai/gpt-oss-120b", "openai/gpt-oss-20b",
                 "llama-3.3-70b-versatile", "llama-3.1-8b-instant"),
        key_env="GROQ_API_KEY",
        contexto="128K",
        cota="30 RPM / 1.000 req por dia / 200K tokens por dia (por organização)",
        supports_tools=True,
        observacao="chave em console.groq.com/keys; cota por organização (chaves extras nao somam)",
    ),
    FreeProviderSpec(
        nome="mistral",
        base_url="https://api.mistral.ai/v1",
        modelos=("mistral-small-latest", "mistral-large-latest", "codestral-latest"),
        key_env="MISTRAL_API_KEY",
        contexto="256K",
        cota="~1 bilhao de tokens por mes (~2 RPM)",
        supports_tools=True,
        observacao="plano Experiment: telefone, sem cartao; dados podem treinar",
    ),
    FreeProviderSpec(
        nome="nvidia",
        base_url="https://integrate.api.nvidia.com/v1",
        modelos=("meta/llama-3.3-70b-instruct", "nvidia/llama-3.3-nemotron-super-49b-v1.5",
                 "qwen/qwen3-235b-a22b"),
        key_env="NVIDIA_API_KEY",
        contexto="128K-262K",
        cota="1.000-5.000 creditos + 40 RPM",
        supports_tools=True,
        observacao="chave nvapi- em build.nvidia.com; catalogo com 100+ modelos",
    ),
    FreeProviderSpec(
        nome="zai",
        base_url="https://api.z.ai/api/paas/v4",
        modelos=("glm-4.7-flash", "glm-4.5-flash"),
        key_env="ZAI_API_KEY",
        contexto="131K",
        cota="~1.000 req por dia (Flash, ~1 req/s)",
        supports_tools=True,
        observacao="modelos Flash custam US$0/token; limites nao publicados oficialmente",
    ),
    FreeProviderSpec(
        nome="cloudflare",
        base_url="https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
        modelos=("@cf/zai-org/glm-5.3-flash", "@cf/google/gemma-4-26b-a4b-it",
                 "@cf/meta/llama-3.1-8b-instruct"),
        key_env="CLOUDFLARE_API_TOKEN",
        conta_id_env="CLOUDFLARE_ACCOUNT_ID",
        contexto="256K-1.3M",
        cota="10.000 neuronios por dia (conta)",
        supports_tools=False,
        observacao="precisa do Account ID na URL; neurônios acabam rápido em modelo grande",
    ),
    FreeProviderSpec(
        nome="ollama",
        base_url="https://api.ollama.com/v1",
        modelos=("gpt-oss:120b", "gpt-oss:20b", "qwen3.5:397b"),
        key_env="OLLAMA_API_KEY",
        contexto="128K-1M",
        cota="creditos mensais gratuitos, 1 requisicao concorrente",
        supports_tools=True,
        observacao="mesmos nomes de modelo do Ollama local; limites nao publicados",
    ),
    FreeProviderSpec(
        nome="openrouter",
        base_url="https://openrouter.ai/api/v1",
        modelos=("meta-llama/llama-3.3-70b-instruct:free", "qwen/qwen3-coder:free",
                 "z-ai/glm-4.5-air:free", "deepseek/deepseek-r1-0528:free"),
        key_env="OPENROUTER_API_KEY",
        contexto="ate 1M",
        cota="20 RPM / 50 req por dia (1.000/dia so pagando US$10 uma vez -> fora do pool)",
        supports_tools=True,
        observacao="só as variantes :free entram; modelo free pode dar 429 no upstream",
    ),
    FreeProviderSpec(
        nome="modelscope",
        base_url="https://api-inference.modelscope.cn/v1",
        modelos=("Qwen/Qwen3.5-35B-A3B", "Qwen/Qwen3.5-27B"),
        key_env="MODELSCOPE_API_KEY",
        contexto="131K-1M",
        cota="2.000 req por dia na conta (<=200-500 por modelo)",
        supports_tools=True,
        observacao="cadastro pede telefone (na pratica chines) - pode ser inviavel",
    ),
    FreeProviderSpec(
        nome="siliconflow",
        base_url="https://api.siliconflow.cn/v1",
        modelos=("Qwen/Qwen3-8B", "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B"),
        key_env="SILICONFLOW_API_KEY",
        contexto="131K",
        cota="modelos a US$0 (~1.000 RPM); credito inicial de US$1",
        supports_tools=True,
        observacao="tier gratuito excluido na UE/UK/CH; catalogo $0 muda",
    ),
    FreeProviderSpec(
        nome="cohere",
        base_url="https://api.cohere.ai/compatibility/v1",
        modelos=("command-a-03-2025", "command-r-plus-08-2024"),
        key_env="COHERE_API_KEY",
        contexto="128K",
        cota="1.000 chamadas por mes (trial key)",
        supports_tools=True,
        observacao="trial aceita apenas uso de desenvolvimento/avaliacao (nao comercial)",
    ),
)


def _ficha_pronta(spec: FreeProviderSpec, src: dict[str, str]) -> tuple[bool, str]:
    """Diz se o corredor pode entrar agora e, quando não, o que falta cadastrar."""
    if spec.key_env and not (src.get(spec.key_env, "") or "").strip():
        return False, f"falta o secret {spec.key_env}"
    if spec.conta_id_env and not (src.get(spec.conta_id_env, "") or "").strip():
        return False, f"falta a variavel {spec.conta_id_env}"
    return True, ""


def build_free_runners(env: dict[str, str] | None = None) -> list[ChatProvider]:
    """
    Monta o pool de capacidade gratuita.

    Entram: os corredores anônimos (sempre) e os que têm a chave gratuita cadastrada.
    Ficam de fora (e aparecem no relatório) os que ainda não têm credencial — assim
    o bot nunca gasta uma requisição num corredor que vai devolver 401.
    """
    src = env if env is not None else os.environ
    runners: list[ChatProvider] = []

    for spec in FREE_PROVIDERS:
        pronto, _ = _ficha_pronta(spec, src)
        if not pronto:
            continue

        base = spec.base_url
        if spec.conta_id_env:
            base = base.format(account_id=src.get(spec.conta_id_env, "").strip())

        headers = dict(spec.headers)
        chave = (src.get(spec.key_env, "") or "").strip() if spec.key_env else ""
        if chave:
            headers["Authorization"] = f"Bearer {chave}"

        runners.append(
            OpenAICompatibleHttpProvider(
                name=spec.nome,
                endpoint_url=f"{base}/chat/completions",
                models=list(spec.modelos),
                headers=headers,
                supports_tools=spec.supports_tools,
                models_url=f"{base}/models" if spec.supports_models else "",
                auto_discover=spec.supports_models,
                cooldown=spec.cooldown,
            )
        )
    return runners


def tabela_do_pool(env: dict[str, str] | None = None) -> str:
    """Config final em markdown: tudo o que a ficha carrega, já com o status de cada um."""
    relatorio = relatorio_do_pool(env)
    faltando = {spec.nome: motivo for spec, motivo in relatorio}
    linhas = [
        "| corredor | base_url | credencial | modelos | contexto | limite grátis | tools | models | cooldown | status |",
        "|---|---|---|---|---|---|:---:|:---:|---:|---|",
    ]
    for spec in FREE_PROVIDERS:
        credencial = spec.key_env or "anônimo (sem cadastro)"
        if spec.conta_id_env:
            credencial = f"{credencial} + {spec.conta_id_env}"
        if faltando.get(spec.nome):
            credencial += f" — ⚠️ {faltando[spec.nome]}"
        modelos = ", ".join(spec.modelos)
        status = spec.status
        linhas.append(
            f"| `{spec.nome}` | `{spec.base_url}` | {credencial} | {modelos} | {spec.contexto} | "
            f"{spec.cota} | {'✅' if spec.supports_tools else '—'} | "
            f"{'✅' if spec.supports_models else '—'} | {spec.cooldown:.0f}s | {status} |"
        )
    return "\n".join(linhas)


def relatorio_do_pool(env: dict[str, str] | None = None) -> list[tuple[FreeProviderSpec, str]]:
    """(ficha, motivo) por provedor: motivo vazio = pronto para entrar na corrida."""
    src = env if env is not None else os.environ
    return [(spec, _ficha_pronta(spec, src)[1]) for spec in FREE_PROVIDERS]


def secrets_faltando(env: dict[str, str] | None = None) -> list[str]:
    """Nomes dos secrets/variáveis que faltam para o pool inteiro entrar na corrida."""
    nomes: list[str] = []
    for spec, motivo in relatorio_do_pool(env):
        if not motivo:
            continue
        for nome in (spec.key_env, spec.conta_id_env):
            if nome and nome not in nomes:
                nomes.append(nome)
    return nomes


def descrever_pool(env: dict[str, str] | None = None) -> tuple[str, list[str]]:
    """Texto curto dos corredores ativos + lista do que falta cadastrar (para logs)."""
    relatorio = relatorio_do_pool(env)
    ativos = [spec.nome for spec, motivo in relatorio if not motivo]
    faltando = [f"{spec.nome} ({motivo})" for spec, motivo in relatorio if motivo]
    return ", ".join(ativos), faltando


# ---------------------------------------------------------------------------
# Gateways com chave de API (todos OpenAI-compatíveis).
# ---------------------------------------------------------------------------
KNOWN_GATEWAYS: dict[str, dict[str, Any]] = {
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "key_env": "OPENAI_API_KEY"},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "model": "llama-3.3-70b-versatile", "key_env": "GROQ_API_KEY"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "model": "openai/gpt-4o-mini", "key_env": "OPENROUTER_API_KEY"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "key_env": "DEEPSEEK_API_KEY"},
    "cerebras": {"base_url": "https://api.cerebras.ai/v1", "model": "llama-3.3-70b", "key_env": "CEREBRAS_API_KEY"},
    "mistral": {"base_url": "https://api.mistral.ai/v1", "model": "mistral-small-latest", "key_env": "MISTRAL_API_KEY"},
    "opencode-zen": {"base_url": "https://opencode.ai/zen/v1", "model": "deepseek-v4-flash", "key_env": "OPENCODE_API_KEY"},
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.5-flash",
        "key_env": "GEMINI_API_KEY",
    },
    # Gateways gratuitos do pool (sem cartão). "anon_key" = funciona sem cadastro.
    "kilo": {
        "base_url": "https://api.kilo.ai/api/gateway",
        "model": "qwen/qwen3-coder:free",
        "key_env": "KILOCODE_API_KEY",
        "anon_key": "anonymous",
    },
    "nvidia": {"base_url": "https://integrate.api.nvidia.com/v1", "model": "meta/llama-3.3-70b-instruct", "key_env": "NVIDIA_API_KEY"},
    "zai": {"base_url": "https://api.z.ai/api/paas/v4", "model": "glm-4.7-flash", "key_env": "ZAI_API_KEY"},
    "ollama": {"base_url": "https://api.ollama.com/v1", "model": "gpt-oss:120b", "key_env": "OLLAMA_API_KEY"},
    "zenmux": {"base_url": "https://zenmux.ai/api/v1", "model": "z-ai/glm-5.2-free", "key_env": "ZENMUX_API_KEY"},
    "siliconflow": {"base_url": "https://api.siliconflow.cn/v1", "model": "Qwen/Qwen3-8B", "key_env": "SILICONFLOW_API_KEY"},
    "modelscope": {"base_url": "https://api-inference.modelscope.cn/v1", "model": "Qwen/Qwen3.5-35B-A3B", "key_env": "MODELSCOPE_API_KEY"},
    "cohere": {"base_url": "https://api.cohere.ai/compatibility/v1", "model": "command-a-03-2025", "key_env": "COHERE_API_KEY"},
}


def resolve_gateway_key(provider: str, explicit_key: str, env: dict[str, str]) -> str:
    """Chave do provedor: LLM_API_KEY tem prioridade; senão usa <PROVEDOR>_API_KEY."""
    if explicit_key:
        return explicit_key
    meta = KNOWN_GATEWAYS.get(provider, {})
    key_env = meta.get("key_env", "")
    if key_env and env.get(key_env, "").strip():
        return env[key_env].strip()
    generic = env.get(f"{provider.upper().replace('-', '_')}_API_KEY", "").strip()
    if generic:
        return generic
    # Provedores com acesso anônimo oficial (ex.: Kilo) usam uma chave literal.
    return str(meta.get("anon_key", "") or "")


def build_gateway_provider(
    provider: str,
    api_key: str,
    model: str = "",
    base_url: str = "",
    models: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> ChatProvider:
    """
    Monta um provedor com chave a partir de LLM_PROVIDER/LLM_BASE_URL/LLM_MODEL/LLM_API_KEY.
    Qualquer gateway OpenAI-compatível funciona passando LLM_BASE_URL.
    """
    src = env if env is not None else os.environ
    provider = provider.strip().lower()

    meta = KNOWN_GATEWAYS.get(provider, {})
    resolved_base = (base_url or meta.get("base_url") or "").rstrip("/")
    if not resolved_base:
        raise ValueError(
            f"LLM_PROVIDER='{provider}' é desconhecido e LLM_BASE_URL não foi informado. "
            f"Opções conhecidas: {', '.join(sorted(KNOWN_GATEWAYS))}."
        )

    resolved_key = resolve_gateway_key(provider, api_key, src) or str(meta.get("anon_key", "") or "")
    if not resolved_key:
        expected = meta.get("key_env", f"{provider.upper().replace('-', '_')}_API_KEY")
        raise ValueError(
            f"LLM_PROVIDER='{provider}' exige chave de API. "
            f"Cadastre o secret {expected} (ou LLM_API_KEY) no GitHub Actions."
        )

    model_chain = [m.strip() for m in (models or []) if m.strip()]
    if model and model not in model_chain:
        model_chain.insert(0, model)
    if not model_chain:
        model_chain = [meta.get("model", "gpt-4o-mini")]

    return OpenAICompatibleHttpProvider(
        name=provider,
        endpoint_url=f"{resolved_base}/chat/completions",
        models=model_chain,
        headers={"Authorization": f"Bearer {resolved_key}"},
        supports_tools=True,
    )


if __name__ == "__main__":  # pragma: no cover - conveniência de linha de comando
    print(tabela_do_pool())
