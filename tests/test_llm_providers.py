"""
Testes da camada de provedores LLM (sem rede):
fallback de modelos, protocolo de ferramentas em texto, sanitização de histórico,
degradação quando o provedor recusa `tools`, compactação de erros HTML e a
mensagem de falha do AutoProvider.
"""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any

from llm.auto import AutoProvider
from llm.base import ChatProvider, LLMResponse, ProviderError, sanitize_messages_for_plain_text
from llm.free_providers import (
    LLM7Provider,
    OVHProvider,
    OpenAICompatibleHttpProvider,
    PollinationsProvider,
    build_anonymous_runners,
    build_gateway_provider,
)

FAKE_TOOL_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "create_channels",
            "description": "Cria canais no servidor.",
            "parameters": {
                "type": "object",
                "properties": {"names": {"type": "array"}, "confirmed": {"type": "boolean"}},
                "required": ["names"],
            },
        },
    }
]


class FakeResponse:
    def __init__(self, status: int = 200, payload: dict[str, Any] | None = None, text: str = "") -> None:
        self.status = status
        self._payload = payload
        self._text = text if text else json.dumps(payload or {})

    async def text(self) -> str:
        return self._text

    async def json(self, content_type: str | None = None) -> Any:
        if self._payload is None:
            raise ValueError("não é JSON")
        return self._payload

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class FakeSession:
    """Sessão aiohttp falsa: devolve as respostas programadas e grava as chamadas."""

    closed = False

    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, json: Any = None, headers: Any = None, timeout: Any = None) -> FakeResponse:
        self.calls.append({"url": url, "payload": json, "headers": headers})
        if not self.responses:
            raise AssertionError("FakeSession sem respostas programadas")
        return self.responses.pop(0)

    async def close(self) -> None:
        self.closed = True


def ok_payload(content: str = "ok", tool_calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message}]}


HISTORY_WITH_TOOL_ROUND = [
    {"role": "system", "content": "Você é o farol."},
    {"role": "user", "content": "cria um canal"},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "create_channels", "arguments": "{}"}}
        ],
    },
    {"role": "tool", "tool_call_id": "c1", "name": "create_channels", "content": "Canal #teste criado."},
]


class TestHttpProvider(unittest.TestCase):
    def _provider(self, responses: list[FakeResponse], **kwargs: Any) -> tuple[OpenAICompatibleHttpProvider, FakeSession]:
        session = FakeSession(responses)
        provider = OpenAICompatibleHttpProvider(
            name=kwargs.pop("name", "fake"),
            endpoint_url="https://example.invalid/v1/chat/completions",
            models=kwargs.pop("models", ["model-a", "model-b"]),
            supports_tools=kwargs.pop("supports_tools", False),
            session_factory=lambda: session,
            **kwargs,
        )
        return provider, session

    def test_model_fallback_when_model_unavailable(self) -> None:
        provider, session = self._provider([
            FakeResponse(400, text='{"error":{"message":"Model \'model-a\' is currently unavailable."}}'),
            FakeResponse(200, ok_payload("feito")),
        ])
        resp = asyncio.run(provider.chat(messages=[{"role": "user", "content": "oi"}]))
        self.assertEqual(resp.content, "feito")
        self.assertEqual([c["payload"]["model"] for c in session.calls], ["model-a", "model-b"])

    def test_non_tool_provider_uses_text_protocol_and_sanitizes_history(self) -> None:
        provider, session = self._provider([FakeResponse(200, ok_payload('```tool\n{"name": "create_channels", "args": {"names": ["x"]}}\n```'))])
        asyncio.run(provider.chat(messages=HISTORY_WITH_TOOL_ROUND, tools=FAKE_TOOL_SCHEMA))

        payload = session.calls[0]["payload"]
        self.assertNotIn("tools", payload)
        roles = [m["role"] for m in payload["messages"]]
        self.assertNotIn("tool", roles)
        joined = "\n".join(m["content"] for m in payload["messages"])
        self.assertIn("PROTOCOLO DE FERRAMENTAS", joined)
        self.assertIn("create_channels(names*", joined)
        self.assertIn("[Resultado da ferramenta create_channels]", joined)

    def test_native_tool_provider_sends_tools_and_parses_calls(self) -> None:
        calls = [{"id": "c9", "type": "function", "function": {"name": "create_channels", "arguments": '{"names": ["a"]}'}}]
        provider, session = self._provider(
            [FakeResponse(200, ok_payload("", tool_calls=calls))],
            supports_tools=True,
        )
        resp = asyncio.run(provider.chat(messages=[{"role": "user", "content": "oi"}], tools=FAKE_TOOL_SCHEMA))
        payload = session.calls[0]["payload"]
        self.assertIn("tools", payload)
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertTrue(resp.has_tool_calls)
        self.assertEqual(resp.tool_calls[0].name, "create_channels")
        self.assertEqual(resp.tool_calls[0].args, {"names": ["a"]})

    def test_tools_rejection_degrades_to_text_protocol(self) -> None:
        provider, session = self._provider([
            FakeResponse(400, text='{"error":"tools parameter is not supported by this model"}'),
            FakeResponse(200, ok_payload("ok sem tools")),
        ], supports_tools=True)
        resp = asyncio.run(provider.chat(messages=[{"role": "user", "content": "oi"}], tools=FAKE_TOOL_SCHEMA))
        self.assertEqual(resp.content, "ok sem tools")
        self.assertTrue(provider.native_tools_rejected)
        self.assertNotIn("tools", session.calls[1]["payload"])

    def test_html_error_body_is_compacted(self) -> None:
        html = "<!DOCTYPE html><html><head><title>404</title></head><body><h1>Not Found</h1></body></html>"
        provider, _ = self._provider([FakeResponse(404, text=html)])
        with self.assertRaises(ProviderError) as ctx:
            asyncio.run(provider.chat(messages=[{"role": "user", "content": "oi"}]))
        message = str(ctx.exception)
        self.assertNotIn("<html", message)
        self.assertIn("HTTP 404", message)
        self.assertLess(len(message), 220)

    def test_network_failure_is_wrapped(self) -> None:
        class BoomSession(FakeSession):
            def post(self, *args: Any, **kwargs: Any) -> FakeResponse:
                raise OSError("getaddrinfo failed")

        session = BoomSession([])
        provider = OpenAICompatibleHttpProvider(
            name="boom",
            endpoint_url="https://example.invalid/v1/chat/completions",
            models=["m"],
            session_factory=lambda: session,
        )
        with self.assertRaises(ProviderError) as ctx:
            asyncio.run(provider.chat(messages=[{"role": "user", "content": "oi"}]))
        self.assertIn("falha de rede", str(ctx.exception))

    def test_empty_answer_is_an_error_not_a_win(self) -> None:
        provider, _ = self._provider([FakeResponse(200, {"choices": [{"message": {"content": ""}}]})])
        with self.assertRaises(ProviderError):
            asyncio.run(provider.chat(messages=[{"role": "user", "content": "oi"}]))


