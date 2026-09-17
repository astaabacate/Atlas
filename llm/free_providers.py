"""
Provedores LLM via HTTP no padrão OpenAI Chat Completions.

Dois grupos vivem aqui:
1. Corredores anônimos (sem chave): llm7, OVH AI Endpoints e Pollinations.
2. Gateways com chave (OpenRouter, Groq, DeepSeek, Cerebras, Mistral, custom).

Histórico importante (o motivo de vários corredores antigos terem sumido):
- GitHub Models: endpoint Azure (models.inference.ai.azure.com) desligado em 17/10/2025 e o
  serviço GitHub Models foi aposentado por completo em 30/07/2026. Não existe mais corrida
  gratuita com GITHUB_TOKEN, por isso o corredor foi removido.
- OpenCode Zen: passou a exigir login + cartão + chave paga (401 "Invalid API key" com
  "Bearer opencode"). Saiu da lista de anônimos; funciona como gateway com chave via LLM_*.
- Kilo (api.kilo.ai) e Blackbox (api.blackbox.ai): os endpoints /v1/chat/completions
  respondem 404 (HTML) — caminhos inexistentes. Removidos para não gastar tempo de corrida.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Any, Callable

import aiohttp

from llm.base import (
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
    ) -> None:
        candidate_models = [m for m in (models or []) if m]
        if default_model and default_model not in candidate_models:
            candidate_models.insert(0, default_model)
        if not candidate_models:
            raise ValueError(f"Provedor {name} exige ao menos um modelo configurado.")

        self.name = name
        self.endpoint_url = endpoint_url
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
        # (foi assim que o llm7 passou a devolver 400 "Model ... is currently unavailable").
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
            # Catálogo num namespace diferente do esperado (ex.: aliases do pollinations):
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
                    espera = exc.retry_after if exc.retry_after is not None else DEFAULT_COOLDOWN
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
                                self._start_cooldown(retry_exc.retry_after or DEFAULT_COOLDOWN)
                                raise
                            exc = retry_exc

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

        if not content and not tool_calls:
            raise ProviderError(
                provider=self.name,
                message=f"{self.name}: resposta vazia ({model})",
                model=model,
            )
        return LLMResponse(content=content, tool_calls=tool_calls)


# ---------------------------------------------------------------------------
# Corredores anônimos (sem chave). Melhor esforço: serviços gratuitos mudam
# modelos/limites com frequência, por isso cada um carrega uma lista de fallback.
# ---------------------------------------------------------------------------
class LLM7Provider(OpenAICompatibleHttpProvider):
    """
    llm7.io — OpenAI-compatível, sem chave (limite por hora no anônimo).

    O catálogo desse provedor muda sem aviso (o slug `qwen2.5-coder-32b`, por exemplo, foi
    aposentado e derrubava a corrida inteira com HTTP 400). Por isso a lista configurada é só
    um ponto de partida: `refresh_models()` descobre os modelos atuais no /v1/models.
    """

    def __init__(
        self,
        models: list[str] | None = None,
        api_key: str = "",
        session_factory: SessionFactory | None = None,
    ) -> None:
        super().__init__(
            name="llm7",
            endpoint_url="https://api.llm7.io/v1/chat/completions",
            models=models or [
                "gpt-4o-mini",
                "gpt-oss-120b",
                "deepseek-v3-0324",
                "mistral-small-3.1-24b",
            ],
            headers={"Authorization": f"Bearer {api_key or 'unused'}"},
            supports_tools=True,
            session_factory=session_factory,
        )


class OVHProvider(OpenAICompatibleHttpProvider):
    """OVHcloud AI Endpoints — anônimo com limite baixo de requisições."""

    def __init__(
        self,
        models: list[str] | None = None,
        session_factory: SessionFactory | None = None,
    ) -> None:
        super().__init__(
            name="ovh",
            endpoint_url="https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/chat/completions",
            models=models or [
                "Meta-Llama-3_3-70B-Instruct",
                "Qwen3-Coder-30B-A3B-Instruct",
                "Llama-3.1-8B-Instruct",
            ],
            headers={},
            supports_tools=False,
            session_factory=session_factory,
        )


class PollinationsProvider(OpenAICompatibleHttpProvider):
    """
    Pollinations — API legada anônima. Só os aliases `openai`/`openai-fast` seguem
    liberados sem token; os demais retornam 404 "Model not found".
    """

    def __init__(
        self,
        models: list[str] | None = None,
        token: str = "",
        session_factory: SessionFactory | None = None,
    ) -> None:
        url = "https://text.pollinations.ai/openai"
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        super().__init__(
            name="pollinations",
            endpoint_url=url,
            models=models or ["openai", "openai-fast"],
            headers=headers,
            supports_tools=False,
            session_factory=session_factory,
            models_url="https://text.pollinations.ai/models",
            discovery_can_replace=False,
        )


def build_anonymous_runners(env: dict[str, str] | None = None) -> list[ChatProvider]:
    """Corredores gratuitos ativados por padrão (podem ser desligados com DISABLE_FREE_LLMS)."""
    src = env if env is not None else os.environ
    runners: list[ChatProvider] = [
        LLM7Provider(api_key=src.get("LLM7_API_KEY", "").strip()),
        OVHProvider(),
        PollinationsProvider(token=src.get("POLLINATIONS_TOKEN", "").strip()),
    ]
    return runners


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
}


def resolve_gateway_key(provider: str, explicit_key: str, env: dict[str, str]) -> str:
    """Chave do provedor: LLM_API_KEY tem prioridade; senão usa <PROVEDOR>_API_KEY."""
    if explicit_key:
        return explicit_key
    meta = KNOWN_GATEWAYS.get(provider, {})
    key_env = meta.get("key_env", "")
    if key_env and env.get(key_env, "").strip():
        return env[key_env].strip()
    return env.get(f"{provider.upper().replace('-', '_')}_API_KEY", "").strip()


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

    resolved_key = resolve_gateway_key(provider, api_key, src)
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
