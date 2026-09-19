"""
Isolamento entre SERVIDORES — requisito de produto do Atlas.

O bot é vendido para vários donos de servidor e roda como UM processo atendendo todos:
conversa, pendência de confirmação e lock de um servidor NUNCA podem aparecer no outro.
Também garante que a memória não cresce para sempre (o bot fica anos no ar).
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from typing import Any

from brain.agent import Agent
from brain.memory import ChannelMemory, memory_key
from llm.base import ChatProvider, LLMResponse, ToolCall


class FakeLLM(ChatProvider):
    def __init__(self, respostas: list[LLMResponse]) -> None:
        self.respostas = list(respostas)
        self.prompts: list[str] = []

    async def chat(self, messages: list[dict[str, Any]], tools: Any = None,
                   timeout: float = 60.0, max_tokens: int = 1024) -> LLMResponse:
        self.prompts.append(messages[-1]["content"])
        return self.respostas.pop(0) if self.respostas else LLMResponse(content="Resposta padrão.")


def guild_com_canal(gid: int, cid: int, nome: str) -> tuple[SimpleNamespace, SimpleNamespace]:
    """Servidor de mentira com um canal de texto (IDs ficam fora da faixa do Discord)."""
    canal = SimpleNamespace(id=cid, name=nome)
    servidor = SimpleNamespace(
        id=gid, name=f"Servidor {gid}", channels=[canal], categories=[], roles=[],
        me=SimpleNamespace(id=gid * 10, guild_permissions=SimpleNamespace(administrator=True),
                           top_role=SimpleNamespace(position=100)),
        owner_id=gid * 10,
    )
    return servidor, canal


class TestChaveDeMemoria(unittest.TestCase):
    def test_chave_junta_servidor_e_canal(self) -> None:
        self.assertEqual(memory_key(111, 222), "111:222")
        self.assertNotEqual(memory_key(1, 2), memory_key(12, 3))  # sem ambiguidade
        self.assertTrue(memory_key(None, 5).startswith("?"))

    def test_duas_conversas_do_mesmo_processo_nao_se_misturam(self) -> None:
        mem = ChannelMemory()
        a, b = memory_key(1, 100), memory_key(2, 100)  # MESMO id de canal, servidores diferentes

        mem.add_message(a, {"role": "user", "content": "segredo do servidor A"})
        mem.add_message(b, {"role": "user", "content": "assunto do servidor B"})

        self.assertEqual([m["content"] for m in mem.get_history(a)], ["segredo do servidor A"])
        self.assertEqual([m["content"] for m in mem.get_history(b)], ["assunto do servidor B"])

    def test_limpar_um_canal_nao_afeta_o_outro_servidor(self) -> None:
        mem = ChannelMemory()
        a, b = memory_key(1, 100), memory_key(2, 100)
        mem.add_message(a, {"role": "user", "content": "A"})
        mem.add_message(b, {"role": "user", "content": "B"})

        mem.clear(a)

        self.assertEqual(mem.get_history(a), [])
        self.assertEqual([m["content"] for m in mem.get_history(b)], ["B"])

    def test_memoria_respeita_o_limite_de_conversas(self) -> None:
        """Bot que roda infinito não pode acumular conversa de todo mundo para sempre."""
        mem = ChannelMemory(max_conversations=3)
        for i in range(10):
            mem.add_message(memory_key(i, i), {"role": "user", "content": f"msg {i}"})

        self.assertEqual(len(mem), 3)
        self.assertEqual(mem.get_history(memory_key(0, 0)), [], "a conversa mais antiga deveria ter saído")
        self.assertEqual([m["content"] for m in mem.get_history(memory_key(9, 9))], ["msg 9"])

    def test_leitura_recente_sobrevive_a_evicao(self) -> None:
        mem = ChannelMemory(max_conversations=2)
        antiga, quente = memory_key(1, 1), memory_key(2, 2)
        mem.add_message(antiga, {"role": "user", "content": "antiga"})
        mem.add_message(quente, {"role": "user", "content": "quente"})

        mem.get_history(antiga)                      # usar conta como "recente"
        mem.add_message(memory_key(3, 3), {"role": "user", "content": "nova"})

        self.assertEqual([m["content"] for m in mem.get_history(antiga)], ["antiga"])
        self.assertEqual(mem.get_history(quente), [], "a menos usada deveria ter saído")

    def test_historico_por_canal_tem_teto_de_mensagens(self) -> None:
        mem = ChannelMemory(max_turns=1)
        chave = memory_key(1, 1)
        for i in range(50):
            mem.add_message(chave, {"role": "user", "content": f"m{i}"})

        hist = mem.get_history(chave)
        self.assertLessEqual(len(hist), 4)
        self.assertEqual(hist[-1]["content"], "m49")


class TestAgenteIsoladoPorServidor(unittest.TestCase):
    def test_resposta_de_um_servidor_nao_vaza_no_outro(self) -> None:
        servidor_a, canal_a = guild_com_canal(1001, 7001, "geral")
        servidor_b, canal_b = guild_com_canal(1002, 7001, "geral")  # mesmo id de canal, outra guild

        memoria = ChannelMemory()
        llm = FakeLLM([
            LLMResponse(content="No servidor A eu guardei: Pinguim.", tool_calls=[]),
            LLMResponse(content="No servidor B não sei de nada.", tool_calls=[]),
        ])
        agent = Agent(llm_provider=llm, memory=memoria, confirm_destructive=True)
        ator = SimpleNamespace(id=1, guild_permissions=SimpleNamespace(administrator=True))

        asyncio.run(agent.process_turn(guild=servidor_a, channel=canal_a, actor=ator,
                                       prompt="Guarde: Pinguim"))
        asyncio.run(agent.process_turn(guild=servidor_b, channel=canal_b, actor=ator,
                                       prompt="Qual o apelido?"))

        chave_a = memory_key(servidor_a.id, canal_a.id)
        chave_b = memory_key(servidor_b.id, canal_b.id)
        self.assertEqual(len(memoria.get_history(chave_a)), 2)   # user + assistente
        self.assertEqual(len(memoria.get_history(chave_b)), 2)
        self.assertNotIn("Pinguim", " ".join(m["content"] for m in memoria.get_history(chave_b)))
        # o segundo turno do servidor B não recebeu o histórico do A como contexto
        self.assertNotIn("Pinguim", " ".join(llm.prompts[1:]))

    def test_confirmacao_pendente_e_por_conversa(self) -> None:
        """O 'sim' no servidor B não pode autorizar um lote pedido no servidor A."""
        servidor_a, canal_a = guild_com_canal(2001, 8001, "geral")
        servidor_b, canal_b = guild_com_canal(2002, 8002, "geral")
        apagados: list[str] = []

        def canal_apagavel(cid: int, nome: str) -> SimpleNamespace:
            ch = SimpleNamespace(id=cid, name=nome)

            async def delete() -> None:
                apagados.append(nome)

            ch.delete = delete
            return ch

        # A conversa acontece em canal_a/canal_b (8001/8002): o lote que o bot apaga é o resto
        servidor_a.channels = [canal_a, canal_apagavel(8003, "a-2"), canal_apagavel(8005, "a-3")]
        servidor_b.channels = [canal_b, canal_apagavel(8004, "b-2"), canal_apagavel(8006, "b-3")]
        for servidor in (servidor_a, servidor_b):
            servidor.get_channel = lambda cid, s=servidor: next((c for c in s.channels if c.id == cid), None)

        # servidor A pede um lote e o bot pergunta (fica pendente)
        agente = Agent(confirm_destructive=True, llm_provider=FakeLLM([
            LLMResponse(content="", tool_calls=[ToolCall(id="c0", name="delete_channels",
                                                         args={"channels": ["8003", "8005"]})]),
            LLMResponse(content="Confirma que posso apagar a-2 e a-3?", tool_calls=[]),
        ]), memory=ChannelMemory())
        ator = SimpleNamespace(id=1, guild_permissions=SimpleNamespace(administrator=True))
        asyncio.run(agente.process_turn(guild=servidor_a, channel=canal_a, actor=ator,
                                        prompt="apague a-1 e a-2 de uma vez"))
        self.assertEqual(apagados, [], "o lote do servidor A não deveria apagar sem confirmação")
        self.assertNotIn("geral", apagados, "a conversa jamais entra no lote")

        # o servidor B manda um "sim" e o modelo tenta se auto-confirmar com o lote DELE
        agente.llm = FakeLLM([
            LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="delete_channels",
                                                         args={"channels": ["8004", "8006"], "confirmed": True})]),
            LLMResponse(content="nada feito", tool_calls=[]),
        ])
        asyncio.run(agente.process_turn(guild=servidor_b, channel=canal_b, actor=ator, prompt="sim"))

        self.assertEqual(apagados, [], "o 'sim' de um servidor autorizou exclusão em lote no outro")
        pendente_a = agente.pending_confirmation(memory_key(servidor_a.id, canal_a.id))
        self.assertTrue(pendente_a, "a pendência do servidor A se perdeu")
        self.assertTrue("delete_channels" in pendente_a or "*" in pendente_a, pendente_a)

        # e o 'sim' DENTRO do servidor A continua valendo: só o lote do A sai, o do B fica
        agente.llm = FakeLLM([
            LLMResponse(content="", tool_calls=[ToolCall(id="c2", name="delete_channels",
                                                         args={"channels": ["8003", "8005"], "confirmed": True})]),
            LLMResponse(content="Pronto!", tool_calls=[]),
        ])
        asyncio.run(agente.process_turn(guild=servidor_a, channel=canal_a, actor=ator, prompt="sim, pode apagar"))

        self.assertEqual(sorted(apagados), ["a-2", "a-3"], "o lote do próprio servidor A não foi apagado")
        self.assertNotIn("b-2", apagados)
        self.assertNotIn("b-3", apagados)
        self.assertEqual(agente.pending_confirmation(memory_key(servidor_a.id, canal_a.id)), set())
        # o pedido do servidor B continua pendente lá (não foi afetado pelo "sim" do A)
        self.assertTrue(agente.pending_confirmation(memory_key(servidor_b.id, canal_b.id)))

    def test_sim_no_mesmo_servidor_autoriza_o_lote(self) -> None:
        """Contraprova: no servidor onde o bot perguntou, o 'sim' funciona."""
        servidor, canal = guild_com_canal(2101, 8101, "geral")
        apagados: list[str] = []

        def canal_apagavel(cid: int, nome: str) -> SimpleNamespace:
            ch = SimpleNamespace(id=cid, name=nome)

            async def delete() -> None:
                apagados.append(nome)

            ch.delete = delete
            return ch

        servidor.channels = [canal, canal_apagavel(8102, "x-2"), canal_apagavel(8103, "x-3")]
        servidor.get_channel = lambda cid: next((c for c in servidor.channels if c.id == cid), None)

        agente = Agent(confirm_destructive=True, llm_provider=FakeLLM([
            LLMResponse(content="", tool_calls=[ToolCall(id="c0", name="delete_channels",
                                                         args={"channels": ["8102", "8103"]})]),
            LLMResponse(content="Confirma que posso apagar x-2 e x-3?", tool_calls=[]),
        ]), memory=ChannelMemory())
        ator = SimpleNamespace(id=1, guild_permissions=SimpleNamespace(administrator=True))
        asyncio.run(agente.process_turn(guild=servidor, channel=canal, actor=ator,
                                        prompt="apague x-1 e x-2 de uma vez"))
        self.assertEqual(apagados, [])

        agente.llm = FakeLLM([
            LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="delete_channels",
                                                         args={"channels": ["8102", "8103"], "confirmed": True})]),
            LLMResponse(content="Pronto!", tool_calls=[]),
        ])
        asyncio.run(agente.process_turn(guild=servidor, channel=canal, actor=ator, prompt="sim, pode apagar"))

        self.assertEqual(sorted(apagados), ["x-2", "x-3"])

    def test_pendencias_nao_crescem_sem_limite(self) -> None:
        agente = Agent(confirm_destructive=True, llm_provider=FakeLLM([]), memory=ChannelMemory())
        agente.max_pending_confirmations = 3
        for i in range(10):
            agente._marcar_pendencia(memory_key(1, i), {"delete_channels"})

        self.assertEqual(len(agente._aguardando_confirmacao), 3)
        self.assertEqual(agente.pending_confirmation(memory_key(1, 9)), {"delete_channels"})
        self.assertEqual(agente.pending_confirmation(memory_key(1, 0)), set())

    def test_conversation_clear_limpa_so_o_canal_de_origem(self) -> None:
        from brain.executors import execute_tool
        from brain.tools import ToolContext

        servidor_a, canal_a = guild_com_canal(3001, 9001, "geral")
        servidor_b, canal_b = guild_com_canal(3002, 9002, "geral")
        memoria = ChannelMemory()
        memoria.add_message(memory_key(servidor_a.id, canal_a.id), {"role": "user", "content": "A"})
        memoria.add_message(memory_key(servidor_b.id, canal_b.id), {"role": "user", "content": "B"})

        ctx = ToolContext(guild=servidor_a, channel=canal_a,
                          actor=SimpleNamespace(id=1, guild_permissions=SimpleNamespace(administrator=True)),
                          memory=memoria)
        asyncio.run(execute_tool("conversation_clear", {}, ctx))

        self.assertEqual(memoria.get_history(memory_key(servidor_a.id, canal_a.id)), [])
        self.assertEqual([m["content"] for m in memoria.get_history(memory_key(servidor_b.id, canal_b.id))], ["B"])


class TestLocksDoBot(unittest.TestCase):
    def test_lock_e_por_conversa_e_nao_cresce_sem_limite(self) -> None:
        import core.bot as bot_mod

        if not hasattr(bot_mod.AtlasBot, "_lock_for"):  # pragma: no cover - sanidade
            self.skipTest("AtlasBot sem _lock_for")

        class BotFalso:
            _lock_for = bot_mod.AtlasBot._lock_for
            max_channel_locks = 3

            def __init__(self) -> None:
                self._channel_locks: dict[Any, asyncio.Lock] = {}

        bot = BotFalso()
        l1 = bot._lock_for("1:1")
        self.assertIs(bot._lock_for("1:1"), l1, "mesma conversa deveria reaproveitar o lock")
        self.assertIsNot(bot._lock_for("2:1"), l1, "servidores diferentes precisam de locks diferentes")

        for i in range(10):
            bot._lock_for(memory_key(9, i))

        self.assertLessEqual(len(bot._channel_locks), 3)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
