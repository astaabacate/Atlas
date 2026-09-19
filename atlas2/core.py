"""
O bot no Discord: recebe a mensagem, responde na hora.

Ordem de cada mensagem:
  1. 👀 na hora (a pessoa vê que foi ouvida em menos de 1 segundo);
  2. o parser local tenta entender — se entender, a ação roda JÁ (sem IA, sem espera);
  3. só se não entender, entra o modelo do OmniRoute, com a resposta aparecendo aos poucos.

Nada de esperar o bot "terminar tudo" para dar sinal de vida.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import discord

from atlas2.actions import Contexto, FalhaBot, executar
from atlas2.brain import Cerebro
from atlas2.config import Config
from atlas2.llm import LLM, LLMIndisponivel
from atlas2.parse import reconhecer  # noqa: E402
from atlas2.texto import tirar_mencao

logger = logging.getLogger("atlas2.core")

LIMITE_DISCORD = 1900
INTERVALO_DE_EDICAO = 1.1


def _pedacos(texto: str) -> list[str]:
    if len(texto) <= LIMITE_DISCORD:
        return [texto]
    pedacos, atual = [], ""
    for linha in texto.splitlines(keepends=True):
        if len(atual) + len(linha) > LIMITE_DISCORD:
            pedacos.append(atual.rstrip())
            atual = ""
        atual += linha
    if atual.strip():
        pedacos.append(atual.rstrip())
    return pedacos or [texto[:LIMITE_DISCORD]]


class Atlas(discord.Client):
    def __init__(self, cfg: Config) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = False
        super().__init__(intents=intents)
        self.cfg = cfg
        self.llm = LLM(cfg)
        self.cerebro = Cerebro(self.llm)
        self.travas: dict[int, asyncio.Lock] = {}
        self.demora_media: list[float] = []

    # ------------------------------------------------------------------ ciclo de vida
    async def on_ready(self) -> None:
        logger.info("Atlas no ar como %s (id %s) em %d servidor(es).",
                    self.user, getattr(self.user, "id", "?"), len(self.guilds))
        if not self.cfg.tem_llm:
            logger.warning("Sem OmniRoute configurado: só os comandos reconhecidos vão funcionar "
                           "(cadastre OMNIROUTE_URL e OMNIROUTE_KEY).")
        await self.change_presence(activity=discord.Game(name="faço o que você mandar ⚡"))

    async def on_message(self, mensagem: discord.Message) -> None:
        if mensagem.author.bot or self.user is None:
            return
        if mensagem.guild is None:
            try:
                await mensagem.reply("Me chame dentro do servidor que eu resolvo. 👋",
                                     mention_author=False)
            except Exception:  # noqa: BLE001
                pass
            return

        mencionado = any(u.id == self.user.id for u in mensagem.mentions)
        canal_liberado = bool(self.cfg.canais_permitidos) and \
            mensagem.channel.id in self.cfg.canais_permitidos
        if not mencionado and not canal_liberado:
            return
        if not self.cfg.canal_permitido(mensagem.channel.id):
            return

        pedido = tirar_mencao(mensagem.content, [self.user.id])
        # Trabalhar sem travar o gateway do Discord: a próxima mensagem pode chegar já.
        asyncio.create_task(self._atender(mensagem, pedido))

    # ------------------------------------------------------------------ trabalho
    async def _atender(self, mensagem: discord.Message, pedido: str) -> None:
        travas = self.travas.setdefault(mensagem.channel.id, asyncio.Lock())
        async with travas:
            inicio = time.monotonic()
            marca = asyncio.create_task(self._marcar(mensagem))
            try:
                if not pedido.strip():
                    await self._responder(mensagem, "Me diga o que fazer — ex.: `liste os canais`.")
                    return
                acao = reconhecer(pedido)
                if acao is not None and acao.tipo == "tempos":
                    await self._responder(mensagem, self.resumo_de_tempos())
                elif acao is not None:
                    logger.info("Comando reconhecido: %s", acao)
                    try:
                        resultado = await executar(acao, Contexto(mensagem.guild, mensagem.channel,
                                                                 mensagem.author))
                    except FalhaBot as exc:
                        await self._responder(mensagem, f"⚠️ {exc}")
                        return
                    await self._responder(mensagem, resultado)
                else:
                    await self._responder_com_ia(mensagem, pedido)
            except FalhaBot as exc:
                await self._responder(mensagem, f"⚠️ {exc}")
            except Exception as exc:  # noqa: BLE001 - o usuário precisa saber o que houve
                logger.exception("Falha atendendo o pedido")
                await self._responder(mensagem, f"❌ Deu erro aqui: {type(exc).__name__}: {exc}"[:400])
            finally:
                gasto = time.monotonic() - inicio
                self.demora_media.append(gasto)
                del self.demora_media[:-50]
                marca.cancel()
                logger.info("Pedido atendido em %.2fs", gasto)
                try:
                    await mensagem.remove_reaction("👀", self.user)
                    await mensagem.add_reaction("✅")
                except Exception:  # noqa: BLE001
                    pass

    async def _marcar(self, mensagem: discord.Message) -> None:
        """👀 imediato: a pessoa sabe que o bot ouviu, mesmo antes de qualquer ação."""
        try:
            await mensagem.add_reaction("👀")
        except Exception:  # noqa: BLE001
            pass

    async def _responder(self, mensagem: discord.Message, texto: str) -> None:
        for pedaco in _pedacos(texto or "Feito!"):
            try:
                await mensagem.reply(pedaco, mention_author=False)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Não consegui responder: %s", exc)
                try:
                    await mensagem.channel.send(pedaco)
                except Exception:  # noqa: BLE001
                    return

    async def _responder_com_ia(self, mensagem: discord.Message, pedido: str) -> None:
        """
        Pedido livre: responde em pedaços (streaming). O primeiro texto aparece na tela assim
        que o modelo solta a primeira palavra — não se espera a resposta inteira.
        """
        if not self.cfg.tem_llm:
            raise FalhaBot("Não reconheci esse pedido e não tenho IA configurada "
                           "(OMNIROUTE_URL/OMNIROUTE_KEY). Ex.: `crie 5 canais`.")
        espaco = await mensagem.reply("🤖 …", mention_author=False)
        guardado = {"texto": "", "editado": 0.0, "erro": None}

        async def mostrar(pedaco: str) -> None:
            guardado["texto"] += pedaco
            agora = time.monotonic()
            if agora - guardado["editado"] < INTERVALO_DE_EDICAO:
                return
            guardado["editado"] = agora
            try:
                await espaco.edit(content=(guardado["texto"].strip() or "🤖 …")[:LIMITE_DISCORD])
            except Exception as exc:  # noqa: BLE001 - edição falhar não pode parar a resposta
                guardado["erro"] = exc

        try:
            final = await self.cerebro.responder(
                pedido, Contexto(mensagem.guild, mensagem.channel, mensagem.author), mostrar)
        except LLMIndisponivel as exc:
            raise FalhaBot(f"A IA do OmniRoute não respondeu agora ({exc}).") from exc

        final = (final or "").strip() or "Feito!"
        try:
            await espaco.edit(content=final[:LIMITE_DISCORD])
        except Exception:  # noqa: BLE001
            await self._responder(mensagem, final)
        for extra in _pedacos(final)[1:]:
            try:
                await mensagem.channel.send(extra)
            except Exception:  # noqa: BLE001
                break

    async def close(self) -> None:
        await self.llm.fechar()
        await super().close()

    # ------------------------------------------------------------------ diagnóstico
    def resumo_de_tempos(self) -> str:
        if not self.demora_media:
            return "Ainda não respondi nada nesta sessão."
        media = sum(self.demora_media) / len(self.demora_media)
        ultima = self.demora_media[-1]
        return (f"⏱️ {len(self.demora_media)} pedido(s) nesta sessão · última {ultima:.2f}s · "
                f"média {media:.2f}s")


def montar_bot(cfg: Config) -> Atlas:
    return Atlas(cfg)


def _sem_uso(*_: Any) -> None:  # pragma: no cover - silencia linters de importação
    return None
