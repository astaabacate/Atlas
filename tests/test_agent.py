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

from brain.agent import Agent, asks_for_confirmation, user_confirmed
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


class TestConfirmacaoDestrutiva(unittest.TestCase):
    """
    O modelo NÃO pode se auto-confirmar: `confirmed=true` só vale quando a ferramenta já
    pediu confirmação e o usuário confirmou depois. Bug pego no teste ao vivo (o agente
    apagou 2 canais de uma vez sem perguntar nada).
    """

    def setUp(self) -> None:
        self.actor = SimpleNamespace(id=1, guild_permissions=SimpleNamespace(administrator=True))
        self.bot_member = SimpleNamespace(id=2, guild_permissions=SimpleNamespace(administrator=True),
                                          top_role=SimpleNamespace(position=100))
        self.apagados: list[str] = []

        def fazer_canal(cid: int, nome: str) -> SimpleNamespace:
            canal = SimpleNamespace(id=cid, name=nome, mentions=[])

            async def delete() -> None:
                self.apagados.append(nome)
                self.canais = [c for c in self.canais if c.id != cid]

            canal.delete = delete
            return canal

        self.canais = [fazer_canal(11, "canal-a"), fazer_canal(12, "canal-b")]
        self.guild = SimpleNamespace(
            name="Servidor Teste", id=12345, channels=self.canais, categories=[], roles=[],
            members=[], me=self.bot_member, owner_id=1,
            get_channel=lambda cid: next((c for c in self.canais if c.id == cid), None),
        )
        self.channel = SimpleNamespace(id=555, name="geral")

    def _agent_com(self, respostas: list[LLMResponse]) -> tuple[Agent, FakeLLM]:
        llm = FakeLLM(respostas)
        return Agent(llm_provider=llm, memory=ChannelMemory()), llm

    def _turno(self, agent: Agent, prompt: str) -> str:
        return asyncio.run(agent.process_turn(guild=self.guild, channel=self.channel,
                                              actor=self.actor, prompt=prompt))

    def test_modelo_nao_se_autoconfirma(self) -> None:
        agent, _ = self._agent_com([
            LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="delete_channels",
                                                         args={"channels": ["11", "12"], "confirmed": True})]),
            LLMResponse(content="Posso apagar os 2 canais? Confirme por favor.", tool_calls=[]),
        ])

        resposta = self._turno(agent, "Apague os canais canal-a e canal-b de uma vez.")

        self.assertEqual(self.apagados, [], "o agente apagou sem a confirmação do usuário")
        self.assertIn("confirm", resposta.lower())
        pendentes = agent.pending_confirmation(555)
        self.assertTrue("delete_channels" in pendentes or "*" in pendentes,
                        f"o pedido de confirmação não ficou registrado: {pendentes}")

        agent2, _ = self._agent_com([
            LLMResponse(content="", tool_calls=[ToolCall(id="c2", name="delete_channels",
                                                         args={"channels": ["11", "12"], "confirmed": True})]),
            LLMResponse(content="Feito, canais apagados.", tool_calls=[]),
        ])
        agent2._aguardando_confirmacao[555] = {"delete_channels"}
        agent2.memory = agent.memory  # mantém o histórico da conversa
        self._turno(agent2, "sim, pode apagar")

        self.assertEqual(sorted(self.apagados), ["canal-a", "canal-b"], "não apagou depois do 'sim'")

    def test_sim_sem_pendencia_nao_libera(self) -> None:
        agent, _ = self._agent_com([
            LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="delete_channels",
                                                         args={"channels": ["11", "12"], "confirmed": True})]),
            LLMResponse(content="Erro ao apagar.", tool_calls=[]),
        ])

        self._turno(agent, "sim")

        self.assertEqual(self.apagados, [], "bastou dizer 'sim' sem o bot ter perguntado nada")

    def test_confirmacao_no_texto_libera_o_sim(self) -> None:
        agent, _ = self._agent_com([
            LLMResponse(content="Tem certeza que quer apagar os 2 canais?", tool_calls=[]),
        ])
        self._turno(agent, "Apague os canais canal-a e canal-b")
        self.assertIn("*", agent.pending_confirmation(555))

        agent2, _ = self._agent_com([
            LLMResponse(content="", tool_calls=[ToolCall(id="c2", name="delete_channels",
                                                         args={"channels": ["11", "12"], "confirmed": True})]),
            LLMResponse(content="Pronto!", tool_calls=[]),
        ])
        agent2._aguardando_confirmacao[555] = agent.pending_confirmation(555)
        self._turno(agent2, "isso, manda ver")

        self.assertEqual(sorted(self.apagados), ["canal-a", "canal-b"])

    def test_canal_unico_nominal_continua_apagando_direto(self) -> None:
        agent, _ = self._agent_com([
            LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="delete_channels",
                                                         args={"channels": ["11"], "confirmed": True})]),
            LLMResponse(content="Canal apagado.", tool_calls=[]),
        ])

        self._turno(agent, "Apague o canal canal-a")

        self.assertEqual(self.apagados, ["canal-a"], "canal único nominal deveria apagar sem travar")

    def test_pergunta_aparece_mesmo_com_resumo_pessimo_do_modelo(self) -> None:
        """
        Modelo fraco (provedor gratuito) insiste no confirmed=true e depois resume "falhou":
        a pergunta de confirmação precisa chegar ao usuário de qualquer jeito.
        """
        teimoso = LLMResponse(content="", tool_calls=[ToolCall(
            id="c1", name="delete_channels", args={"channels": ["11", "12"], "confirmed": True})])
        agent, _ = self._agent_com([
            teimoso, teimoso,
            LLMResponse(content="**Resumo:** 1. Tentei excluir os canais. 2. A tentativa falhou.", tool_calls=[]),
        ])
        agent.max_tool_rounds = 2

        resposta = self._turno(agent, "Apague os canais canal-a e canal-b de uma vez.")

        self.assertEqual(self.apagados, [], "apagou sem confirmação do usuário")
        self.assertIn("confirma", resposta.lower(),
                      f"o usuário ficou sem a pergunta de confirmação: {resposta!r}")

    def test_pergunta_aparece_no_caminho_de_resumo(self) -> None:
        teimoso = LLMResponse(content="", tool_calls=[ToolCall(
            id="c1", name="delete_channels", args={"channels": ["11", "12"], "confirmed": True})])
        agent, _ = self._agent_com([teimoso, teimoso, LLMResponse(content="", tool_calls=[])])
        agent.max_tool_rounds = 2

        resposta = self._turno(agent, "Apague os canais canal-a e canal-b")

        self.assertEqual(self.apagados, [])
        self.assertIn("sim, pode apagar", resposta.lower())

    def test_helpers_de_confirmacao(self) -> None:
        self.assertTrue(user_confirmed("sim, pode apagar"))
        self.assertTrue(user_confirmed("Confirmo!"))
        self.assertTrue(user_confirmed("isso mesmo"))
        self.assertFalse(user_confirmed("apague os canais 1 e 2"))
        self.assertFalse(user_confirmed("não, deixa quieto"))
        self.assertTrue(asks_for_confirmation("Posso apagar esses 2 canais?"))
        self.assertTrue(asks_for_confirmation("Tem certeza disso?"))
        self.assertFalse(asks_for_confirmation("Canais excluídos com sucesso!"))


if __name__ == "__main__":
    unittest.main()
