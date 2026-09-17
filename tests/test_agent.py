"""
Testes do loop do Agente Farol com provedor LLM fake.
Testa: resposta em texto puro, round-trip de ferramentas nativas,
fallback de ferramentas em markdown (```tool), tratamento de erros e limite de rodadas.
"""

from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from typing import Any

from brain.agent import Agent
from brain.memory import ChannelMemory
from brain.tools import ToolError
from llm.base import ChatProvider, LLMResponse, ToolCall


class FakeLLM(ChatProvider):
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.call_history: list[dict[str, Any]] = []

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        timeout: float = 60.0,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        self.call_history.append({"messages": messages, "tools": tools})
        if self.responses:
            return self.responses.pop(0)
        return LLMResponse(content="Resposta padrão fake.")


class TestAgent(unittest.TestCase):
    def setUp(self) -> None:
        self.actor_perms = SimpleNamespace(administrator=True, manage_channels=True, manage_roles=True)
        self.bot_perms = SimpleNamespace(administrator=True, manage_channels=True, manage_roles=True)
        self.actor = SimpleNamespace(id=1, guild_permissions=self.actor_perms)
        self.bot_member = SimpleNamespace(id=2, guild_permissions=self.bot_perms, top_role=SimpleNamespace(position=100))
        self.guild = SimpleNamespace(
            name="Servidor Teste",
            id=12345,
            channels=[],
            categories=[],
            roles=[],
            me=self.bot_member,
            owner_id=1,
        )
        self.channel = SimpleNamespace(id=555, name="geral")

    def test_pure_text_response(self) -> None:
        fake_llm = FakeLLM([
            LLMResponse(content="Olá! Posso ajudar a montar seu servidor.", tool_calls=[]),
        ])
        agent = Agent(llm_provider=fake_llm, memory=ChannelMemory())

        res = asyncio.run(
            agent.process_turn(
                guild=self.guild,
                channel=self.channel,
                actor=self.actor,
                prompt="Oi bot",
            )
        )
        self.assertEqual(res, "Olá! Posso ajudar a montar seu servidor.")

    def test_native_tool_roundtrip(self) -> None:
        created_channel = SimpleNamespace(id=777, name="anuncios")

        async def fake_create_text_channel(name, **kwargs):
            return created_channel

        self.guild.create_text_channel = fake_create_text_channel

        fake_llm = FakeLLM([
            # Rodada 1: modelo decide chamar create_channels
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_123",
                        name="create_channels",
                        args={"channels": [{"name": "anuncios", "type": "text"}]},
                    )
                ],
            ),
            # Rodada 2: após receber o retorno da ferramenta, modelo responde
            LLMResponse(content="Criei o canal <#777> para você!", tool_calls=[]),
        ])

        agent = Agent(llm_provider=fake_llm, memory=ChannelMemory())
        res = asyncio.run(
            agent.process_turn(
                guild=self.guild,
                channel=self.channel,
                actor=self.actor,
                prompt="cria o canal anuncios",
            )
        )
        self.assertIn("<#777>", res)
        self.assertEqual(len(fake_llm.call_history), 2)

    def test_fallback_tool_markdown(self) -> None:
        """
        Testa provedores gratuitos anônimos que respondem com bloco ```tool.
        """
        created_channel = SimpleNamespace(id=888, name="bate-papo")

        async def fake_create_text_channel(name, **kwargs):
            return created_channel

        self.guild.create_text_channel = fake_create_text_channel

        fallback_text = (
            "Vou criar o canal para você agora:\n"
            "```tool\n"
            '{"name": "create_channels", "args": {"channels": [{"name": "bate-papo", "type": "text"}]}}\n'
            "```"
        )

        fake_llm = FakeLLM([
            # Rodada 1: sem tool_calls nativas, apenas bloco markdown
            LLMResponse(content=fallback_text, tool_calls=[]),
            # Rodada 2: resposta final
            LLMResponse(content="Pronto! O canal <#888> foi criado.", tool_calls=[]),
        ])

        agent = Agent(llm_provider=fake_llm, memory=ChannelMemory())
        res = asyncio.run(
            agent.process_turn(
                guild=self.guild,
                channel=self.channel,
                actor=self.actor,
                prompt="cria bate-papo",
            )
        )
        self.assertIn("<#888>", res)
        self.assertEqual(len(fake_llm.call_history), 2)

    def test_tool_error_handled_gracefully(self) -> None:
        """
        Se a ferramenta levantar ToolError (ex: permissão ou confirmação),
        ela vira mensagem de erro para o modelo e não derruba o agente.
        """
        fake_llm = FakeLLM([
            # Modelo tenta apagar cargo sem confirmação
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_del",
                        name="delete_role",
                        args={"role": "VIP", "confirmed": False},
                    )
                ],
            ),
            # Modelo lê a mensagem de confirmação e pergunta ao usuário
            LLMResponse(
                content="Isso apagará o cargo VIP permanentemente. Posso confirmar?",
                tool_calls=[],
            ),
        ])

        role = SimpleNamespace(id=999, name="VIP", position=10, managed=False, is_default=lambda: False)
        self.guild.roles = [role]

        agent = Agent(llm_provider=fake_llm, memory=ChannelMemory())
        res = asyncio.run(
            agent.process_turn(
                guild=self.guild,
                channel=self.channel,
                actor=self.actor,
                prompt="apaga o cargo VIP",
            )
        )
        self.assertIn("Posso confirmar?", res)

    def test_max_rounds_triggers_final_summary(self) -> None:
        """
        Se o modelo atingir o limite max_tool_rounds chamando ferramentas,
        o agente interrompe o loop e solicita um resumo final.
        """
        responses = [
            # Rodada 1: tool call
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="c_0", name="color_palette", args={"query": "gamer"})],
            ),
            # Rodada 2: tool call
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="c_1", name="color_palette", args={"query": "gamer"})],
            ),
            # Chamada de resumo final solicitada pelo agente
            LLMResponse(content="Resumo final de todas as ações.", tool_calls=[]),
        ]

        fake_llm = FakeLLM(responses)
        agent = Agent(llm_provider=fake_llm, memory=ChannelMemory(), max_tool_rounds=2)

        res = asyncio.run(
            agent.process_turn(
                guild=self.guild,
                channel=self.channel,
                actor=self.actor,
                prompt="loop teste",
            )
        )
        self.assertEqual(res, "Resumo final de todas as ações.")
        # Verifica se o resumo final foi solicitado sem schema de tools
        self.assertIsNone(fake_llm.call_history[-1]["tools"])


if __name__ == "__main__":
    unittest.main()
