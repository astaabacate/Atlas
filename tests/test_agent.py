"""
Testes do loop do Agente Farol com provedor LLM fake.
Testa: resposta em texto puro, round-trip de ferramentas nativas,
fallback de ferramentas em markdown (```tool), tratamento de erros e limite de rodadas.
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from typing import Any

from brain.agent import Agent, asks_for_confirmation, user_confirmed
from brain.memory import ChannelMemory, memory_key
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
        # mesma chave do agente: (servidor, canal)
        self.chave_conversa = memory_key(self.guild.id, self.channel.id)

    def _agent_com(self, respostas: list[LLMResponse], cauteloso: bool = True) -> tuple[Agent, FakeLLM]:
        """Estes testes exercitam o MODO CAUTELOSO (o padrão do bot é o direto)."""
        llm = FakeLLM(respostas)
        return Agent(llm_provider=llm, memory=ChannelMemory(), confirm_destructive=cauteloso), llm

    def _turno(self, agent: Agent, prompt: str) -> str:
        return asyncio.run(agent.process_turn(guild=self.guild, channel=self.channel,
                                              actor=self.actor, prompt=prompt))

    def test_modo_direto_executa_o_pedido_sem_perguntar(self) -> None:
        """Padrão: 'apague os canais X e Y' → apaga e responde o que fez, sem 'confirma?'."""
        agent, _ = self._agent_com([
            LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="delete_channels",
                                                         args={"channels": ["11", "12"], "confirmed": True})]),
            LLMResponse(content="Apaguei canal-a e canal-b. 🗑️", tool_calls=[]),
        ], cauteloso=False)

        resposta = self._turno(agent, "Apague os canais canal-a e canal-b de uma vez.")

        self.assertEqual(sorted(self.apagados), ["canal-a", "canal-b"], "modo direto apaga na hora")
        self.assertNotIn("confirm", resposta.lower(), "não pode pedir confirmação no modo direto")

    def test_ferramenta_terminal_responde_sem_segunda_chamada_ao_llm(self) -> None:
        """Excluir canal: a resposta pronta da ferramenta vale — sem gastar outra ida ao LLM."""
        agent, llm = self._agent_com([
            LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="delete_channels",
                                                         args={"channels": ["11"]})]),
        ], cauteloso=False)

        resposta = self._turno(agent, "Apague o canal canal-a")

        self.assertEqual(len(llm.call_history), 1, "chamou o LLM de novo só para resumir o que já sabia")
        self.assertIn("Exclusão concluída", resposta)
        self.assertEqual(self.apagados, ["canal-a"])

    def test_pedido_extra_na_mesma_frase_nao_usa_o_atalho(self) -> None:
        """'apague esse chat e mande oi': o 'oi' faz parte do pedido — o modelo tem que responder."""
        agent, llm = self._agent_com([
            LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="conversation_clear", args={})]),
            LLMResponse(content="oi 👋", tool_calls=[]),
        ], cauteloso=False)

        resposta = self._turno(agent, "blz agr exclua esse chat aqui todo e mande oi")

        self.assertEqual(len(llm.call_history), 2, "o atalho engoliu o 'mande oi'")
        self.assertEqual(resposta, "oi 👋")

    def test_ferramenta_nao_terminal_ainda_pede_o_resumo(self) -> None:
        """Criar canal NÃO é terminal: o modelo precisa continuar a conversa."""
        agent, llm = self._agent_com([
            LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="list_roles", args={})]),
            LLMResponse(content="Você tem 3 cargos.", tool_calls=[]),
        ], cauteloso=False)

        resposta = self._turno(agent, "Quais cargos existem?")

        self.assertEqual(len(llm.call_history), 2)
        self.assertIn("3 cargos", resposta)

    def test_modelo_nao_se_autoconfirma(self) -> None:
        agent, _ = self._agent_com([
            LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="delete_channels",
                                                         args={"channels": ["11", "12"], "confirmed": True})]),
            LLMResponse(content="Posso apagar os 2 canais? Confirme por favor.", tool_calls=[]),
        ])

        resposta = self._turno(agent, "Apague os canais canal-a e canal-b de uma vez.")

        self.assertEqual(self.apagados, [], "o agente apagou sem a confirmação do usuário")
        self.assertIn("confirm", resposta.lower())
        pendentes = agent.pending_confirmation(self.chave_conversa)
        self.assertTrue("delete_channels" in pendentes or "*" in pendentes,
                        f"o pedido de confirmação não ficou registrado: {pendentes}")

        agent2, _ = self._agent_com([
            LLMResponse(content="", tool_calls=[ToolCall(id="c2", name="delete_channels",
                                                         args={"channels": ["11", "12"], "confirmed": True})]),
            LLMResponse(content="Feito, canais apagados.", tool_calls=[]),
        ])
        agent2._aguardando_confirmacao[self.chave_conversa] = {"delete_channels"}
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
        self.assertIn("*", agent.pending_confirmation(self.chave_conversa))

        agent2, _ = self._agent_com([
            LLMResponse(content="", tool_calls=[ToolCall(id="c2", name="delete_channels",
                                                         args={"channels": ["11", "12"], "confirmed": True})]),
            LLMResponse(content="Pronto!", tool_calls=[]),
        ])
        agent2._aguardando_confirmacao[self.chave_conversa] = agent.pending_confirmation(self.chave_conversa)
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

    def test_resumo_final_falha_mas_trabalho_feito_nao_vira_erro(self) -> None:
        """Corrida de LLM morre no resumo final: o cliente vê o que foi feito, não um erro."""
        from llm.auto import LLMUnavailableError

        canal = SimpleNamespace(id=999, name="resumo")

        async def fake_create_text_channel(name, **kwargs):
            return canal

        self.guild.create_text_channel = fake_create_text_channel

        class LLMQueMorreNoResumo(FakeLLM):
            async def chat(self, messages, tools=None, timeout=60.0, max_tokens=1024):
                if self.call_history and len(self.call_history) >= 1:
                    self.call_history.append({"messages": messages, "tools": tools})
                    raise LLMUnavailableError("Nenhum dos 2 provedores de LLM respondeu (kilo/tools, groq)",
                                              transient=True)
                return await super().chat(messages, tools, timeout, max_tokens)

        llm = LLMQueMorreNoResumo([
            LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="create_channels",
                                                         args={"channels": [{"name": "resumo"}]})]),
        ])
        agent = Agent(llm_provider=llm, memory=ChannelMemory())
        agent.max_tool_rounds = 1

        resposta = self._turno(agent, "cria o canal resumo")

        # o resultado REAL da ferramenta (em português) é melhor que uma desculpa genérica
        self.assertIn("Criei 1 canal", resposta)
        self.assertNotIn("Nenhum dos", resposta)
        self.assertNotIn("Não consegui falar com nenhum modelo", resposta)

    def test_llm_cai_no_meio_do_laco_e_o_trabalho_feito_nao_vira_erro(self) -> None:
        """Ferramenta executada + LLM morrendo na rodada seguinte = resposta com o que foi feito."""
        from llm.auto import LLMUnavailableError

        canal = SimpleNamespace(id=888, name="meio-do-laco")

        async def fake_create_text_channel(name, **kwargs):
            return canal

        self.guild.create_text_channel = fake_create_text_channel

        class LLMQueMorreNaSegundaRodada(FakeLLM):
            async def chat(self, messages, tools=None, timeout=60.0, max_tokens=1024):
                self.call_history.append({"messages": messages, "tools": tools})
                if len(self.call_history) >= 2:
                    raise LLMUnavailableError("Nenhum dos 1 provedores de LLM respondeu (kilo)")
                return LLMResponse(content="", tool_calls=[
                    ToolCall(id="c1", name="create_channels", args={"channels": [{"name": "x"}]}),
                    ToolCall(id="c2", name="edit_channel",
                             args={"channel": "x", "topic": "novo tópico"}),
                ])

        llm = LLMQueMorreNaSegundaRodada([])
        agent = Agent(llm_provider=llm, memory=ChannelMemory())
        agent.max_tool_rounds = 3

        resposta = self._turno(agent, "cria o canal x e põe um tópico")

        self.assertNotIn("Não consegui falar com nenhum modelo", resposta)
        self.assertNotIn("Nenhum dos", resposta)
        self.assertTrue(resposta.strip(), "tem que responder algo em PT-BR")
        self.assertTrue("Criei" in resposta or "atualizado" in resposta or "Fiz o que você pediu" in resposta,
                        f"resposta inesperada: {resposta!r}")

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


class TestEcoDeContexto(unittest.TestCase):
    """
    O caso que o dono do servidor viu: falou "oi" e recebeu de volta o PLANEJAMENTO em inglês,
    começando por "[Ação solicitada: edit_channel(...)]" — o modelo regurgitou o contexto que
    o bot mandou (histórico + protocolo de ferramentas).
    """

    def test_eco_do_plumbing_e_barrado(self) -> None:
        from brain.agent import Agent

        textao = (
            "[Ação solicitada: edit_channel({\"name\": \"dicas-freefire\"})]\n"
            "Let's start by editing categories: we need to identify category IDs.\n"
            "Then edit channels within. First COMUNIDADE, then JOGOS & VOZ."
        )
        self.assertIsNotNone(Agent.resposta_ruim(textao))

    def test_bloco_de_protocolo_na_resposta_e_barrado(self) -> None:
        from brain.agent import Agent

        self.assertIsNotNone(Agent.resposta_ruim('```tool\n{"name": "edit_channel"}\n```'))
        self.assertIsNotNone(Agent.resposta_ruim("Ferramentas disponíveis: - create_roles(...)"))

    def test_resposta_normal_continua_passando(self) -> None:
        from brain.agent import Agent

        for boa in ("Feito! ✅ Canal renomeado para dicas-freefire.",
                    "Pronto, criei a categoria 🎮 FREE FIRE com 3 canais.",
                    "Não encontrei esse canal no servidor."):
            self.assertIsNone(Agent.resposta_ruim(boa), boa)

    def test_resultado_de_ferramenta_com_json_nao_e_eco(self) -> None:
        """`export_structure` devolve JSON em ```json — isso é resposta legítima, não eco."""
        from brain.agent import Agent

        saida = '📦 Estrutura exportada\n```json\n{"roles": [], "categories": []}\n```'
        self.assertIsNone(Agent.resposta_ruim(saida))


class TestRespostaNuncaVazaRaciocinio(unittest.TestCase):
    """O dono recebeu um textão em inglês (rascunho do modelo). Nunca mais."""

    def setUp(self) -> None:
        self.actor = SimpleNamespace(id=1, guild_permissions=SimpleNamespace(administrator=True))
        self.bot_member = SimpleNamespace(id=2, guild_permissions=SimpleNamespace(administrator=True),
                                          top_role=SimpleNamespace(position=100))
        self.canais = []
        self.guild = SimpleNamespace(
            name="Servidor Teste", id=12345, channels=self.canais, categories=[], roles=[],
            members=[], me=self.bot_member, owner_id=1, get_channel=lambda cid: None,
        )
        self.channel = SimpleNamespace(id=555, name="geral")

    def _turno(self, agent: Agent, prompt: str) -> str:
        return asyncio.run(agent.process_turn(guild=self.guild, channel=self.channel,
                                              actor=self.actor, prompt=prompt))

    TEXTao_EN = (
        "- User: oi  ← This is the last user message before my current turn\n"
        "But in the current turn showing in the assistant's view, it says: 'mude o nome do server'.\n"
        "There's inconsistency here. Looking at the very end of the user's message history: the "
        "user said oi. I should figure out what the user wants and then answer properly. Let me "
        "think about whether the name change already happened and what the correct answer is."
    )

    def test_textao_em_ingles_e_reescrito_em_portugues(self) -> None:
        llm = FakeLLM([
            LLMResponse(content=self.TEXTao_EN, tool_calls=[]),
            LLMResponse(content="Não posso mudar o nome do servidor agora.", tool_calls=[]),
        ])
        agent = Agent(llm_provider=llm, memory=ChannelMemory())

        resposta = self._turno(agent, "mude o nome do server pra pretinho")

        self.assertEqual(resposta, "Não posso mudar o nome do servidor agora.")
        self.assertNotIn("thinking", resposta.lower())

    def test_resposta_gigante_em_portugues_tambem_e_reescrita(self) -> None:
        llm = FakeLLM([
            LLMResponse(content="Feito! " + ("detalhe importante " * 200), tool_calls=[]),
            LLMResponse(content="Pronto, canais criados.", tool_calls=[]),
        ])
        agent = Agent(llm_provider=llm, memory=ChannelMemory())

        resposta = self._turno(agent, "crie uns canais")

        self.assertEqual(resposta, "Pronto, canais criados.")
        self.assertLess(len(resposta), 1000)

    def test_quando_o_modelo_insiste_no_ingles_a_resposta_e_o_resultado_da_ferramenta(self) -> None:
        """Nem a reescrita deu certo: o bot entrega o que a ferramenta respondeu (em PT)."""
        apagados: list[str] = []

        def canal(cid: int, nome: str) -> SimpleNamespace:
            ch = SimpleNamespace(id=cid, name=nome, mentions=[], channels=None)
            async def delete(_n=nome):
                apagados.append(_n)
            ch.delete = delete
            return ch

        self.canais.extend([canal(11, "canal-a"), canal(12, "canal-b")])
        self.guild.get_channel = lambda cid: next((c for c in self.canais if c.id == cid), None)

        llm = FakeLLM([
            LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="delete_channels",
                                                         args={"channels": ["11", "12"]})]),
            LLMResponse(content=self.TEXTao_EN, tool_calls=[]),
            LLMResponse(content=self.TEXTao_EN, tool_calls=[]),  # reescrita também falhou
        ])
        agent = Agent(llm_provider=llm, memory=ChannelMemory())

        resposta = self._turno(agent, "apague os canais canal-a e canal-b e me diga se deu certo")

        self.assertEqual(sorted(apagados), ["canal-a", "canal-b"], "a ação em si precisa ter acontecido")
        self.assertIn("Exclusão concluída", resposta)
        self.assertNotIn("thinking", resposta.lower())
        self.assertLess(len(resposta), 1000)

    def test_sem_nada_para_dizer_o_fallback_e_curto_e_em_portugues(self) -> None:
        llm = FakeLLM([
            LLMResponse(content=self.TEXTao_EN, tool_calls=[]),
            LLMResponse(content="Let me think again about the user's request.", tool_calls=[]),
        ])
        agent = Agent(llm_provider=llm, memory=ChannelMemory())

        resposta = self._turno(agent, "oi")

        self.assertTrue(resposta.startswith("Feito"), resposta)
        self.assertLess(len(resposta), 200)
