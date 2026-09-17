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
    llm_timeout: float = 60.0
    llm_max_tokens: int = 1024
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

        try:
            timeout = float(src.get("LLM_TIMEOUT", "60").strip())
        except ValueError:
            timeout = 60.0

        try:
            max_tokens = int(src.get("LLM_MAX_TOKENS", "1024").strip())
        except ValueError:
            max_tokens = 1024

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

        return cls(
            discord_token=raw_token,
            llm_provider=provider,
            llm_model=model,
            llm_base_url=base_url,
            llm_api_key=api_key,
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
        )