class TestSanitizeMessages(unittest.TestCase):
    def test_assistant_tool_calls_become_text(self) -> None:
        out = sanitize_messages_for_plain_text(HISTORY_WITH_TOOL_ROUND)
        self.assertEqual([m["role"] for m in out], ["system", "user", "assistant", "user"])
        self.assertIn("create_channels", out[2]["content"])


class FailingProvider(ChatProvider):
    def __init__(self, name: str, error: str) -> None:
        self.name = name
        self.error = error

    async def chat(self, messages: Any, tools: Any = None, timeout: float = 60.0, max_tokens: int = 1024) -> LLMResponse:
        raise RuntimeError(self.error)


class SlowProvider(ChatProvider):
    def __init__(self, name: str, delay: float, content: str) -> None:
        self.name = name
        self.delay = delay
        self.content = content

    async def chat(self, messages: Any, tools: Any = None, timeout: float = 60.0, max_tokens: int = 1024) -> LLMResponse:
        await asyncio.sleep(self.delay)
        return LLMResponse(content=self.content)


class TestAutoProvider(unittest.TestCase):
    def test_winner_is_the_first_success(self) -> None:
        auto = AutoProvider(providers=[
            SlowProvider("lento", 5.0, "tarde demais"),
            SlowProvider("rapido", 0.0, "venci"),
        ])
        resp = asyncio.run(auto.chat(messages=[{"role": "user", "content": "oi"}]))
        self.assertEqual(resp.content, "venci")
        self.assertEqual(auto.last_winner, "rapido")

    def test_failure_message_lists_every_provider_and_stays_short(self) -> None:
        html = "<!DOCTYPE html><html><body>404 page</body></html>"
        auto = AutoProvider(providers=[
            FailingProvider("a", "Cannot connect to host models.inference.ai.azure.com:443 [Name or service not known]"),
            FailingProvider("b", f"b: HTTP 404 — {html}"),
            FailingProvider("c", 'c: HTTP 401 — {"error":"Invalid API key."}'),
        ])
        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(auto.chat(messages=[{"role": "user", "content": "oi"}]))
        message = str(ctx.exception)
        for token in ("Cannot connect", "HTTP 404", "Invalid API key", "LLM_PROVIDER", "LLM_API_KEY"):
            self.assertIn(token, message)
        self.assertNotIn("<html", message)
        self.assertLess(len(message), 800)

    def test_describe_lists_runners(self) -> None:
        auto = AutoProvider.create_default(env={})
        names = [p.name for p in auto.providers]
        self.assertEqual(names, ["llm7", "ovh", "pollinations"])
        self.assertIn("llm7/tools", auto.describe())

    def test_dead_providers_are_gone(self) -> None:
        auto = AutoProvider.create_default(env={})
        names = {p.name for p in auto.providers}
        for dead in ("github_models", "zen", "kilo", "blackbox"):
            self.assertNotIn(dead, names)

    def test_disable_free_with_no_provider_raises(self) -> None:
        with self.assertRaises(ValueError):
            AutoProvider.create_default(disable_free=True, env={})

    def test_named_gateway_needs_key(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            AutoProvider.create_default(custom_provider="openrouter", env={})
        self.assertIn("OPENROUTER_API_KEY", str(ctx.exception))

    def test_custom_gateway_via_base_url(self) -> None:
        auto = AutoProvider.create_default(
            custom_provider="meu-gateway",
            custom_base_url="https://gateway.invalid/v1",
            custom_models=["modelo-1", "modelo-2"],
            api_key="sk-teste",
            disable_free=True,
            env={},
        )
        provider = auto.providers[0]
        self.assertEqual(provider.endpoint_url, "https://gateway.invalid/v1/chat/completions")
        self.assertEqual(provider.models, ["modelo-1", "modelo-2"])
        self.assertEqual(provider.headers["Authorization"], "Bearer sk-teste")

    def test_provider_specific_key_env_is_used(self) -> None:
        provider = build_gateway_provider("groq", api_key="", env={"GROQ_API_KEY": "gsk_x"})
        self.assertEqual(provider.headers["Authorization"], "Bearer gsk_x")
        self.assertTrue(provider.supports_tools)

    def test_unknown_provider_without_base_url_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            build_gateway_provider("nao-existe", api_key="k", env={})
        self.assertIn("LLM_BASE_URL", str(ctx.exception))


class TestAnonymousRunners(unittest.TestCase):
    def test_llm7_default_models_do_not_use_the_dead_pinned_version(self) -> None:
        provider = LLM7Provider()
        self.assertNotIn("gpt-4o-mini-2024-07-18", provider.models)
        self.assertIn("gpt-4o-mini", provider.models)
        self.assertTrue(provider.supports_tools)

    def test_pollinations_uses_free_legacy_aliases(self) -> None:
        provider = PollinationsProvider()
        self.assertEqual(provider.models, ["openai", "openai-fast"])
        self.assertEqual(provider.endpoint_url, "https://text.pollinations.ai/openai")

    def test_build_anonymous_runners(self) -> None:
        runners = build_anonymous_runners(env={"LLM7_API_KEY": " k "})
        self.assertEqual([r.name for r in runners], ["llm7", "ovh", "pollinations"])
        self.assertEqual(runners[0].headers["Authorization"], "Bearer k")

    def test_ovh_has_fallback_models(self) -> None:
        self.assertGreater(len(OVHProvider().models), 1)


if __name__ == "__main__":
    unittest.main()


class TestAgentWithPlainTextProvider(unittest.TestCase):
    """
    Integração real: Agent + provedor HTTP SEM function calling.
    Garante que o protocolo de texto fecha o ciclo (modelo emite ```tool, agente executa,
    e o resultado volta como texto puro na rodada seguinte).
    """

    def setUp(self) -> None:
        from types import SimpleNamespace

        perms = SimpleNamespace(administrator=True, manage_channels=True, manage_roles=True)
        self.actor = SimpleNamespace(id=1, guild_permissions=perms)
        self.guild = SimpleNamespace(
            name="Servidor Teste",
            id=12345,
            channels=[],
            categories=[],
            roles=[],
            me=SimpleNamespace(id=2, guild_permissions=perms, top_role=SimpleNamespace(position=100)),
            owner_id=1,
        )
        self.channel = SimpleNamespace(id=555, name="geral")

    def test_tool_executed_via_text_protocol(self) -> None:
        from brain.agent import Agent
        from brain.memory import ChannelMemory
        from types import SimpleNamespace

        created = SimpleNamespace(id=999, name="avisos")

        async def fake_create_text_channel(name, **kwargs):
            return created

        self.guild.create_text_channel = fake_create_text_channel

        tool_block = (
            "Criando agora:\n```tool\n"
            '{"name": "create_channels", "args": {"channels": [{"name": "avisos", "type": "text"}]}}\n```'
        )
        session = FakeSession([
            FakeResponse(200, ok_payload(tool_block)),
            FakeResponse(200, ok_payload("Pronto! Criei <#999>.")),
        ])
        provider = OVHProvider(models=["Meta-Llama-3_3-70B-Instruct"], session_factory=lambda: session)
        agent = Agent(llm_provider=provider, memory=ChannelMemory())

        result = asyncio.run(
            agent.process_turn(
                guild=self.guild,
                channel=self.channel,
                actor=self.actor,
                prompt="cria o canal avisos",
            )
        )

        self.assertIn("<#999>", result)
        self.assertEqual(len(session.calls), 2)
        second_payload = session.calls[1]["payload"]
        self.assertNotIn("tools", second_payload)
        roles = [m["role"] for m in second_payload["messages"]]
        self.assertNotIn("tool", roles)
        joined = "\n".join(m["content"] for m in second_payload["messages"])
        self.assertIn("[Resultado da ferramenta create_channels]", joined)
