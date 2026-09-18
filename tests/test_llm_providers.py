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
        self.assertEqual(vistos, ["modelo-a", "modelo-a", "modelo-b", "modelo-b"],
                         "cada modelo ganha uma segunda chance antes de passar a vez")

    def test_vazio_seco_resolve_na_repeticao(self) -> None:
        tentativas = {"n": 0}

        def fake_session() -> Any:
            return None

        provider = OpenAICompatibleHttpProvider(
            name="corredor-roteador",
            endpoint_url="https://exemplo.invalido/v1/chat/completions",
            models=["modelo-a"],
            session_factory=fake_session,
        )

        async def fake_post(session, payload, headers, timeout, model):  # noqa: ANN001
            tentativas["n"] += 1
            if tentativas["n"] == 1:
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
