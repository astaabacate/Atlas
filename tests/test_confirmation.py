"""
Testes da política de confirmação (CONFIRM_DESTRUCTIVE).

Padrão do dono (modo direto): o pedido do usuário já é a autorização — apaga e informa.
Modo cauteloso (CONFIRM_DESTRUCTIVE=true): 2+ canais, categoria ou cargo pedem "sim" antes.
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from brain.ops import op_delete_channels, op_delete_role
from brain.tools import ToolContext, ToolError


class TestConfirmation(unittest.TestCase):
    def setUp(self) -> None:
        self.actor_perms = SimpleNamespace(administrator=True, manage_channels=True, manage_roles=True)
        self.bot_perms = SimpleNamespace(administrator=True, manage_channels=True, manage_roles=True)
        self.actor = SimpleNamespace(id=1, guild_permissions=self.actor_perms)
        self.bot_member = SimpleNamespace(id=2, guild_permissions=self.bot_perms, top_role=SimpleNamespace(position=100))

    def _conversa(self, *canais: SimpleNamespace, atual: SimpleNamespace | None = None,
                  cauteloso: bool = False, categorias: list | None = None) -> ToolContext:
        guild = SimpleNamespace(channels=list(canais), categories=categorias or [],
                                me=self.bot_member, owner_id=1)
        return ToolContext(guild=guild, channel=atual if atual is not None else canais[0],
                           actor=self.actor, confirm_destructive=cauteloso)

    def test_single_nominal_channel_deletes_without_confirmation(self) -> None:
        deleted = False

        async def fake_delete():
            nonlocal deleted
            deleted = True

        alvo = SimpleNamespace(id=101, name="canal-teste", delete=fake_delete, channels=None)
        conversa = SimpleNamespace(id=100, name="geral", delete=lambda: None, channels=None)
        ctx = self._conversa(conversa, alvo, atual=conversa)

        # confirmed=False (padrão)
        res = asyncio.run(op_delete_channels(ctx, ["canal-teste"], confirmed=False))
        self.assertTrue(deleted, "Canal único nominal deve ser excluído sem pedir confirmação")
        self.assertIn("Exclusão concluída", res)

    def test_nunca_apaga_o_canal_onde_esta_a_conversa(self) -> None:
        """Bug ao vivo (18/09): "apague todos os canais menos esse" apagou o canal da conversa."""
        apagados: list[str] = []

        def canal(cid: int, nome: str) -> SimpleNamespace:
            ch = SimpleNamespace(id=cid, name=nome, channels=None)

            async def delete(_n=nome):
                apagados.append(_n)

            ch.delete = delete
            return ch

        conversa = canal(100, "geral")
        outro = canal(101, "off-topic")
        ctx = self._conversa(conversa, outro, atual=conversa)

        res = asyncio.run(op_delete_channels(ctx, ["geral", "off-topic"], confirmed=False))

        self.assertEqual(apagados, ["off-topic"], "o canal da conversa nunca pode ser apagado")
        self.assertIn("Mantive <#100> fora da lista", res)
        self.assertIn("menos esse", res)

    def test_pedido_para_apagar_so_o_canal_atual_recusa_com_motivo(self) -> None:
        conversa = SimpleNamespace(id=100, name="geral", delete=lambda: None, channels=None)
        ctx = self._conversa(conversa, atual=conversa)

        with self.assertRaises(ToolError) as err_ctx:
            asyncio.run(op_delete_channels(ctx, ["geral"], confirmed=False))

        msg = str(err_ctx.exception)
        self.assertIn("Não vou apagar o canal onde estamos conversando", msg)
        self.assertIn("clear_messages", msg)

    def test_modo_direto_apaga_lote_e_categoria_sem_perguntar(self) -> None:
        """Padrão: 'apague todos os canais MENOS esse' executa na hora (menos o da conversa)."""
        apagados: list[str] = []

        def canal(cid: int, nome: str) -> SimpleNamespace:
            ch = SimpleNamespace(id=cid, name=nome, channels=None)
            async def delete(_n=nome):
                apagados.append(_n)
            ch.delete = delete
            return ch

        c1, c2, c3 = canal(101, "canal-1"), canal(102, "canal-2"), canal(103, "canal-3")
        ctx = self._conversa(c1, c2, c3, atual=c1)  # confirm_destructive=False

        res = asyncio.run(op_delete_channels(ctx, ["canal-1", "canal-2"], confirmed=False))
        self.assertEqual(apagados, ["canal-2"], "apaga de verdade, mas nunca o canal da conversa")
        self.assertIn("Exclusão concluída", res)
        self.assertIn("Mantive <#101>", res)

    def test_modo_cauteloso_ainda_pergunta(self) -> None:
        conversa = SimpleNamespace(id=100, name="geral", delete=lambda: None, channels=None)
        ch1 = SimpleNamespace(id=101, name="canal-1", delete=lambda: None, channels=None)
        ch2 = SimpleNamespace(id=102, name="canal-2", delete=lambda: None, channels=None)
        ctx = self._conversa(conversa, ch1, ch2, atual=conversa, cauteloso=True)

        # confirmed=False deve levantar ToolError pedindo confirmação
        with self.assertRaises(ToolError) as err_ctx:
            asyncio.run(op_delete_channels(ctx, ["canal-1", "canal-2"], confirmed=False))

        msg = str(err_ctx.exception)
        self.assertIn("Isso apaga 2 canal(is)", msg)
        self.assertIn("confirmed=true", msg)

    def test_multiple_channels_execute_with_confirmed_true(self) -> None:
        deleted_count = 0

        async def fake_delete():
            nonlocal deleted_count
            deleted_count += 1

        conversa = SimpleNamespace(id=100, name="geral", delete=fake_delete, channels=None)
        ch1 = SimpleNamespace(id=101, name="canal-1", delete=fake_delete, channels=None)
        ch2 = SimpleNamespace(id=102, name="canal-2", delete=fake_delete, channels=None)
        ctx = self._conversa(conversa, ch1, ch2, atual=conversa)

        res = asyncio.run(op_delete_channels(ctx, ["canal-1", "canal-2"], confirmed=True))
        self.assertEqual(deleted_count, 2)
        self.assertIn("Exclusão concluída", res)

    def test_category_requires_confirmation_no_modo_cauteloso(self) -> None:
        sub_ch = SimpleNamespace(id=101, name="sub", delete=lambda: None)
        conversa = SimpleNamespace(id=100, name="geral", delete=lambda: None, channels=None)
        category = SimpleNamespace(id=200, name="Categoria Velha", delete=lambda: None, channels=[sub_ch])
        ctx = self._conversa(conversa, sub_ch, atual=conversa, cauteloso=True, categorias=[category])

        with self.assertRaises(ToolError) as err_ctx:
            asyncio.run(op_delete_channels(ctx, ["Categoria Velha"], confirmed=False))

        self.assertIn("confirmed=true", str(err_ctx.exception))

    def test_delete_role_requires_confirmation_no_modo_cauteloso(self) -> None:
        deleted = False

        async def fake_delete():
            nonlocal deleted
            deleted = True

        role = SimpleNamespace(id=300, name="CargoPerigoso", position=10, managed=False, is_default=lambda: False, delete=fake_delete)
        guild = SimpleNamespace(roles=[role], me=self.bot_member, owner_id=1)
        ctx = ToolContext(guild=guild, channel=None, actor=self.actor, confirm_destructive=True)

        # Sem confirmação -> lança ToolError
        with self.assertRaises(ToolError) as err_ctx:
            asyncio.run(op_delete_role(ctx, "CargoPerigoso", confirmed=False))
        self.assertIn("confirmed=true", str(err_ctx.exception))
        self.assertFalse(deleted)

        # Com confirmação -> executa
        res = asyncio.run(op_delete_role(ctx, "CargoPerigoso", confirmed=True))
        self.assertTrue(deleted)
        self.assertIn("excluído com sucesso", res)


if __name__ == "__main__":
    unittest.main()


class TestLimparConversaEMensagens(unittest.TestCase):
    """O que o dono reclamou: o bot disse que limpou o chat e o chat continuava lá."""

    def setUp(self) -> None:
        self.perms = SimpleNamespace(administrator=True, manage_channels=True,
                                     manage_roles=True, manage_messages=True)
        self.bot_member = SimpleNamespace(id=2, guild_permissions=self.perms,
                                          top_role=SimpleNamespace(position=100))
        self.actor = SimpleNamespace(id=1, guild_permissions=self.perms)

    def test_conversation_clear_nao_diz_que_apagou_mensagens(self) -> None:
        from brain.memory import ChannelMemory, memory_key
        from brain.ops import op_conversation_clear

        memoria = ChannelMemory()
        guild = SimpleNamespace(id=9, me=self.bot_member, channels=[], roles=[], owner_id=1)
        canal = SimpleNamespace(id=55, name="geral")
        chave = memory_key(guild.id, canal.id)
        memoria.add_message(chave, {"role": "user", "content": "oi"})

        ctx = ToolContext(guild=guild, channel=canal, actor=self.actor, memory=memoria)
        resposta = asyncio.run(op_conversation_clear(ctx))

        self.assertEqual(memoria.get_history(chave), [], "a memória não foi limpa de verdade")
        self.assertIn("clear_messages", resposta, "a resposta tem que apontar a ferramenta certa")

        texto = resposta.lower()
        for mentira in ("chat está limpo", "mensagens apagadas", "conversa apagada"):
            self.assertNotIn(mentira, texto, f"resposta mentiu: {resposta!r}")
        self.assertIn("as mensagens do canal continuam", texto)

    def test_clear_messages_apaga_de_verdade_e_conta_o_que_apagou(self) -> None:
        from brain.ops import op_clear_messages

        apagadas: list[str] = []

        class Msg:
            def __init__(self, n: int) -> None:
                self.n = n

            async def delete(self) -> None:
                apagadas.append(str(self.n))

        class Canal:
            id, name = 77, "geral"

            def __init__(self) -> None:
                self.usou_purge = False

            async def purge(self, limit: int = 50) -> list[Any]:
                self.usou_purge = True
                return [Msg(i) for i in range(min(limit, 3))]

        canal = Canal()
        guild = SimpleNamespace(id=9, me=self.bot_member, channels=[canal], roles=[], owner_id=1)
        ctx = ToolContext(guild=guild, channel=canal, actor=self.actor)

        resposta = asyncio.run(op_clear_messages(ctx, limit=3))

        self.assertTrue(canal.usou_purge, "não usou o caminho de bulk delete")
        self.assertIn("Apaguei 3 mensagem", resposta)
        self.assertIn("#geral", resposta)

    def test_clear_messages_sem_permissao_e_bloqueado(self) -> None:
        from brain.ops import op_clear_messages

        sem_permissao = SimpleNamespace(administrator=False, manage_messages=False)
        autor = SimpleNamespace(id=1, guild_permissions=sem_permissao)
        bot = SimpleNamespace(id=2, guild_permissions=self.perms, top_role=SimpleNamespace(position=100))

        class Canal:
            id, name = 77, "geral"

            async def purge(self, limit: int = 50) -> list[Any]:
                raise AssertionError("não podia nem tentar apagar")

        canal = Canal()
        guild = SimpleNamespace(id=9, me=bot, channels=[canal], roles=[], owner_id=1)
        ctx = ToolContext(guild=guild, channel=canal, actor=autor)

        with self.assertRaises(ToolError) as ctx_err:
            asyncio.run(op_clear_messages(ctx, limit=5))
        self.assertIn("Gerenciar mensagens", str(ctx_err.exception))

    def test_clear_messages_no_modo_cauteloso_pede_confirmacao(self) -> None:
        from brain.ops import op_clear_messages

        class Canal:
            id, name = 77, "geral"

            async def purge(self, limit: int = 50) -> list[Any]:
                raise AssertionError("apagou antes da confirmação")

        canal = Canal()
        guild = SimpleNamespace(id=9, me=self.bot_member, channels=[canal], roles=[], owner_id=1)
        ctx = ToolContext(guild=guild, channel=canal, actor=self.actor, confirm_destructive=True)

        with self.assertRaises(ToolError) as ctx_err:
            asyncio.run(op_clear_messages(ctx, limit=5))
        self.assertIn("confirmed=true", str(ctx_err.exception))
