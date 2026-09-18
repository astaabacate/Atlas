"""Manda um "oi" ao vivo no servidor do Farol (teste real de ponta a ponta).

Fluxo: conecta com o DISCORD_TOKEN (igual ao main.py/E2E), escolhe o servidor
(E2E_GUILD_ID ou o maior por membros), escolhe um canal onde o bot pode escrever,
envia a mensagem curta e publica o resultado em reports/oi-latest.md.

Sem segredo em log ou relatório — o token só sai do ambiente do Actions.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MENSAGEM_PADRAO = "Oi! 👋 A nova IA assumiu o farol — teste de envio ao vivo."

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Envia um oi ao vivo pelo bot do Farol.")
    parser.add_argument("--guild-id", default="", help="ID do servidor (senão: E2E_GUILD_ID, senão o maior)")
    parser.add_argument("--channel-id", default="", help="ID do canal (senão: OI_CHANNEL_ID, senão o primeiro canal de texto onde o bot pode escrever)")
    parser.add_argument("--criar-canal", default=os.environ.get("OI_CRIAR_CANAL", "").strip(), help="nome de canal de texto para USAR (e criar se não existir)")
    parser.add_argument("--mensagem", default=os.environ.get("OI_MENSAGEM", "").strip() or MENSAGEM_PADRAO)
    parser.add_argument("--outdir", default="reports", help="pasta do relatório (default: reports)")
    parser.add_argument("--connect-timeout", type=int, default=60)
    return parser.parse_args()


class OiResultado:
    """Acumula o que aconteceu, para o relatório sair honesto em qualquer saída."""

    def __init__(self) -> None:
        self.notas: list[str] = []
        self.sucesso = False
        self.resumo = "não enviado"

    def nota(self, texto: str) -> None:
        self.notas.append(texto)
        print(f"• {texto}")


async def _conectar(discord: Any, config: Any, timeout: int, res: OiResultado) -> tuple[Any, Any]:
    """Mesma armação do E2E (scripts/e2e_live.py): login + gateway, com fallback
    de intents privilegiadas desligadas no Developer Portal."""
    from core.bot import build_intents

    async def subir(intents: Any) -> tuple[Any, Any, Any]:
        client = discord.Client(intents=intents)
        pronto = asyncio.Event()

        @client.event
        async def on_ready() -> None:  # noqa: ANN202
            pronto.set()

        await asyncio.wait_for(client.login(config.discord_token), timeout=45)
        tarefa = asyncio.create_task(client.connect(reconnect=False))
        await asyncio.wait_for(pronto.wait(), timeout=timeout)
        return client, tarefa, pronto

    try:
        client, tarefa, _ = await subir(build_intents(config))
        return client, tarefa
    except discord.PrivilegedIntentsRequired:
        res.nota("intents privilegiadas ligadas na config mas bloqueadas no portal; reconectei sem elas "
                 "(igual ao E2E — o bot real falharia ao subir assim)")
        intents_simples = discord.Intents(guilds=True, guild_messages=True, dm_messages=True)
        client, tarefa, _ = await subir(intents_simples)
        return client, tarefa


def _escolher_servidor(client: Any, guild_id: str, res: OiResultado) -> Any:
    servidores = list(client.guilds)
    if not servidores:
        raise RuntimeError("o bot não está em nenhum servidor — convide-o (README Passo 2)")
    if guild_id.strip().isdigit():
        alvo = next((g for g in servidores if str(g.id) == guild_id.strip()), None)
        if alvo is not None:
            return alvo
        res.nota(f"servidor {guild_id} não encontrado entre os {len(servidores)}; usando o maior por membros")
    escolhido = max(servidores, key=lambda g: getattr(g, "member_count", 0) or 0)
    nomes = ", ".join(f"{g.name} ({g.id})" for g in servidores)
    res.nota(f"servidores visíveis: {nomes}; escolhido: {escolhido.name}")
    return escolhido


async def _canal_por_nome(guild: Any, nome: str, res: OiResultado) -> Any:
    """Acha um canal de texto pelo nome; cria se não existir e o bot puder."""
    alvo = next((c for c in guild.text_channels if c.name == nome), None)
    if alvo is not None:
        res.nota(f"canal #{nome} já existia; reutilizado")
        return alvo
    if not guild.me.guild_permissions.manage_channels:
        res.nota(f"sem permissão de manage_channels para criar #{nome}; caindo para o primeiro canal escrevível")
        return None
    criado = await asyncio.wait_for(guild.create_text_channel(nome, reason="oi ao vivo do Farol (teste de ponta a ponta)"), timeout=30)
    res.nota(f"canal #{nome} criado agora ({criado.id})")
    return criado


def _escolher_canal(discord: Any, guild: Any, channel_id: str, res: OiResultado) -> Any:
    if channel_id.strip().isdigit():
        canal = guild.get_channel_or_thread(int(channel_id)) or guild.get_channel(int(channel_id))
        if canal is not None:
            return canal
        res.nota(f"canal {channel_id} não achado em {guild.name}; caindo para o primeiro canal de texto escrevível")
    for canal in guild.text_channels:  # já vem ordenado por posição e visível para o bot
        perms = canal.permissions_for(guild.me)
        if perms.send_messages and perms.view_channel:
            return canal
    raise RuntimeError(f"nenhum canal de texto escrevível para o bot em {guild.name}")


async def rodar() -> int:
    args = _parse_args()
    res = OiResultado()

    from config import Config, ConfigError

    try:
        config = Config.from_env()
    except ConfigError as exc:
        res.nota(f"configuração recusada: {exc}")
        _escrever_relatorio(args.outdir, res, None, None, "")
        return 1

    import discord

    client = None
    tarefa = None
    try:
        client, tarefa = await _conectar(discord, config, args.connect_timeout, res)
        guild = _escolher_servidor(client, args.guild_id or os.environ.get("E2E_GUILD_ID", ""), res)
        canal = await _canal_por_nome(guild, args.criar_canal, res) if args.criar_canal else None
        if canal is None:
            canal = _escolher_canal(discord, guild, args.channel_id or os.environ.get("OI_CHANNEL_ID", ""), res)
        enviada = await asyncio.wait_for(canal.send(args.mensagem), timeout=30)
        res.sucesso = True
        res.resumo = f"mensagem {enviada.id} entregue em #{canal.name}"
        link = getattr(enviada, "jump_url", "")
        _escrever_relatorio(args.outdir, res, guild, canal, link, enviada=enviada)
        print(f"✅ {res.resumo}")
        return 0
    except Exception as exc:  # noqa: BLE001 — o relatório precisa do motivo real
        res.nota(f"falha real: {type(exc).__name__}: {exc}")
        _escrever_relatorio(args.outdir, res, None, None, "")
        print(f"❌ oi não entregue: {type(exc).__name__}: {exc}")
        return 1
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                await client.close()
        if tarefa is not None:
            tarefa.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await tarefa


def _escrever_relatorio(outdir: str, res: OiResultado, guild: Any, canal: Any, link: str,
                        enviada: Any = None) -> None:
    pasta = Path(outdir)
    pasta.mkdir(parents=True, exist_ok=True)
    agora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    linhas = [
        "# 🏮 Oi ao vivo — Farol",
        "",
        f"- Quando: {agora}",
        f"- Resultado: {'✅ ' + res.resumo if res.sucesso else '❌ ' + res.resumo}",
    ]
    if guild is not None:
        linhas.append(f"- Servidor: {guild.name} ({guild.id})")
    if canal is not None:
        linhas.append(f"- Canal: #{canal.name} ({canal.id})")
    if enviada is not None and getattr(enviada, "author", None) is not None:
        linhas.append(f"- Enviada como: {enviada.author}")
    if link:
        linhas.append(f"- Link: {link}")
    if res.notas:
        linhas += ["", "Notas:", *[f"- {n}" for n in res.notas]]
    destino = pasta / "oi-latest.md"
    destino.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    print(f"relatório: {destino}")


def main() -> None:
    sys.exit(asyncio.run(rodar()))


if __name__ == "__main__":
    main()
