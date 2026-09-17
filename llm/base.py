"""
Classes base e estruturas de dados para provedores de LLM.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("farol.llm")


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
