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

    def test_single_nominal_channel_deletes_without_confirmation(self) -> None:
        deleted = False

        async def fake_delete():
            nonlocal deleted
            deleted = True

        ch = SimpleNamespace(id=101, name="canal-teste", delete=fake_delete, channels=None)
        guild = SimpleNamespace(channels=[ch], categories=[], me=self.bot_member, owner_id=1)
        ctx = ToolContext(guild=guild, channel=ch, actor=self.actor)

        # confirmed=False (padrão)
        res = asyncio.run(op_delete_channels(ctx, ["canal-teste"], confirmed=False))
        self.assertTrue(deleted, "Canal único nominal deve ser excluído sem pedir confirmação")
        self.assertIn("Exclusão concluída", res)

    def test_modo_direto_apaga_lote_e_categoria_sem_perguntar(self) -> None:
        """Padrão: 'apague todos e deixe só esse' executa na hora."""
        apagados: list[str] = []

        def canal(cid: int, nome: str) -> SimpleNamespace:
            ch = SimpleNamespace(id=cid, name=nome, channels=None)
            async def delete(_n=nome):
                apagados.append(_n)
            ch.delete = delete
            return ch

        c1, c2, c3 = canal(101, "canal-1"), canal(102, "canal-2"), canal(103, "canal-3")
        guild = SimpleNamespace(channels=[c1, c2, c3], categories=[], me=self.bot_member, owner_id=1)
        ctx = ToolContext(guild=guild, channel=c1, actor=self.actor)  # confirm_destructive=False

        res = asyncio.run(op_delete_channels(ctx, ["canal-1", "canal-2"], confirmed=False))
        self.assertEqual(sorted(apagados), ["canal-1", "canal-2"], "sem perguntar, apagando de verdade")
        self.assertIn("Exclusão concluída", res)

    def test_modo_cauteloso_ainda_pergunta(self) -> None:
        ch1 = SimpleNamespace(id=101, name="canal-1", delete=lambda: None, channels=None)
        ch2 = SimpleNamespace(id=102, name="canal-2", delete=lambda: None, channels=None)
        guild = SimpleNamespace(channels=[ch1, ch2], categories=[], me=self.bot_member, owner_id=1)
        ctx = ToolContext(guild=guild, channel=ch1, actor=self.actor, confirm_destructive=True)

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

        ch1 = SimpleNamespace(id=101, name="canal-1", delete=fake_delete, channels=None)
        ch2 = SimpleNamespace(id=102, name="canal-2", delete=fake_delete, channels=None)
        guild = SimpleNamespace(channels=[ch1, ch2], categories=[], me=self.bot_member, owner_id=1)
        ctx = ToolContext(guild=guild, channel=ch1, actor=self.actor)

        res = asyncio.run(op_delete_channels(ctx, ["canal-1", "canal-2"], confirmed=True))
        self.assertEqual(deleted_count, 2)
        self.assertIn("Exclusão concluída", res)

    def test_category_requires_confirmation_no_modo_cauteloso(self) -> None:
        sub_ch = SimpleNamespace(id=101, name="sub", delete=lambda: None)
        category = SimpleNamespace(id=200, name="Categoria Velha", delete=lambda: None, channels=[sub_ch])
        guild = SimpleNamespace(channels=[sub_ch], categories=[category], me=self.bot_member, owner_id=1)
        ctx = ToolContext(guild=guild, channel=sub_ch, actor=self.actor, confirm_destructive=True)

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
