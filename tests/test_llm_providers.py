"""
Testes da camada de provedores LLM (sem rede):
fallback de modelos, protocolo de ferramentas em texto, sanitização de histórico,
degradação quando o provedor recusa `tools`, compactação de erros HTML e a
mensagem de falha do AutoProvider.
"""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from typing import Any

from llm.auto import LLMUnavailableError, AutoProvider
from llm.base import ChatProvider, LLMResponse, ProviderError, sanitize_messages_for_plain_text
from llm.free_providers import (
    FREE_PROVIDERS,
    OpenAICompatibleHttpProvider,
    _parse_retry_after,
    build_free_runners,
    build_gateway_provider,
    descrever_pool,
    relatorio_do_pool,
    tabela_do_pool,
)

# Env fake com todas as credenciais do pool: usado para montar a corrida inteira nos testes.
SECRETS_DO_POOL = {
    "GEMINI_API_KEY": "x",
    "GROQ_API_KEY": "x",
    "MISTRAL_API_KEY": "x",
    "NVIDIA_API_KEY": "x",
    "ZAI_API_KEY": "x",
    "CLOUDFLARE_API_TOKEN": "x",
    "CLOUDFLARE_ACCOUNT_ID": "x",
    "OLLAMA_API_KEY": "x",
    "OPENROUTER_API_KEY": "x",
    "MODELSCOPE_API_KEY": "x",
    "SILICONFLOW_API_KEY": "x",
    "COHERE_API_KEY": "x",
}

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
    def __init__(self, status: int = 200, payload: dict[str, Any] | None = None, text: str = "",
                 headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.headers = dict(headers or {"Content-Type": "application/json"})
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
        # GETs (descoberta de modelos) têm fila própria: por padrão devolvem 404 e não
        # interferem nos testes que só se importam com o POST do chat.
        self.get_responses: list[FakeResponse] = []
        self.calls: list[dict[str, Any]] = []
        self.gets: list[dict[str, Any]] = []

    def post(self, url: str, json: Any = None, headers: Any = None, timeout: Any = None) -> FakeResponse:
        self.calls.append({"url": url, "payload": json, "headers": headers})
        if not self.responses:
            raise AssertionError("FakeSession sem respostas programadas")
        return self.responses.pop(0)

    def get(self, url: str, headers: Any = None, timeout: Any = None) -> FakeResponse:
        self.gets.append({"url": url, "headers": headers})
        if not self.get_responses:
            return FakeResponse(404, {"error": "sem catálogo neste teste"})
        return self.get_responses.pop(0)

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


def provider_de_teste(session: FakeSession, **extra: Any) -> OpenAICompatibleHttpProvider:
    """Provedor neutro para os testes de HTTP (os provedores reais mudam de nome)."""
    kwargs: dict[str, Any] = {
        "name": "provedor-de-teste",
        "endpoint_url": "https://provedor.inválido/v1/chat/completions",
        "models": ["modelo-a", "modelo-b"],
        "session_factory": lambda: session,
    }
    kwargs.update(extra)
    return OpenAICompatibleHttpProvider(**kwargs)


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

    def test_429_uses_retry_after_and_gets_a_second_chance(self) -> None:
        """'Queue full for IP' (429) não pode derrubar o turno: espera e tenta de novo."""
        session = FakeSession([
            FakeResponse(429, {"error": "Queue full for IP"}, headers={"Retry-After": "0.05"}),
            FakeResponse(200, ok_payload("consegui depois da fila")),
        ])
        provider = provider_de_teste(session)

        resp = asyncio.run(provider.chat(messages=[{"role": "user", "content": "oi"}]))

        self.assertEqual(resp.content, "consegui depois da fila")
        self.assertEqual(len(session.calls), 2)
        self.assertFalse(provider.cooling_down, "depois de vencer, o provedor sai do castigo")

    def test_429_without_retry_after_benches_the_provider(self) -> None:
        session = FakeSession([
            FakeResponse(429, {"error": "rate limit exceeded"}),
            FakeResponse(429, {"error": "rate limit exceeded"}),
        ])
        provider = provider_de_teste(session)

        with self.assertRaises(ProviderError) as ctx:
            asyncio.run(provider.chat(messages=[{"role": "user", "content": "oi"}]))

        self.assertTrue(ctx.exception.is_rate_limited)
        self.assertTrue(provider.cooling_down, "quem estoura o limite fica de castigo")

    def test_dead_model_triggers_catalog_discovery_and_fallback(self) -> None:
        """Modelo aposentado no provedor: em vez de insistir, descobre os atuais."""
        session = FakeSession([
            FakeResponse(400, {"error": "Model modelo-aposentado-32b is currently unavailable"}),
            FakeResponse(200, ok_payload("respondi com o modelo novo")),
        ])
        session.get_responses.append(
            FakeResponse(200, {"data": [{"id": "modelo-aposentado-32b"}, {"id": "gpt-oss-120b"}]}))
        provider = OpenAICompatibleHttpProvider(
            name="provedor-de-teste",
            endpoint_url="https://provedor.inválido/v1/chat/completions",
            models=["modelo-aposentado-32b", "modelo-de-reserva"],
            supports_tools=True,
            session_factory=lambda: session,
        )

        resp = asyncio.run(provider.chat(messages=[{"role": "user", "content": "oi"}]))

        self.assertEqual(resp.content, "respondi com o modelo novo")
        self.assertIn("gpt-oss-120b", provider.models, "o catálogo descoberto entra na lista")
        self.assertEqual(provider.models[0], "gpt-oss-120b", "e o modelo morto sai da frente")
        self.assertTrue(all(g["url"] == "https://provedor.inválido/v1/models" for g in session.gets))
        self.assertGreaterEqual(len(session.gets), 1)
        self.assertEqual([c["payload"]["model"] for c in session.calls],
                         ["modelo-aposentado-32b", "gpt-oss-120b"],
                         "o slug morto é tentado uma vez e o catálogo descoberto assume")

    def test_discovery_does_not_replace_a_curated_list_with_unknown_ids(self) -> None:
        """Catálogo em outro namespace não pode sobrescrever a lista que funciona."""
        provider = OpenAICompatibleHttpProvider(
            name="teste",
            endpoint_url="https://exemplo.inválido/v1/chat/completions",
            models=["alias-bom", "alias-bom-fast"],
            discovery_can_replace=False,
        )
        self.assertFalse(provider.discovery_can_replace)
        self.assertEqual(provider.models, ["alias-bom", "alias-bom-fast"])

    def test_retry_after_parsing_is_sane(self) -> None:
        self.assertEqual(_parse_retry_after({"Retry-After": "12"}), 12.0)
        self.assertEqual(_parse_retry_after({"Retry-After": "9999"}), 300.0)
        self.assertIsNone(_parse_retry_after({"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}))
        self.assertIsNone(_parse_retry_after({}))
        self.assertIsNone(_parse_retry_after(None))

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


class AlwaysFailingProvider(ChatProvider):
    """Sempre falha com o status/mensagem pedidos; conta quantas vezes foi chamado."""

    def __init__(self, name: str, status: int = 429, message: str = "rate limit exceeded",
                 retry_after: float | None = None) -> None:
        self.name = name
        self.status = status
        self.message = message
        self.retry_after = retry_after
        self.chamadas = 0

    async def chat(self, messages: Any, tools: Any = None, timeout: float = 60.0, max_tokens: int = 1024) -> LLMResponse:
        self.chamadas += 1
        raise ProviderError(self.name, f"{self.name}: HTTP {self.status} — {self.message}",
                            status=self.status, model="m", retry_after=self.retry_after)


class FlakyProvider(ChatProvider):
    """Falha nas primeiras `falhas` chamadas (429 por padrão) e depois responde."""

    def __init__(self, name: str, content: str = "voltei", falhas: int = 1,
                 status: int = 429, retry_after: float | None = None) -> None:
        self.name = name
        self.content = content
        self.falhas = falhas
        self.status = status
        self.retry_after = retry_after
        self.chamadas = 0

    async def chat(self, messages: Any, tools: Any = None, timeout: float = 60.0, max_tokens: int = 1024) -> LLMResponse:
        self.chamadas += 1
        if self.chamadas <= self.falhas:
            raise ProviderError(self.name, f"{self.name}: HTTP {self.status} — fila cheia",
                                status=self.status, model="m", retry_after=self.retry_after)
        return LLMResponse(content=self.content)


def corrida(*providers: ChatProvider, waves: int = 2) -> AutoProvider:
    auto = AutoProvider(providers=list(providers))
    auto.max_waves = waves
    auto.wave_delay = 0.01
    return auto


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

    def test_benched_runner_is_not_called_again_while_another_answers(self) -> None:
        """Quem estourou o limite (429) sai da frente: não pode ser martelado a cada mensagem."""
        morto = AlwaysFailingProvider("corredor-alfa", 429, retry_after=30.0)
        vivo = SlowProvider("corredor-beta", 0.0, "respondi")
        auto = corrida(morto, vivo)

        asyncio.run(auto.chat(messages=[{"role": "user", "content": "oi"}]))
        asyncio.run(auto.chat(messages=[{"role": "user", "content": "oi de novo"}]))

        self.assertEqual(vivo.delay, 0.0)
        self.assertEqual(morto.chamadas, 1, "o corredor de castigo não é chamado de novo à toa")
        self.assertIn("corredor-alfa", auto.castigados())

    def test_second_wave_saves_the_turn_when_everyone_fails_at_first(self) -> None:
        """Todos os corredores com 429/fila cheia na primeira onda: a segunda resolve."""
        teimoso = FlakyProvider("corredor-gama", "segunda tentativa", falhas=1, retry_after=5.0)
        auto = corrida(teimoso, waves=2)

        resp = asyncio.run(auto.chat(messages=[{"role": "user", "content": "oi"}]))

        self.assertEqual(resp.content, "segunda tentativa")
        self.assertGreaterEqual(teimoso.chamadas, 2)
        self.assertEqual(auto.last_failure_transient, False)

    def test_single_wave_still_works_when_configured(self) -> None:
        teimoso = FlakyProvider("corredor-gama", "nunca chego", falhas=1)
        auto = corrida(teimoso, waves=1)
        with self.assertRaises(LLMUnavailableError):
            asyncio.run(auto.chat(messages=[{"role": "user", "content": "oi"}]))
        self.assertEqual(teimoso.chamadas, 1)

    def test_total_failure_is_flagged_transient_with_a_friendly_message(self) -> None:
        auto = corrida(
            AlwaysFailingProvider("corredor-alfa", 400, "Model modelo-aposentado is currently unavailable"),
            AlwaysFailingProvider("corredor-beta", 429, "API rate limit exceeded"),
            AlwaysFailingProvider("corredor-gama", 429, "Queue full for IP"),
        )

        with self.assertRaises(LLMUnavailableError) as ctx:
            asyncio.run(auto.chat(messages=[{"role": "user", "content": "oi"}]))

        erro = ctx.exception
        self.assertTrue(erro.transient, "429/fila cheia é falha passageira")
        self.assertIn("corredor-beta", str(erro))
        self.assertIn("LLM_API_KEY", str(erro))

        from core.bot import FarolBot
        mensagem = FarolBot._mensagem_de_erro(erro)
        self.assertIn("fila cheia", mensagem)
        self.assertNotIn("HTTP", mensagem, "o cliente não deve ver o dump técnico dos provedores")
        self.assertNotIn("verifique as permissões", mensagem)

    def test_hard_failure_is_not_flagged_transient(self) -> None:
        auto = corrida(AlwaysFailingProvider("meu-gateway", 401, "Invalid API key"))
        with self.assertRaises(LLMUnavailableError) as ctx:
            asyncio.run(auto.chat(messages=[{"role": "user", "content": "oi"}]))
        self.assertFalse(ctx.exception.transient)

    def test_describe_lists_runners(self) -> None:
        """Sem chave nenhuma, o pool entrega o corredor anônimo (Kilo)."""
        auto = AutoProvider.create_default(env={})
        names = [p.name for p in auto.providers]
        self.assertEqual(names, ["kilo"])
        self.assertIn("kilo/tools", auto.describe())

    def test_pool_cresce_conforme_as_chaves_gratuitas_aparecem(self) -> None:
        auto = AutoProvider.create_default(env={"GROQ_API_KEY": "gsk", "GEMINI_API_KEY": "gk"})
        names = [p.name for p in auto.providers]
        self.assertEqual(names, ["kilo", "gemini", "groq"])

    def test_provedores_mortos_e_removidos_ficam_fora(self) -> None:
        auto = AutoProvider.create_default(env={"LLM7_API_KEY": "x", "POLLINATIONS_TOKEN": "y"})
        names = {p.name for p in auto.providers}
        # aposentados/pagos que já saíram da lista e os 3 removidos nesta limpeza
        for morto in ("github_models", "zen", "blackbox", "llm7", "ovh", "pollinations", "cerebras"):
            self.assertNotIn(morto, names, f"{morto} não pode voltar para a corrida")

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


class TestTabelaDoPool(unittest.TestCase):
    """A config final precisa sair já com as colunas pedidas pelo dono."""

    def test_tabela_traz_colunas_e_status(self) -> None:
        tabela = tabela_do_pool(env={})
        for coluna in ("base_url", "credencial", "modelos", "contexto", "limite grátis",
                       "tools", "models", "cooldown", "status"):
            self.assertIn(coluna, tabela)
        self.assertIn("🟢 TESTADA E FUNCIONANDO", tabela)  # kilo
        self.assertIn("🟡 GRATUITA CONFIRMADA, MAS NÃO TESTADA", tabela)

    def test_supports_models_vira_descoberta_no_corredor(self) -> None:
        corredores = {r.name: r for r in build_free_runners(env=SECRETS_DO_POOL)}
        self.assertEqual(len(corredores), len(FREE_PROVIDERS), "toda ficha com chave entra na corrida")
        for spec in FREE_PROVIDERS:
            corredor = corredores[spec.nome]
            if spec.supports_models:
                self.assertTrue(corredor.models_url.endswith("/models"), spec.nome)
                self.assertTrue(corredor.auto_discover, spec.nome)
            else:
                self.assertEqual(corredor.models_url, "", spec.nome)
                self.assertFalse(corredor.auto_discover, spec.nome)

    def test_cooldown_da_ficha_chega_no_corredor(self) -> None:
        corredor = build_free_runners(env={})[0]
        self.assertEqual(corredor.cooldown, FREE_PROVIDERS[0].cooldown)


class TestRespostaVaziaPorTeto(unittest.TestCase):
    """Modelo grátis de raciocínio gasta o teto e devolve vazio: repetir com mais espaço."""

    def test_vazio_por_teto_repete_o_mesmo_modelo_com_mais_tokens(self) -> None:
        pedidos: list[int] = []

        def fake_session() -> Any:
            return None

        provider = OpenAICompatibleHttpProvider(
            name="corredor-raciocinio",
            endpoint_url="https://exemplo.invalido/v1/chat/completions",
            models=["modelo-que-pensa"],
            session_factory=fake_session,
        )

        async def fake_post(session, payload, headers, timeout, model):  # noqa: ANN001
            pedidos.append(int(payload["max_tokens"]))
            if len(pedidos) == 1:
                raise ProviderError(
                    provider=provider.name,
                    message=f"{provider.name}: resposta vazia ({model} — teto de tokens)",
                    model=model,
                    empty_response=True,
                    truncated=True,
                )
            return LLMResponse(content="agora respondeu")

        provider._post = fake_post  # type: ignore[assignment]
        resposta = asyncio.run(provider.chat(messages=[{"role": "user", "content": "oi"}], timeout=5, max_tokens=100))

        self.assertEqual(resposta.content, "agora respondeu")
        self.assertEqual(len(pedidos), 2, "tinha que repetir uma única vez")
        self.assertGreater(pedidos[1], pedidos[0], "a repetição precisa de mais espaço")
        self.assertGreaterEqual(pedidos[1], 1024, "mínimo generoso para raciocínio")

    def test_vazio_seco_repete_uma_vez_depois_troca_de_modelo(self) -> None:
        """Roteador grátis às vezes devolve nada: repetir o modelo e, se insistir, trocar."""
        vistos: list[str] = []

        def fake_session() -> Any:
            return None

        provider = OpenAICompatibleHttpProvider(
            name="corredor-roteador",
            endpoint_url="https://exemplo.invalido/v1/chat/completions",
            models=["modelo-a", "modelo-b"],
            session_factory=fake_session,
        )

        async def fake_post(session, payload, headers, timeout, model):  # noqa: ANN001
            vistos.append(model)
            raise ProviderError(
                provider=provider.name,
                message=f"{provider.name}: resposta vazia ({model})",
                model=model,
                empty_response=True,
                truncated=False,
            )

        provider._post = fake_post  # type: ignore[assignment]
        with self.assertRaises(ProviderError) as ctx:
            asyncio.run(provider.chat(messages=[{"role": "user", "content": "oi"}], timeout=5, max_tokens=100))

        self.assertTrue(ctx.exception.is_transient, "vazio tem que contar como falha passageira")
        self.assertEqual(vistos, ["modelo-a", "modelo-b"],
                         "vazio passa a vez na hora: repetir o mesmo modelo só soma latência")

    def test_vazio_seco_troca_para_o_proximo_modelo(self) -> None:
        """O modelo que devolve vazio sai da frente: o próximo da lista responde."""
        tentativas = {"n": 0}

        def fake_session() -> Any:
            return None

        provider = OpenAICompatibleHttpProvider(
            name="corredor-roteador",
            endpoint_url="https://exemplo.invalido/v1/chat/completions",
            models=["modelo-a", "modelo-b"],
            session_factory=fake_session,
        )

        async def fake_post(session, payload, headers, timeout, model):  # noqa: ANN001
            tentativas["n"] += 1
            if model == "modelo-a":
                raise ProviderError(
                    provider=provider.name,
                    message=f"{provider.name}: resposta vazia ({model})",
                    model=model,
                    empty_response=True,
                    truncated=False,
                )
            return LLMResponse(content="achei o caminho")

        provider._post = fake_post  # type: ignore[assignment]
        resposta = asyncio.run(provider.chat(messages=[{"role": "user", "content": "oi"}], timeout=5, max_tokens=100))
        self.assertEqual(resposta.content, "achei o caminho")
        self.assertEqual(tentativas["n"], 2)


class TestModelosConferidosAoVivo(unittest.TestCase):
    """A lista do kilo sai do catálogo publicado pelo CI, não de listinha de terceiro."""

    RELATORIO = Path(__file__).resolve().parents[1] / "reports" / "kilo-modelos-free.md"
    RELATORIO_LATENCIA = Path(__file__).resolve().parents[1] / "reports" / "kilo-latencia-modelos.md"
    HISTORICO_LATENCIA = Path(__file__).resolve().parents[1] / "reports" / "kilo-latencia-historico.json"

    def test_ficha_do_kilo_confere_com_o_catalogo_publicado(self) -> None:
        if not self.RELATORIO.exists():
            self.skipTest("reports/kilo-modelos-free.md ainda não foi publicado pelo CI")
        catalogo = self.RELATORIO.read_text(encoding="utf-8")
        livres = set()
        for linha in catalogo.splitlines():
            if "| sim |" not in linha:
                continue
            for pedaco in linha.split("`")[1::2]:
                livres.add(pedaco.strip())

        ficha = next(spec for spec in FREE_PROVIDERS if spec.nome == "kilo")
        presentes = [m for m in ficha.modelos if m in livres]
        self.assertGreaterEqual(
            len(presentes), 3,
            "o catálogo do Kilo mudou: atualize a ficha com o que reports/kilo-modelos-free.md traz",
        )

    def _resumo_do_historico(self) -> dict[str, dict[str, Any]]:
        """Mediana e taxa de conteúdo por modelo somando as rodadas medidas pelo smoke."""
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from smoke_llm import resumo_latencia  # noqa: PLC0415

        return resumo_latencia(json.loads(self.HISTORICO_LATENCIA.read_text(encoding="utf-8")))

    def test_ordem_do_kilo_comeca_pelo_modelo_mais_rapido(self) -> None:
        """Ordem da fila tem que sair do histórico medido — nunca de uma rodada solta.

        A rede oscila: um modelo que respondeu em 0,66 s volta "200 vazio" na rodada seguinte. Se
        o teste olhasse só a última medição, a CI quebraria por acaso (foi o que aconteceu em
        18/09). Aqui a comparação é com a mediana acumulada, e a tolerância é "entre os 3 mais
        rápidos" justamente porque os tempos vizinhos empatam dentro do ruído.
        """
        ficha = next(spec for spec in FREE_PROVIDERS if spec.nome == "kilo")
        self.assertEqual(ficha.modelos[-1], "kilo-auto/free",
                         "o roteador (que às vezes devolve vazio) vai por último")

        if not self.HISTORICO_LATENCIA.exists():
            self.skipTest("sem histórico de medição: só os invariantes estruturais valem")
        resumo = self._resumo_do_historico()
        # o roteador `kilo-auto` tem regra própria (sempre o último), então não entra na
        # comparação de grupos: ele responde de vez em quando, mas não é modelo de trabalho.
        conhecidos = [m for m in ficha.modelos if m in resumo and m != "kilo-auto/free"]
        com_conteudo = [m for m in conhecidos if resumo[m]["com_conteudo"] > 0]
        if len(com_conteudo) < 3:
            self.skipTest(f"histórico curto: só {len(com_conteudo)} modelo(s) com conteúdo medido")

        # 1) o primeiro da fila tem que ser confiável (respondeu com conteúdo em pelo menos
        #    metade das rodadas) e rápido na mediana.
        primeiro = ficha.modelos[0]
        info = resumo.get(primeiro)
        self.assertIsNotNone(info, f"o primeiro da fila ({primeiro}) nunca foi medido pelo smoke")
        self.assertGreaterEqual(
            info["taxa_conteudo"], 0.5,
            f"o primeiro da fila devolveu conteúdo em só {info['taxa_conteudo'] * 100:.0f}% das rodadas",
        )
        self.assertLess(info["ms"], 5000, f"o primeiro da fila tem mediana de {info['ms'] / 1000:.2f}s")

        # 2) e estar entre os 3 melhores do ranking medido: mais rodadas com conteúdo primeiro,
        #    mediana como desempate (só mediana deixaria um modelo que acertou 1 de 4 na frente)
        fila = sorted(com_conteudo, key=lambda m: (-resumo[m]["taxa_conteudo"], resumo[m]["ms"]))
        self.assertIn(primeiro, fila[:3],
                      f"o primeiro da fila devia estar entre os 3 melhores do ranking: {fila[:3]}")

        # 3) a fila inteira tem que respeitar o ranking medido: taxa de conteúdo não-decrescente
        #    ao longo dela. Assim um modelo confiável nunca fica atrás de um que quase nunca
        #    responde — e se a medição virar, a CI mostra em vez de o dono descobrir no Discord.
        taxa = {m: resumo[m]["taxa_conteudo"] for m in conhecidos}
        sugerida = sorted(conhecidos, key=lambda m: (-taxa[m], resumo[m]["ms"]))
        taxas = [taxa[m] for m in conhecidos]
        self.assertEqual(
            taxas, sorted(taxas, reverse=True),
            "fila fora de ordem pelo ranking medido. Ordem sugerida pela medição: "
            + " → ".join(f"{m} ({taxa[m] * 100:.0f}%)" for m in sugerida))

        # 4) nenhum modelo que NUNCA devolveu conteúdo pode vir antes de um que devolveu:
        #    seria gastar a primeira tentativa (e o tempo do usuário) em quem não responde.
        zeros = {m for m in conhecidos if resumo[m]["com_conteudo"] == 0}
        achou_zero = False
        for modelo in ficha.modelos:
            if modelo in zeros:
                achou_zero = True
            elif modelo in com_conteudo and achou_zero:
                self.fail(f"{modelo} já devolveu conteúdo, mas está atrás de modelo que nunca devolveu")


class TestHistoricoDeLatencia(unittest.TestCase):
    """O agregado que decide a fila do `kilo` — testado sem rede, com histórico montado à mão."""

    @staticmethod
    def _historico():
        return {"rodadas": [
            {"em": "2026-09-18T01:40:02Z", "modelos": {
                "a:free": {"resultado": "200", "ms_mediana": 2000, "amostras": [["200", 2000]]},
                "b:free": {"resultado": "200 vazio", "ms_mediana": 600, "amostras": [["200 vazio", 600]]},
                "c:free": {"resultado": "HTTP 429", "ms_mediana": 400, "amostras": [["HTTP 429", 400]]},
            }},
            {"em": "2026-09-18T02:53:24Z", "modelos": {
                "a:free": {"resultado": "200", "ms_mediana": 4000, "amostras": [["200", 4000]]},
                "b:free": {"resultado": "200", "ms_mediana": 800, "amostras": [["200", 800]]},
                "c:free": {"resultado": "200 vazio", "ms_mediana": 500, "amostras": [["200 vazio", 500]]},
            }},
        ]}

    def test_mediana_conta_so_quem_respondeu_com_conteudo(self) -> None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from smoke_llm import resumo_latencia  # noqa: PLC0415

        resumo = resumo_latencia(self._historico())
        # 2000 e 4000 com conteúdo → mediana fica com a amostra mais lenta (pessimismo)
        self.assertEqual(resumo["a:free"]["ms"], 4000)
        self.assertEqual(resumo["a:free"]["taxa_conteudo"], 1.0)
        # 600 vazio + 800 com conteúdo → 50%, mediana só da que teve conteúdo
        self.assertEqual(resumo["b:free"]["ms"], 800)
        self.assertEqual(resumo["b:free"]["taxa_conteudo"], 0.5)
        # nunca respondeu com conteúdo: sem mediana e taxa zero
        self.assertIsNone(resumo["c:free"]["ms"])
        self.assertEqual(resumo["c:free"]["taxa_conteudo"], 0.0)

    def test_relatorio_separa_agregado_da_ultima_rodada(self) -> None:
        import os
        import tempfile

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from smoke_llm import escrever_relatorio_latencia  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(Path(tmp) / "reports", exist_ok=True)
            anterior = os.getcwd()
            os.chdir(tmp)
            try:
                historico = self._historico()
                ultima = [(m, i["resultado"], float(i["ms_mediana"]))
                          for m, i in historico["rodadas"][-1]["modelos"].items()]
                escrever_relatorio_latencia(historico, ultima)
                texto = (Path(tmp) / "reports" / "kilo-latencia-modelos.md").read_text(encoding="utf-8")
            finally:
                os.chdir(anterior)

        self.assertIn("Agregado", texto)
        self.assertIn("rodadas no histórico: 2", texto)
        self.assertIn("`b:free` | 50% (1/2)", texto)
        # quem nunca devolveu conteúdo aparece sem mediana, e não inventa número
        self.assertIn("`c:free` | 0% (0/2) | - |", texto)

    def test_varios_modelos_sem_conteudo_nao_quebram_o_relatorio(self) -> None:
        """Regressão da rodada de 18/09: comparar None com float derrubava a sonda inteira.

        Naquela rodada a maioria dos modelos devolveu 429/vazio, e a ordenação do agregado
        (que precisa mandar os sem-mediana para o fim) estourava TypeError — o relatório de
        latência não era escrito e o passo da sonda saía vermelho sem motivo.
        """
        import os
        import tempfile

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from smoke_llm import escrever_relatorio_latencia  # noqa: PLC0415

        historico = {"rodadas": [{"em": "2026-09-18T03:16:31Z", "modelos": {
            "bom:free": {"resultado": "200", "ms_mediana": 900, "amostras": [["200", 900]]},
            "vazio1:free": {"resultado": "200 vazio", "ms_mediana": 400, "amostras": [["200 vazio", 400]]},
            "vazio2:free": {"resultado": "HTTP 429", "ms_mediana": 500, "amostras": [["HTTP 429", 500]]},
            "vazio3:free": {"resultado": "200 vazio", "ms_mediana": 600, "amostras": [["200 vazio", 600]]},
        }}]}
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(Path(tmp) / "reports", exist_ok=True)
            anterior = os.getcwd()
            os.chdir(tmp)
            try:
                escrever_relatorio_latencia(
                    historico, [("bom:free", "200", 900.0), ("vazio1:free", "200 vazio", 400.0)])
                texto = (Path(tmp) / "reports" / "kilo-latencia-modelos.md").read_text(encoding="utf-8")
            finally:
                os.chdir(anterior)

        linhas = [ln for ln in texto.splitlines() if ln.startswith("| `")]
        self.assertTrue(linhas[0].startswith("| `bom:free`"), f"o que respondeu tem que vir primeiro: {linhas[0]}")
        self.assertIn("- |", linhas[1], f"quem não tem mediana aparece sem número: {linhas[1]}")

    def test_historico_guarda_no_maximo_30_rodadas(self) -> None:
        import os
        import tempfile

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from smoke_llm import _registrar_latencia  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(Path(tmp) / "reports", exist_ok=True)
            anterior = os.getcwd()
            os.chdir(tmp)
            try:
                for indice in range(35):
                    _registrar_latencia([("a:free", "200", 1000.0 + indice)],
                                        {"a:free": [("200", 1000.0 + indice)]})
                dados = json.loads((Path(tmp) / "reports" / "kilo-latencia-historico.json")
                                   .read_text(encoding="utf-8"))["rodadas"]
            finally:
                os.chdir(anterior)

        self.assertEqual(len(dados), 30)
        self.assertEqual(dados[-1]["modelos"]["a:free"]["ms_mediana"], 1034)


class TestFreePool(unittest.TestCase):
    """O pool só é o que a documentação confirma: nada de provedor morto na lista."""

    def test_provedores_removidos_nao_existem_mais_no_pool(self) -> None:
        """llm7, OVH e Pollinations saíram de vez: nem classe, nem ficha, nem corredor."""
        nomes = {spec.nome for spec in FREE_PROVIDERS}
        for morto in ("llm7", "ovh", "pollinations"):
            self.assertNotIn(morto, nomes)

        import llm.free_providers as mod

        for antigo in ("LLM7Provider", "OVHProvider", "PollinationsProvider"):
            self.assertFalse(hasattr(mod, antigo), f"{antigo} devia ter sido removido do código")

    def test_sem_chave_so_entra_o_corredor_anonimo(self) -> None:
        runners = build_free_runners(env={})
        self.assertEqual([r.name for r in runners], ["kilo"], "só o Kilo é anônimo")
        self.assertEqual(runners[0].headers["Authorization"], "Bearer anonymous")
        self.assertTrue(runners[0].supports_tools)

    def test_chaves_gratuitas_acionam_corredores_automaticamente(self) -> None:
        runners = build_free_runners(env={
            "GROQ_API_KEY": " gsk_x ",
            "GEMINI_API_KEY": "gk",
            "MISTRAL_API_KEY": "mk",
            "ZAI_API_KEY": "zk",
        })
        self.assertEqual([r.name for r in runners], ["kilo", "gemini", "groq", "mistral", "zai"])
        por_nome = {r.name: r for r in runners}
        self.assertEqual(por_nome["groq"].headers["Authorization"], "Bearer gsk_x")
        self.assertEqual(por_nome["gemini"].models[0], "gemini-2.5-flash")
        self.assertIn("generativelanguage.googleapis.com", por_nome["gemini"].endpoint_url)

    def test_provedor_com_conta_id_monta_a_url_com_o_id(self) -> None:
        runners = build_free_runners(env={
            "CLOUDFLARE_API_TOKEN": "ct",
            "CLOUDFLARE_ACCOUNT_ID": "acc123",
        })
        cloudflare = next(r for r in runners if r.name == "cloudflare")
        self.assertEqual(
            cloudflare.endpoint_url,
            "https://api.cloudflare.com/client/v4/accounts/acc123/ai/v1/chat/completions",
        )

    def test_provedor_sem_credencial_fica_fora_e_aparece_no_relatorio(self) -> None:
        relatorio = {spec.nome: motivo for spec, motivo in relatorio_do_pool(env={})}
        self.assertIn("groq", relatorio)
        self.assertIn("GROQ_API_KEY", relatorio["groq"])
        self.assertEqual(relatorio["kilo"], "", "o anônimo está sempre pronto")

        ativos, faltando = descrever_pool(env={})
        self.assertEqual(ativos, "kilo")
        self.assertTrue(any("GEMINI_API_KEY" in item for item in faltando))

    def test_pool_inteiro_com_todas_as_chaves(self) -> None:
        env = {
            "GROQ_API_KEY": "a",
            "GEMINI_API_KEY": "b",
            "MISTRAL_API_KEY": "c",
            "NVIDIA_API_KEY": "d",
            "ZAI_API_KEY": "e",
            "CLOUDFLARE_API_TOKEN": "f",
            "CLOUDFLARE_ACCOUNT_ID": "g",
            "OLLAMA_API_KEY": "h",
            "OPENROUTER_API_KEY": "i",
            "MODELSCOPE_API_KEY": "j",
            "SILICONFLOW_API_KEY": "k",
            "COHERE_API_KEY": "l",
        }
        nomes = [r.name for r in build_free_runners(env=env)]
        self.assertEqual(len(nomes), len(FREE_PROVIDERS))
        self.assertEqual(nomes[0], "kilo")

    def test_gateway_kilo_funciona_sem_chave(self) -> None:
        provider = build_gateway_provider("kilo", api_key="", env={})
        self.assertEqual(provider.endpoint_url, "https://api.kilo.ai/api/gateway/chat/completions")
        self.assertEqual(provider.headers["Authorization"], "Bearer anonymous")


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
        provider = provider_de_teste(session)
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


class TestRaciocinioVazado(unittest.TestCase):
    """Modelos grátis às vezes mandam o rascunho interno no content — em inglês e enorme."""

    def _provider(self) -> OpenAICompatibleHttpProvider:
        return OpenAICompatibleHttpProvider(
            name="corredor-pensador",
            endpoint_url="https://exemplo.invalido/v1/chat/completions",
            models=["modelo-que-pensa"],
            session_factory=lambda: None,
        )

    def test_rascunho_e_cortado_e_resposta_final_fica(self) -> None:
        resposta = {
            "choices": [{"message": {
                "content": ("Here's a thinking process:\n\n1. **Analyze User Input:** "
                            "The user wants the server renamed.\n\nLet me think...\n\n"
                            "Final answer: Não posso mudar o nome do servidor agora."),
            }, "finish_reason": "stop"}]
        }
        provider = self._provider()
        provider._session = FakeSession([FakeResponse(payload=resposta)])

        resultado = asyncio.run(provider.chat(
            messages=[{"role": "user", "content": "mude o nome do server pra pretinho"}], timeout=5))

        self.assertEqual(resultado.content, "Não posso mudar o nome do servidor agora.")
        self.assertNotIn("thinking", resultado.content.lower())

    def test_so_rascunho_vira_resposta_vazia_transitoria(self) -> None:
        """Sem resposta de verdade, o corredor tem que sair da frente — não mandar o rascunho."""
        resposta = {"choices": [{"message": {
            "content": "Let me think about it. The user said oi and I need to figure out what to do.",
        }, "finish_reason": "stop"}]}
        provider = self._provider()
        provider._session = FakeSession([FakeResponse(payload=resposta)])

        with self.assertRaises(ProviderError) as ctx:
            asyncio.run(provider.chat(messages=[{"role": "user", "content": "oi"}], timeout=5))

        self.assertTrue(ctx.exception.is_empty_response)
        self.assertTrue(ctx.exception.is_transient, "vazio tem que permitir nova onda/outro modelo")

    def test_raciocinio_em_campo_separado_nao_entra_na_resposta(self) -> None:
        resposta = {"choices": [{"message": {
            "content": "Pronto, apaguei os 10 canais. 🗑️",
            "reasoning_content": "The user asked to delete channels. I should call the tool...",
        }, "finish_reason": "stop"}]}
        provider = self._provider()
        provider._session = FakeSession([FakeResponse(payload=resposta)])

        resultado = asyncio.run(provider.chat(messages=[{"role": "user", "content": "apague"}], timeout=5))

        self.assertEqual(resultado.content, "Pronto, apaguei os 10 canais. 🗑️")

class ProviderDeContexto(ChatProvider):
    """Recusa por TAMANHO na primeira chamada (como os modelos grátis fazem) e depois responde."""

    def __init__(self, name: str = "kilo", exige: int = 99) -> None:
        self.name = name
        self.exige = exige
        self.chamadas = 0
        self.mensagens_recebidas: list[int] = []

    async def chat(self, messages, tools=None, timeout=60.0, max_tokens=1024):
        self.chamadas += 1
        self.mensagens_recebidas.append(len(messages))
        if len(messages) > self.exige:
            raise ProviderError(
                self.name,
                f"{self.name}: HTTP 400 (m) — This model's maximum context length is 65536 "
                "tokens; however your messages resulted in too many tokens",
                status=400, model="m",
            )
        return LLMResponse(content="coube agora")


class TestErroDeContexto(unittest.TestCase):
    """
    "Não consegui falar com nenhum modelo" aparecia em tarefas específicas: quando o pedido não
    cabia no modelo, o erro era tratado como definitivo. Vale tentar de novo com o histórico
    cortado — e, se não couber de jeito nenhum, dizer o MOTIVO certo para o cliente.
    """

    def test_contexto_e_classificado_como_problema_de_tamanho(self) -> None:
        de_contexto = [
            ProviderError("kilo", "HTTP 400 — maximum context length is 65536 tokens", status=400),
            ProviderError("kilo", "HTTP 400 — prompt is too long", status=400),
            ProviderError("kilo", "HTTP 413 — payload too large", status=413),
            ProviderError("kilo", "HTTP 400 — the input is too long for this model", status=400),
        ]
        for erro in de_contexto:
            self.assertTrue(erro.is_context_problem, erro.raw_message)

        nao_de_contexto = [
            ProviderError("kilo", "HTTP 401 — Invalid API key", status=401),
            ProviderError("kilo", "HTTP 429 — rate limit exceeded", status=429),
            ProviderError("kilo", "HTTP 404 — model not found", status=404),
        ]
        for erro in nao_de_contexto:
            self.assertFalse(erro.is_context_problem, erro.raw_message)

    def test_corrida_repete_com_historico_cortado_e_vence(self) -> None:
        provider = ProviderDeContexto(exige=8)
        auto = corrida(provider, waves=2)
        historico = [{"role": "user", "content": f"mensagem {i}"} for i in range(30)]

        resposta = asyncio.run(auto.chat(messages=[{"role": "system", "content": "sistema"},
                                                   *historico]))

        self.assertEqual(resposta.content, "coube agora")
        self.assertEqual(provider.chamadas, 2, "tinha que repetir uma vez com menos contexto")
        self.assertGreater(provider.mensagens_recebidas[0], provider.mensagens_recebidas[1],
                           "a segunda tentativa tem que mandar MENOS mensagens")
        self.assertLessEqual(provider.mensagens_recebidas[1], 9)

    def test_contexto_insuportavel_avisa_o_motivo_certo(self) -> None:
        provider = ProviderDeContexto(exige=0)  # nunca cabe
        auto = corrida(provider, waves=1)

        with self.assertRaises(LLMUnavailableError) as ctx:
            asyncio.run(auto.chat(messages=[{"role": "system", "content": "s"},
                                            *[{"role": "user", "content": str(i)} for i in range(30)]]))

        erro = ctx.exception
        self.assertEqual(erro.motivo, "contexto")
        from core.bot import FarolBot
        mensagem = FarolBot._mensagem_de_erro(erro)
        self.assertIn("comprida demais", mensagem)
        self.assertIn("limpar conversa", mensagem)
        self.assertNotIn("HTTP", mensagem)

    def test_erro_comum_nao_vira_desculpa_de_contexto(self) -> None:
        auto = corrida(AlwaysFailingProvider("kilo", 401, "Invalid API key"), waves=1)
        with self.assertRaises(LLMUnavailableError) as ctx:
            asyncio.run(auto.chat(messages=[{"role": "user", "content": "oi"}]))
        self.assertEqual(ctx.exception.motivo, "")


class TestPoolDeUmCorredorSo(unittest.TestCase):
    """
    O CI tem UM corredor (kilo). Nele, "todo mundo de castigo" virava falha imediata — e as
    tarefas específicas (as que gastam mais de uma chamada e esbarram no limite de 200 req/h)
    eram justamente as que morriam com "não consegui falar com nenhum modelo".
    """

    def test_pool_de_castigo_espera_o_castigo_mais_curto(self) -> None:
        from llm.auto import BENCH_ON_RATE_LIMIT  # noqa: F401  (documenta de onde vem o castigo)

        # 429 na primeira chamada → castigo curto → o bot espera e tenta de novo com sucesso
        provider = FlakyProvider("kilo", content="respondi depois do castigo", falhas=1,
                                 status=429, retry_after=0.4)
        auto = corrida(provider, waves=2)
        auto.wave_delay = 0.01

        resposta = asyncio.run(auto.chat(messages=[{"role": "user", "content": "tarefa pesada"}]))
        self.assertEqual(resposta.content, "respondi depois do castigo")
        self.assertGreaterEqual(provider.chamadas, 2)

    def test_castigo_longo_nao_trava_o_turno(self) -> None:
        """Castigo de minutos não pode segurar o cliente: falha rápido com mensagem transitória."""
        provider = AlwaysFailingProvider("kilo", 429, "Queue full for IP", retry_after=600)
        auto = corrida(provider, waves=2)

        with self.assertRaises(LLMUnavailableError) as ctx:
            asyncio.run(auto.chat(messages=[{"role": "user", "content": "oi"}], timeout=5.0))
        self.assertTrue(ctx.exception.transient)

    def test_contexto_nao_castiga_o_corredor(self) -> None:
        """Erro de tamanho é do PEDIDO: castigar o corredor impediria a tentativa com menos contexto."""
        provider = ProviderDeContexto(exige=8)
        auto = corrida(provider, waves=2)
        asyncio.run(auto.chat(messages=[{"role": "system", "content": "s"},
                                        *[{"role": "user", "content": str(i)} for i in range(30)]]))
        self.assertEqual(auto.castigados(), [], "corredor castigado por erro de tamanho do pedido")

    def test_modelo_indisponivel_convida_a_tentar_de_novo(self) -> None:
        """Catálogo dos gratuitos muda sozinho: o cliente deve ler 'tente de novo', não beco sem saída."""
        auto = corrida(
            AlwaysFailingProvider("kilo", 400, "Model modelo-x is currently unavailable"),
            waves=1,
        )
        with self.assertRaises(LLMUnavailableError) as ctx:
            asyncio.run(auto.chat(messages=[{"role": "user", "content": "oi"}]))
        self.assertTrue(ctx.exception.transient)
        from core.bot import FarolBot
        self.assertIn("tente de novo", FarolBot._mensagem_de_erro(ctx.exception).lower())


class TestPodaDeMensagens(unittest.TestCase):
    def test_mantem_system_e_o_mais_recente(self) -> None:
        from llm.base import podar_mensagens

        msgs = [{"role": "system", "content": "s"},
                *[{"role": "user", "content": str(i)} for i in range(20)]]
        podado = podar_mensagens(msgs, manter=5)
        self.assertEqual(podado[0]["role"], "system")
        self.assertEqual(len(podado), 6)
        self.assertEqual(podado[-1]["content"], "19")

    def test_sem_historico_grande_nao_mexe(self) -> None:
        from llm.base import podar_mensagens

        msgs = [{"role": "user", "content": "oi"}]
        self.assertEqual(podar_mensagens(msgs), msgs)

    def test_resultado_de_ferramenta_orfa_e_descartado(self) -> None:
        """Provedor nenhum aceita `role=tool` sem a chamada que o pediu."""
        from llm.base import podar_mensagens

        msgs = [{"role": "user", "content": str(i)} for i in range(20)]
        msgs += [{"role": "tool", "content": "resultado"},
                 {"role": "assistant", "content": "ok"},
                 {"role": "user", "content": "e agora?"}]
        podado = podar_mensagens(msgs, manter=3)
        self.assertNotEqual(podado[0].get("role"), "tool")

