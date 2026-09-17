"""
Testes de intents do Discord.
Garante que o bot nunca suba online e mudo.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

import discord

from core.bot import build_intents


class TestIntents(unittest.TestCase):
    def test_default_intents(self) -> None:
        cfg = SimpleNamespace(
            members_intent=False,
            message_content_intent=False,
        )
        intents = build_intents(cfg)

        # Intents essenciais para escutar mensagens e menções (não privilegiadas)
        self.assertTrue(intents.guilds, "guilds deve ser True")
        self.assertTrue(intents.guild_messages, "guild_messages deve ser True para receber on_message em servidores")
        self.assertTrue(intents.dm_messages, "dm_messages deve ser True para responder em DM")

        # Intents privilegiadas devem ser False por padrão para não falhar no gateway
        self.assertFalse(intents.members, "members deve ser False por padrão")
        self.assertFalse(intents.message_content, "message_content deve ser False por padrão")

    def test_privileged_intents_enabled_when_configured(self) -> None:
        cfg = SimpleNamespace(
            members_intent=True,
            message_content_intent=True,
        )
        intents = build_intents(cfg)
        self.assertTrue(intents.members)
        self.assertTrue(intents.message_content)

    def test_guilds_alone_does_not_receive_messages(self) -> None:
        """
        Teste de regressão do bug crítico:
        Intents(guilds=True) sozinho ativa APENAS o bit guilds e NÃO recebe mensagens.
        """
        raw_intents = discord.Intents(guilds=True)
        self.assertTrue(raw_intents.guilds)
        self.assertFalse(
            raw_intents.guild_messages,
            "Intents(guilds=True) sozinho tem guild_messages=False e deixa o bot mudo!",
        )
        self.assertFalse(
            raw_intents.dm_messages,
            "Intents(guilds=True) sozinho tem dm_messages=False!",
        )


if __name__ == "__main__":
    unittest.main()
