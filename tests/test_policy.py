"""
Testes de política de permissões (Policy).
Checa os dois lados (autor e bot), bypass de administrador e hierarquia de cargos.
Duck-typed (sem dependência de discord).
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from brain.policy import require
from brain.tools import ToolError


class TestPolicy(unittest.TestCase):
    def test_author_missing_permission(self) -> None:
        actor_perms = SimpleNamespace(manage_channels=False, administrator=False)
        bot_perms = SimpleNamespace(manage_channels=True, administrator=False)

        with self.assertRaises(ToolError) as ctx:
            require("create_channels", actor_perms, bot_perms)
        self.assertIn("Você precisa da permissão 'Gerenciar canais'", str(ctx.exception))

    def test_bot_missing_permission(self) -> None:
        actor_perms = SimpleNamespace(manage_channels=True, administrator=False)
        bot_perms = SimpleNamespace(manage_channels=False, administrator=False)

        with self.assertRaises(ToolError) as ctx:
            require("create_channels", actor_perms, bot_perms)
        self.assertIn("Eu preciso da permissão 'Gerenciar canais'", str(ctx.exception))

    def test_admin_author_does_not_bypass_bot_missing_permission(self) -> None:
        """
        O dono ou autor ser Administrador NÃO supre a ausência de permissão no cargo do bot!
        """
        actor_perms = SimpleNamespace(administrator=True)
        bot_perms = SimpleNamespace(administrator=False, manage_channels=False)

        with self.assertRaises(ToolError) as ctx:
            require("create_channels", actor_perms, bot_perms)
        self.assertIn("Eu preciso da permissão", str(ctx.exception))

    def test_both_have_permission(self) -> None:
        actor_perms = SimpleNamespace(manage_channels=True, administrator=False)
        bot_perms = SimpleNamespace(manage_channels=True, administrator=False)

        # Não deve lançar exceção
        require("create_channels", actor_perms, bot_perms)

    def test_admin_bypass_for_both(self) -> None:
        actor_perms = SimpleNamespace(administrator=True)
        bot_perms = SimpleNamespace(administrator=True)

        require("create_channels", actor_perms, bot_perms)
        require("create_roles", actor_perms, bot_perms)
        require("apply_template", actor_perms, bot_perms)

    def test_role_hierarchy_everyone(self) -> None:
        actor_perms = SimpleNamespace(administrator=True)
        bot_perms = SimpleNamespace(administrator=True)
        role = SimpleNamespace(name="@everyone", position=0, managed=False, is_default=lambda: True)

        with self.assertRaises(ToolError) as ctx:
            require("delete_role", actor_perms, bot_perms, target_role=role)
        self.assertIn("Não é possível alterar ou excluir o cargo @everyone", str(ctx.exception))

    def test_role_hierarchy_managed(self) -> None:
        actor_perms = SimpleNamespace(administrator=True)
        bot_perms = SimpleNamespace(administrator=True)
        role = SimpleNamespace(name="BotIntegration", position=3, managed=True)

        with self.assertRaises(ToolError) as ctx:
            require("delete_role", actor_perms, bot_perms, target_role=role)
        self.assertIn("gerenciado por uma integração", str(ctx.exception))

    def test_role_hierarchy_above_bot(self) -> None:
        actor_perms = SimpleNamespace(administrator=True)
        bot_perms = SimpleNamespace(administrator=True)
        bot_member = SimpleNamespace(top_role=SimpleNamespace(position=5))
        role = SimpleNamespace(name="SuperCargo", position=10, managed=False)

        with self.assertRaises(ToolError) as ctx:
            require("delete_role", actor_perms, bot_perms, bot_member=bot_member, target_role=role)
        self.assertIn("está acima ou na mesma posição do meu cargo mais alto", str(ctx.exception))

    def test_role_hierarchy_above_actor(self) -> None:
        actor_perms = SimpleNamespace(administrator=True)
        bot_perms = SimpleNamespace(administrator=True)
        actor = SimpleNamespace(id=100, top_role=SimpleNamespace(position=4))
        guild = SimpleNamespace(owner_id=999)  # autor não é dono
        bot_member = SimpleNamespace(top_role=SimpleNamespace(position=10))
        role = SimpleNamespace(name="CargoAlto", position=6, managed=False)

        with self.assertRaises(ToolError) as ctx:
            require(
                "delete_role",
                actor_perms,
                bot_perms,
                actor=actor,
                bot_member=bot_member,
                guild=guild,
                target_role=role,
            )
        self.assertIn("Você não pode gerenciar o cargo", str(ctx.exception))

    def test_server_owner_bypasses_actor_hierarchy(self) -> None:
        actor_perms = SimpleNamespace(administrator=True)
        bot_perms = SimpleNamespace(administrator=True)
        owner = SimpleNamespace(id=999, top_role=SimpleNamespace(position=2))
        guild = SimpleNamespace(owner_id=999)
        bot_member = SimpleNamespace(top_role=SimpleNamespace(position=10))
        role = SimpleNamespace(name="CargoAlto", position=6, managed=False)

        # Como o autor é o dono do servidor, a hierarquia de usuário não o bloqueia
        require(
            "edit_role",
            actor_perms,
            bot_perms,
            actor=owner,
            bot_member=bot_member,
            guild=guild,
            target_role=role,
        )


if __name__ == "__main__":
    unittest.main()
