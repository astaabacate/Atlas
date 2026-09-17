"""
Cliente principal do bot Discord (FarolBot).
Gerencia ciclo de vida, intents, eventos on_message e feedback visual (👀 / ✅ / ❌).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict
from typing import TYPE_CHECKING

import discord

from core.helpers import split_message

if TYPE_CHECKING:
    from config import Config
    from brain.agent import Agent

logger = logging.getLogger("farol.bot")


def build_intents(config: Config) -> discord.Intents:
    """
    Constrói as intents necessárias.
    - guilds, guild_messages, dm_messages ativas por padrão (não privilegiadas).
    - members e message_content opcionais (privilegiadas).
    """
    intents = discord.Intents(
        guilds=True,
        guild_messages=True,
        dm_messages=True,
    )
    intents.members = config.members_intent
    intents.message_content = config.message_content_intent
    return intents


class FarolBot(discord.Client):
    def __init__(self, config: Config, agent: Agent, **kwargs) -> None:
        intents = build_intents(config)
        super().__init__(intents=intents, **kwargs)
        self.config = config
        self.agent = agent
        self._channel_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def on_ready(self) -> None:
        logger.info(
            "FarolBot conectado com sucesso como %s (ID: %s) em %d servidores.",
            self.user,
            self.user.id if self.user else "desconhecido",
            len(self.guilds),
        )

    async def on_message(self, message: discord.Message) -> None:
        # Ignorar outros bots e as próprias mensagens
        if message.author.bot or (self.user and message.author.id == self.user.id):
            return

        # DMs: responder explicando escopo
        if isinstance(message.channel, discord.DMChannel):
            await message.reply(
                "Olá! Eu sou o **farol**, especialista em estruturar e organizar servidores Discord.\n"
                "Eu só executo comandos dentro de servidores! Me adicione a um servidor e me mencione "
                "(`@farol <seu pedido>`) para começar."
            )
            return

        # Filtro de canais permitidos (se configurado)
        if self.config.allowed_channel_ids and message.channel.id not in self.config.allowed_channel_ids:
            return

        # Verificar se o bot foi mencionado
        if not self.user:
            return

        is_mentioned = (
            self.user in message.mentions
            or f"<@{self.user.id}>" in message.content
            or f"<@!{self.user.id}>" in message.content
        )

        if not is_mentioned:
            return

        # Disparar tarefa independente para não bloquear o loop de eventos
        asyncio.create_task(self._process_message_safe(message))

    async def _process_message_safe(self, message: discord.Message) -> None:
        # Reação imediata com 👀 para sinalizar que a mensagem foi recebida e começou a ser processada
        try:
            await message.add_reaction("👀")
        except Exception as exc:
            logger.debug("Não foi possível adicionar reação inicial: %s", exc)

        channel_id = message.channel.id
        async with self._channel_locks[channel_id]:
            success = False
            try:
                # Manter indicador de digitação enquanto a LLM e ferramentas rodam
                async with message.channel.typing():
                    # Remover menções ao bot do prompt
                    clean_text = re.sub(rf"<@!?{self.user.id}>", "", message.content).strip()

                    reply_text = await self.agent.process_turn(
                        guild=message.guild,
                        channel=message.channel,
                        actor=message.author,
                        prompt=clean_text,
                        attachments=list(message.attachments),
                    )

                    chunks = split_message(reply_text, limit=2000)
                    if chunks:
                        # Primeiro bloco como resposta (reply)
                        await message.reply(chunks[0], mention_author=False)
                        # Demais blocos enviados sequencialmente no mesmo canal
                        for extra in chunks[1:]:
                            await message.channel.send(extra)

                success = True

            except Exception as exc:
                logger.exception("Erro ao processar mensagem do usuário %s: %s", message.author, exc)
                try:
                    await message.reply(
                        f"❌ Ocorreu um erro ao processar seu pedido:\n`{exc}`\n"
                        "Se o erro persistir, verifique as permissões do meu cargo.",
                        mention_author=False,
                    )
                except Exception:
                    pass

            finally:
                # Atualizar reação: remover 👀 e colocar ✅ ou ❌
                try:
                    if self.user:
                        await message.remove_reaction("👀", self.user)
                except Exception:
                    pass

                try:
                    target_emoji = "✅" if success else "❌"
                    await message.add_reaction(target_emoji)
                except Exception as exc:
                    logger.debug("Não foi possível atualizar reação final: %s", exc)
