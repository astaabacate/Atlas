"""
Configuração do bot farol a partir de variáveis de ambiente.
Apenas stdlib (sem dependências externas nesta etapa).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


class ConfigError(Exception):
    """Erro acionável de configuração."""
    pass


def _parse_cor(value: str | None) -> int | None:
    """Cor de destaque: aceita #RRGGBB, RRGGBB, 0xRRGGBB. Vazio ou 'auto' = medir do avatar."""
    v = (value or "").strip().lower()
    if not v or v in ("auto", "avatar", "automatico", "automático"):
        return None
    v = v.lstrip("#").removeprefix("0x")
    try:
        cor = int(v, 16)
    except ValueError:
        return None
    return cor if 0 <= cor <= 0xFFFFFF else None


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    v = value.strip().lower()
    return v in ("1", "true", "yes", "on", "sim", "s")


def _is_valid_discord_token(token: str) -> bool:
    if not token or not token.strip():
        return False
    t = token.strip()
    # Palavras de teste / placeholder conhecidas
    if t.lower() in ("inválido", "invalido", "invalid", "unused", "token", "none", "null"):
        return False
    # Um token de bot do Discord possui 3 partes separadas por ponto: id.timestamp.hmac
    parts = t.split(".")
    if len(parts) != 3:
        return False
    if len(t) < 40:
        return False
    return True


@dataclass(slots=True)
class Config:
    discord_token: str
    llm_provider: str = "auto"
    llm_model: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_models: list[str] = field(default_factory=list)
    disable_free_llms: bool = False
    llm_timeout: float = 60.0
    llm_max_tokens: int = 1024
    # Confirmação de ação destrutiva em lote. Padrão do dono: executa direto e informa
    # (o pedido já é a autorização). Ligue com CONFIRM_DESTRUCTIVE=true se quiser perguntar.
    confirm_destructive: bool = False
    # Ferramentas "terminais" (excluir/limpar) já devolvem a resposta pronta: responder com ela
    # economiza uma ida ao LLM inteira (~metade do tempo até a mensagem aparecer no Discord).
    direct_tool_reply: bool = True
    # Quando o modelo só PROMETE a ação (sem chamar ferramenta), cobra a ferramenta uma vez antes
    # de devolver o texto: era isso que fazia o cliente ter de pedir de novo.
    nudge_promise: bool = True
    max_tool_rounds: int = 3
    history_len: int = 10
    bulk_concurrency: int = 3
    api_timeout: float = 10.0
    log_level: str = "INFO"
    health_port: int | None = None
    disabled_apis: set[str] = field(default_factory=set)
    allowed_channel_ids: set[int] = field(default_factory=set)
    members_intent: bool = False
    message_content_intent: bool = False
    github_token: str = ""
    # Cara das respostas: mensagem em Components V2 (organizada) com a cor do farol.
    # ACCENT_COLOR vazio/"auto" = a cor é MEDIDA do avatar do bot; ou um hex (#5865F2).
    accent_color: int | None = None
    mensagem_v2: bool = True

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Config:
        src = env if env is not None else os.environ

        raw_token = src.get("DISCORD_TOKEN", "").strip()
        if not raw_token:
            raise ConfigError(
                "DISCORD_TOKEN não fornecido. "
                "Crie o bot em https://discord.com/developers/applications → Bot → Reset Token, "
                "e cadastre o secret DISCORD_TOKEN no GitHub Actions ou no seu ambiente local."
            )

        if not _is_valid_discord_token(raw_token):
            raise ConfigError(
                "DISCORD_TOKEN possui formato inválido. Um token de bot do Discord é composto "
                "por 3 segmentos separados por ponto (ex: ID.TIMESTAMP.HMAC). "
                "Gere um token válido em https://discord.com/developers/applications → Bot → Reset Token, "
                "e configure a variável DISCORD_TOKEN."
            )

        provider = src.get("LLM_PROVIDER", "auto").strip().lower() or "auto"
        model = src.get("LLM_MODEL", "").strip()
        base_url = src.get("LLM_BASE_URL", "").strip()
        api_key = src.get("LLM_API_KEY", "").strip()
        # Cadeia de fallback de modelos: LLM_MODELS="gpt-4o-mini,deepseek-v3-0324"
        llm_models = [
            item.strip()
            for item in src.get("LLM_MODELS", "").split(",")
            if item.strip()
        ]
        disable_free_llms = _parse_bool(src.get("DISABLE_FREE_LLMS"))

        try:
            timeout = float(src.get("LLM_TIMEOUT", "60").strip())
        except ValueError:
            timeout = 60.0

        try:
            max_tokens = int(src.get("LLM_MAX_TOKENS", "1024").strip())
        except ValueError:
            max_tokens = 1024

        confirm_destructive = _parse_bool(src.get("CONFIRM_DESTRUCTIVE"))
        direct_tool_reply = _parse_bool(src.get("DIRECT_TOOL_REPLY", "true"), default=True)
        nudge_promise = _parse_bool(src.get("NUDGE_PROMISE", "true"), default=True)

        try:
            max_tool_rounds = int(src.get("MAX_TOOL_ROUNDS", "3").strip())
        except ValueError:
            max_tool_rounds = 3

        try:
            history_len = int(src.get("HISTORY_LEN", "10").strip())
        except ValueError:
            history_len = 10

        try:
            bulk_concurrency = int(src.get("BULK_CONCURRENCY", "3").strip())
        except ValueError:
            bulk_concurrency = 3

        try:
            api_timeout = float(src.get("API_TIMEOUT", "10").strip())
        except ValueError:
            api_timeout = 10.0

        log_level = src.get("LOG_LEVEL", "INFO").strip().upper() or "INFO"

        health_port_raw = src.get("HEALTH_PORT", "").strip()
        health_port = int(health_port_raw) if health_port_raw.isdigit() else None

        disabled_apis_raw = src.get("DISABLED_APIS", "").strip()
        disabled_apis = {
            item.strip().lower()
            for item in disabled_apis_raw.split(",")
            if item.strip()
        }

        allowed_raw = src.get("ALLOWED_CHANNEL_IDS", "").strip()
        allowed_channel_ids = set()
        for item in allowed_raw.split(","):
            val = item.strip()
            if val.isdigit():
                allowed_channel_ids.add(int(val))

        members_intent = _parse_bool(src.get("MEMBERS_INTENT"))
        message_content_intent = _parse_bool(src.get("MESSAGE_CONTENT_INTENT"))
        github_token = src.get("GITHUB_TOKEN", "").strip()
        accent_color = _parse_cor(src.get("ACCENT_COLOR"))
        mensagem_v2 = _parse_bool(src.get("MENSAGEM_V2", "true"), default=True)

        return cls(
            discord_token=raw_token,
            llm_provider=provider,
            llm_model=model,
            llm_base_url=base_url,
            llm_api_key=api_key,
            llm_models=llm_models,
            disable_free_llms=disable_free_llms,
            confirm_destructive=confirm_destructive,
            direct_tool_reply=direct_tool_reply,
            nudge_promise=nudge_promise,
            llm_timeout=timeout,
            llm_max_tokens=max_tokens,
            max_tool_rounds=max_tool_rounds,
            history_len=history_len,
            bulk_concurrency=bulk_concurrency,
            api_timeout=api_timeout,
            log_level=log_level,
            health_port=health_port,
            disabled_apis=disabled_apis,
            allowed_channel_ids=allowed_channel_ids,
            members_intent=members_intent,
            message_content_intent=message_content_intent,
            github_token=github_token,
            accent_color=accent_color,
            mensagem_v2=mensagem_v2,
        )
