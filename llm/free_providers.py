"""
Implementação dos corredores LLM gratuitos e anônimos (sem cadastro/sem chave)
e do GitHub Models (usando GITHUB_TOKEN automático no GitHub Actions).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

from llm.base import ChatProvider, LLMResponse, ToolCall, parse_openai_tool_calls

logger = logging.getLogger("farol.llm.free")


class OpenAICompatibleHttpProvider(ChatProvider):
    """Provedor genérico para APIs compatíveis com o padrão OpenAI Chat Completions."""

    def __init__(
        self,
        name: str,
        endpoint_url: str,
        default_model: str,
        headers: dict[str, str] | None = None,
        supports_tools: bool = False,
    ) -> None:
        self.name = name
        self.endpoint_url = endpoint_url
        self.default_model = default_model
        self.headers = headers or {}
        self.supports_tools = supports_tools
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        timeout: float = 60.0,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        session = await self._get_session()
        payload: dict[str, Any] = {
            "model": self.default_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }

        if tools and self.supports_tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "FarolDiscordBot/1.0",
            **self.headers,
        }

        client_timeout = aiohttp.ClientTimeout(total=timeout)
        try:
            async with session.post(
                self.endpoint_url,
                json=payload,
                headers=headers,
                timeout=client_timeout,
            ) as resp:
                if resp.status != 200:
                    text_body = await resp.text()
                    raise RuntimeError(
                        f"Provedor {self.name} retornou status HTTP {resp.status}: {text_body[:200]}"
                    )

                data = await resp.json(content_type=None)
                choices = data.get("choices", [])
                if not choices:
                    raise RuntimeError(f"Provedor {self.name} retornou resposta vazia: {data}")

                msg = choices[0].get("message", {})
                content = msg.get("content") or ""
                raw_tools = msg.get("tool_calls") or []

                tool_calls: list[ToolCall] = []
                if raw_tools:
                    tool_calls = parse_openai_tool_calls(raw_tools)

                return LLMResponse(content=content, tool_calls=tool_calls)

        except Exception as exc:
            logger.debug("[%s] Falha na chamada: %s", self.name, exc)
            raise

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


class LLM7Provider(OpenAICompatibleHttpProvider):
    """Provedor gratuito llm7.io (~60 req/h anônimo)."""

    def __init__(self, model: str = "gpt-4o-mini-2024-07-18") -> None:
        super().__init__(
            name="llm7",
            endpoint_url="https://api.llm7.io/v1/chat/completions",
            default_model=model,
            headers={"Authorization": "Bearer unused"},
            supports_tools=True,
        )


class ZenProvider(OpenAICompatibleHttpProvider):
    """Provedor OpenCode Zen com modelo nemotron-3-ultra-free."""

    def __init__(self, model: str = "nemotron-3-ultra-free") -> None:
        super().__init__(
            name="zen",
            endpoint_url="https://opencode.ai/zen/v1/chat/completions",
            default_model=model,
            headers={"Authorization": "Bearer opencode"},
            supports_tools=False,
        )


class KiloProvider(OpenAICompatibleHttpProvider):
    """Provedor gratuito Kilo Code (~200 req/h)."""

    def __init__(self, model: str = "kilo-auto/free") -> None:
        super().__init__(
            name="kilo",
            endpoint_url="https://api.kilo.ai/v1/chat/completions",
            default_model=model,
            headers={},
            supports_tools=False,
        )


class OVHProvider(OpenAICompatibleHttpProvider):
    """Provedor OVHcloud AI Endpoints (anônimo, ~2 req/min)."""

    def __init__(self, model: str = "Meta-Llama-3_3-70B-Instruct") -> None:
        super().__init__(
            name="ovh",
            endpoint_url="https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/chat/completions",
            default_model=model,
            headers={},
            supports_tools=False,
        )


class PollinationsProvider(OpenAICompatibleHttpProvider):
    """Provedor gratuito Pollinations AI."""

    def __init__(self, model: str = "openai") -> None:
        super().__init__(
            name="pollinations",
            endpoint_url="https://text.pollinations.ai/openai",
            default_model=model,
            headers={},
            supports_tools=False,
        )


class GitHubModelsProvider(OpenAICompatibleHttpProvider):
    """
    Provedor GitHub Models usando o GITHUB_TOKEN gerado automaticamente pelo Actions.
    Possui suporte estável e nativo a tool/function calling.
    """

    def __init__(self, github_token: str, model: str = "gpt-4o-mini") -> None:
        super().__init__(
            name="github_models",
            endpoint_url="https://models.inference.ai.azure.com/chat/completions",
            default_model=model,
            headers={"Authorization": f"Bearer {github_token}"},
            supports_tools=True,
        )


class BlackboxProvider(OpenAICompatibleHttpProvider):
    """Provedor Blackbox AI."""

    def __init__(self, model: str = "blackboxai/openai/gpt-5.5") -> None:
        super().__init__(
            name="blackbox",
            endpoint_url="https://api.blackbox.ai/chat/completions",
            default_model=model,
            headers={},
            supports_tools=False,
        )
