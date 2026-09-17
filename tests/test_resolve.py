"""
Testes de resolução de canais, cargos e membros.
Aceita ID, menções, nomes exatos, nomes com prefixos e busca parcial ("contém").
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from brain.resolve import resolve_channel, resolve_member, resolve_role
from brain.tools import ToolError


class TestResolve(unittest.TestCase):
    def setUp(self) -> None:
        self.ch_geral = SimpleNamespace(id=101, name="geral")
        self.ch_voz = SimpleNamespace(id=102, name="🔊-lobby-1")
        self.cat_info = SimpleNamespace(id=103, name="📢 INFORMAÇÕES", channels=[])

        self.role_admin = SimpleNamespace(id=201, name="Admin")
        self.role_mod = SimpleNamespace(id=202, name="Moderador Gamer")

        self.member_pedro = SimpleNamespace(id=301, name="pedro_silva", nick="Pedrão", display_name="Pedrão")
        self.member_joao = SimpleNamespace(id=302, name="joao123", nick=None, display_name="joao123")

        self.guild = SimpleNamespace(
            channels=[self.ch_geral, self.ch_voz],
            categories=[self.cat_info],
            roles=[self.role_admin, self.role_mod],
            members=[self.member_pedro, self.member_joao],
        )

    def test_resolve_channel_by_id(self) -> None:
        res = resolve_channel(self.guild, "101")
        self.assertEqual(res, self.ch_geral)

    def test_resolve_channel_by_mention(self) -> None:
        res = resolve_channel(self.guild, "<#102>")
        self.assertEqual(res, self.ch_voz)

    def test_resolve_channel_by_exact_name(self) -> None:
        res = resolve_channel(self.guild, "geral")
        self.assertEqual(res, self.ch_geral)

    def test_resolve_channel_by_name_with_hash(self) -> None:
        res = resolve_channel(self.guild, "#geral")
        self.assertEqual(res, self.ch_geral)

    def test_resolve_channel_case_insensitive_and_contains(self) -> None:
        res = resolve_channel(self.guild, "lobby-1")
        self.assertEqual(res, self.ch_voz)

    def test_resolve_channel_category(self) -> None:
        res = resolve_channel(self.guild, "INFORMAÇÕES")
        self.assertEqual(res, self.cat_info)

    def test_resolve_channel_not_found(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            resolve_channel(self.guild, "canal-fantasma")
        self.assertIn("não foi encontrado", str(ctx.exception))

    def test_resolve_role_by_id_and_mention(self) -> None:
        self.assertEqual(resolve_role(self.guild, "201"), self.role_admin)
        self.assertEqual(resolve_role(self.guild, "<@&202>"), self.role_mod)

    def test_resolve_role_by_name_and_prefix(self) -> None:
        self.assertEqual(resolve_role(self.guild, "@Admin"), self.role_admin)
        self.assertEqual(resolve_role(self.guild, "moderador"), self.role_mod)

    def test_resolve_role_not_found(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            resolve_role(self.guild, "VIP")
        self.assertIn("Cargo 'VIP' não foi encontrado", str(ctx.exception))

    def test_resolve_member_by_id_and_mention(self) -> None:
        self.assertEqual(resolve_member(self.guild, "301"), self.member_pedro)
        self.assertEqual(resolve_member(self.guild, "<@302>"), self.member_joao)
        self.assertEqual(resolve_member(self.guild, "<@!301>"), self.member_pedro)

    def test_resolve_member_by_nick(self) -> None:
        self.assertEqual(resolve_member(self.guild, "pedrão"), self.member_pedro)


if __name__ == "__main__":
    unittest.main()
