"""
Provedores de LLM opcionais que utilizam chave de API (OpenAI, Anthropic, Gemini).
100% implementados via aiohttp (sem SDKs proprietários).
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from llm.base import ChatProvider, LLMResponse, ToolCall, parse_openai_tool_calls

logger = logging.getLogger("atlas.llm.key")


class OpenAIProvider(ChatProvider):
    name = "openai"
    supports_tools = True

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
    ) -> None:
        self.api_key = api_key
        self.model = model or "gpt-4o-mini"
        self.base_url = base_url.rstrip("/")
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
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with session.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"OpenAI error {resp.status}: {body[:200]}")
            data = await resp.json()
            msg = data["choices"][0]["message"]
            raw_tools = msg.get("tool_calls") or []
            tool_calls = parse_openai_tool_calls(raw_tools)
            return LLMResponse(content=msg.get("content") or "", tool_calls=tool_calls)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


class AnthropicProvider(ChatProvider):
    name = "anthropic"
    supports_tools = True

    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-5-haiku-20241022",
        base_url: str = "https://api.anthropic.com/v1",
    ) -> None:
        self.api_key = api_key
        self.model = model or "claude-3-5-haiku-20241022"
        self.base_url = base_url.rstrip("/")
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

        # Separar system prompt se houver
        system_content = ""
        claude_messages: list[dict[str, Any]] = []
        for m in messages:
            if m.get("role") == "system":
                system_content += ("\n" if system_content else "") + m.get("content", "")
            else:
                claude_messages.append({"role": m.get("role"), "content": m.get("content")})

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": claude_messages,
        }
        if system_content:
            payload["system"] = system_content

        if tools:
            # Converter schemas de OpenAI para Anthropic
            anthropic_tools = []
            for t in tools:
                fn = t.get("function", {})
                anthropic_tools.append({
                    "name": fn.get("name"),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {}),
                })
            payload["tools"] = anthropic_tools

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        async with session.post(
            f"{self.base_url}/messages",
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Anthropic error {resp.status}: {body[:200]}")
            data = await resp.json()

            content_text = ""
            tool_calls: list[ToolCall] = []
            for block in data.get("content", []):
                if block.get("type") == "text":
                    content_text += block.get("text", "")
                elif block.get("type") == "tool_use":
                    tool_calls.append(
                        ToolCall(
                            id=block.get("id", ""),
                            name=block.get("name", ""),
                            args=block.get("input", {}),
                        )
                    )

            return LLMResponse(content=content_text, tool_calls=tool_calls)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


class GeminiProvider(OpenAIProvider):
    """Google Gemini usando endpoint OpenAI-compatível."""

    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai",
    ) -> None:
        super().__init__(api_key=api_key, model=model or "gemini-2.0-flash", base_url=base_url)
