"""
Cliente principal do bot Discord (FarolBot).
Gerencia ciclo de vida, intents, eventos on_message e feedback visual (👀 / ✅ / ❌).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any

import discord

from brain.memory import memory_key
from core.helpers import split_message
from core.look import Aparencia

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
        # Um lock por CONVERSA (servidor+canal) para não responder duas mensagens do mesmo
        # canal ao mesmo tempo. Limitado de propósito: o bot roda meses em centenas de
        # servidores e não pode acumular um lock por canal para sempre.
        self._channel_locks: dict[Any, asyncio.Lock] = {}
        self.max_channel_locks: int = 1000
        # Cara das respostas: cor medida do próprio avatar + mensagem em Components V2.
        self.aparencia = Aparencia(getattr(config, "accent_color", None),
                                   v2=bool(getattr(config, "mensagem_v2", True)))

    def _lock_for(self, key: Any) -> asyncio.Lock:
        lock = self._channel_locks.get(key)
        if lock is None:
            if len(self._channel_locks) >= self.max_channel_locks:
                # descarta um lock que não está sendo usado agora
                for antigo, candidato in list(self._channel_locks.items()):
                    if not candidato.locked():
                        self._channel_locks.pop(antigo, None)
                        break
            lock = asyncio.Lock()
            self._channel_locks[key] = lock
        return lock

    async def _responder(self, message: discord.Message, texto: str) -> None:
        """
        Responde com a mensagem V2 (container na cor do farol) e, se não der, em texto.

        O enfeite é opcional por definição: qualquer falha aqui (API, versão, limite) cai no
        envio simples — a resposta do bot nunca fica presa por causa da aparência.
        """
        view = self.aparencia.view(texto)
        if view is not None:
            try:
                await message.reply(view=view, mention_author=False)
                return
            except Exception as exc:  # noqa: BLE001 - cai no texto simples
                logger.debug("Envio em Components V2 falhou (%s); respondendo em texto.", exc)
        await message.reply(texto, mention_author=False)

    async def on_ready(self) -> None:
        # Mede a cor do avatar uma vez (só precisa de rede na primeira vez)
        try:
            await self.aparencia.preparar(self.user)
        except Exception as exc:  # noqa: BLE001 - sem cor bonita o bot ainda responde
            logger.debug("Não consegui preparar a aparência: %s", exc)
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

    @staticmethod
    def _mensagem_de_erro(exc: BaseException) -> str:
        """
        Traduz a falha para o que o CLIENTE deve ler no Discord.

        Erro de LLM não é culpa de quem escreveu, e despejar a resposta crua dos provedores
        (HTTP 429 de três serviços) só assusta. O detalhe técnico fica no log.
        """
        from llm.auto import LLMUnavailableError

        if isinstance(exc, LLMUnavailableError):
            return exc.resumo_para_usuario()

        detail = " ".join(str(exc).split())
        if len(detail) > 300:
            detail = detail[:299].rstrip() + "…"
        return f"❌ Não consegui concluir seu pedido agora:\n`{detail}`"

    async def _process_message_safe(self, message: discord.Message) -> None:
        # Reação imediata com 👀 para sinalizar que a mensagem foi recebida e começou a ser processada
        try:
            await message.add_reaction("👀")
        except Exception as exc:
            logger.debug("Não foi possível adicionar reação inicial: %s", exc)

        # mesma chave do agente: servidor + canal (isolamento entre servidores)
        channel_id = memory_key(getattr(message.guild, "id", None), message.channel.id)
        async with self._lock_for(channel_id):
            success = False
            try:
                # Manter indicador de digitação enquanto a LLM e ferramentas rodam
                async with message.channel.typing():
                    # Remover menções ao bot do prompt
                    clean_text = re.sub(rf"<@!?{self.user.id}>", "", message.content).strip()

                    if not self.aparencia.cor_medida:
                        # Avatar trocado/sem medição ainda: mede agora (é a 1ª resposta)
                        try:
                            await self.aparencia.preparar(self.user)
                        except Exception as exc:  # noqa: BLE001 - a resposta não depende disso
                            logger.debug("Sem medir a cor do avatar: %s", exc)

                    reply_text = await self.agent.process_turn(
                        guild=message.guild,
                        channel=message.channel,
                        actor=message.author,
                        prompt=clean_text,
                        attachments=list(message.attachments),
                    )

                    chunks = split_message(reply_text, limit=2000)
                    if chunks:
                        # Primeiro bloco como resposta (reply), já com a cara do farol
                        await self._responder(message, chunks[0])
                        # Demais blocos enviados sequencialmente no mesmo canal
                        for extra in chunks[1:]:
                            await message.channel.send(extra)

                success = True

            except Exception as exc:
                logger.exception("Erro ao processar mensagem do usuário %s: %s", message.author, exc)
                try:
                    await message.reply(self._mensagem_de_erro(exc), mention_author=False)
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
