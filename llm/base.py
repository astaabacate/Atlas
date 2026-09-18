"""
Classes base e estruturas de dados para provedores de LLM.
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("farol.llm")


class ProviderError(RuntimeError):
    """Falha de um provedor LLM com metadados para decisão de retry/fallback."""

    def __init__(
        self,
        provider: str,
        message: str,
        status: int | None = None,
        model: str = "",
        html_body: bool = False,
        retry_after: float | None = None,
        empty_response: bool = False,
        truncated: bool = False,
    ) -> None:
        self.provider = provider
        self.status = status
        self.model = model
        self.html_body = html_body
        self.raw_message = message
        # Segundos pedidos pelo provedor no header Retry-After (quando veio).
        self.retry_after = retry_after
        # Resposta sem conteúdo e sem tool_calls; `truncated` diz que faltou teto de tokens
        # (modelo de raciocínio gastou tudo "pensando"), então vale repetir com mais espaço.
        self.empty_response = empty_response
        self.truncated = truncated
        super().__init__(message)

    @property
    def is_empty_response(self) -> bool:
        """True quando o modelo não devolveu nada (nem texto, nem ferramenta)."""
        return self.empty_response

    @property
    def is_rate_limited(self) -> bool:
        """True quando o provedor recusou por fila/limite (HTTP 429 e afins)."""
        if self.status == 429:
            return True
        blob = self.raw_message.lower()
        return any(
            marker in blob
            for marker in ("rate limit", "rate-limit", "too many requests", "queue full", "quota")
        )

    @property
    def is_transient(self) -> bool:
        """Falha passageira: vale repetir a corrida depois de uma pausa curta."""
        if self.is_rate_limited:
            return True
        if self.status is not None and self.status >= 500:
            return True
        blob = self.raw_message.lower()
        return any(
            marker in blob
            for marker in ("timeout", "timed out", "falha de rede", "connection", "temporarily")
        )

    @property
    def is_model_problem(self) -> bool:
        """True quando o provedor rejeitou o MODELO (vale tentar o próximo da lista)."""
        if self.status not in (400, 404, 422):
            return False
        # Página HTML de erro (Vercel/nginx/CDN) significa URL/caminho errado,
        # não modelo indisponível — trocar de modelo só queimaria o resto da lista.
        if self.html_body:
            return False
        blob = self.raw_message.lower()
        if "<html" in blob or "<!doctype" in blob:
            return False
        markers = (
            "model",
            "unavailable",
            "not found",
            "does not exist",
            "no such model",
            "invalid model",
        )
        return any(marker in blob for marker in markers)

    @property
    def is_tools_rejection(self) -> bool:
        """True quando o provedor rejeitou o schema de `tools`/function calling."""
        if self.status not in (400, 404, 422):
            return False
        if self.html_body:
            return False
        blob = self.raw_message.lower()
        if "<html" in blob or "<!doctype" in blob:
            return False
        return ("tool" in blob or "function_call" in blob or "function calling" in blob) and (
            "not support" in blob
            or "unsupported" in blob
            or "invalid" in blob
            or "unknown" in blob
            or "unexpected" in blob
        )


def compact_error_text(text: str, limit: int = 160) -> str:
    """Reduz um corpo de erro (às vezes HTML puro) a uma linha curta e legível."""
    if not text:
        return "corpo vazio"
    cleaned = re.sub(r"<script.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<style.*?</style>", " ", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1].rstrip() + "…"
    return cleaned or "corpo ilegível"


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class ChatProvider(ABC):
    """Classe base abstrata para todos os provedores de chat LLM."""

    name: str = "base"
    # True quando o provedor aceita o schema OpenAI de `tools` (function calling nativo).
    supports_tools: bool = False

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        timeout: float = 60.0,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Envia mensagens e schemas de ferramentas para o modelo e retorna a resposta estruturada."""
        pass

    async def close(self) -> None:
        """Fecha quaisquer recursos abertos (ex: sessões HTTP)."""
        pass


def parse_openai_tool_calls(raw_calls: list[dict[str, Any]]) -> list[ToolCall]:
    """Converte tool_calls do formato OpenAI para a classe ToolCall interna."""
    result: list[ToolCall] = []
    for item in raw_calls:
        call_id = item.get("id", "")
        function_data = item.get("function", {})
        name = function_data.get("name", "")
        raw_args = function_data.get("arguments", "{}")

        args: dict[str, Any] = {}
        if isinstance(raw_args, dict):
            args = raw_args
        elif isinstance(raw_args, str):
            try:
                args = json.loads(raw_args)
            except Exception:
                args = {}

        if name:
            result.append(ToolCall(id=call_id, name=name, args=args))
    return result


def summarize_tools(tools: list[dict[str, Any]], limit: int = 40) -> str:
    """Lista compacta de ferramentas (nome + descrição) para o protocolo de texto."""
    lines: list[str] = []
    for tool in tools[:limit]:
        fn = tool.get("function", {}) if isinstance(tool, dict) else {}
        name = fn.get("name", "")
        if not name:
            continue
        desc = (fn.get("description") or "").strip().splitlines()[0] if fn.get("description") else ""
        params = fn.get("parameters", {}).get("properties", {}) or {}
        required = set(fn.get("parameters", {}).get("required", []) or [])
        param_txt = ", ".join(
            f"{key}{'*' if key in required else ''}" for key in list(params)[:12]
        )
        lines.append(f"- {name}({param_txt}) — {desc[:120]}")
    return "\n".join(lines)


TOOL_PROTOCOL_TEMPLATE = """PROTOCOLO DE FERRAMENTAS (você NÃO tem function calling nativo nesta conexão):
Para executar uma ação, responda com UM bloco markdown exatamente neste formato:

```tool
{{"name": "NOME_DA_FERRAMENTA", "args": {{"chave": "valor"}}}}
```

Regras do protocolo:
1. Use apenas ferramentas da lista abaixo; os nomes devem ser idênticos.
2. Um bloco por resposta. Se precisar de várias ações, comece pela mais importante.
3. Nunca invente campos: use apenas os parâmetros listados (`*` = obrigatório).
4. Se não precisar de ferramenta, responda normalmente em texto (sem bloco).

Ferramentas disponíveis:
{tools}
"""


def build_tool_protocol_notice(tools: list[dict[str, Any]]) -> str:
    """Mensagem de sistema que ensina o modelo a emitir ```tool {...}``` sem function calling."""
    return TOOL_PROTOCOL_TEMPLATE.format(tools=summarize_tools(tools))


def sanitize_messages_for_plain_text(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Converte um histórico OpenAI (com role=tool e assistant.tool_calls) em mensagens
    que um provedor SEM function calling aceita: apenas system/user/assistant com texto.
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content") or ""

        if role == "tool":
            label = msg.get("name") or "ferramenta"
            out.append({
                "role": "user",
                "content": f"[Resultado da ferramenta {label}]\n{content}".strip(),
            })
            continue

        if role == "assistant":
            calls = msg.get("tool_calls") or []
            if calls and not content:
                rendered = "; ".join(
                    f"{c.get('function', {}).get('name', '?')}({c.get('function', {}).get('arguments', '')})"
                    for c in calls
                )
                content = f"[Ação solicitada: {rendered}]"
            out.append({"role": "assistant", "content": content})
            continue

        if role == "system":
            out.append({"role": "system", "content": content})
            continue

        out.append({"role": "user", "content": content})
    return out
