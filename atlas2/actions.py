"""
As ações de verdade no Discord. Nada aqui chama modelo: é API do Discord e pronto.

Três regras que vieram de bugs reais do dono:
  1. o canal onde a conversa acontece NUNCA é apagado (o bot tem que poder responder);
  2. "apague todos" lê a lista NA HORA (o servidor muda durante a conversa);
  3. depois de apagar, CONFERE na API: se sobrou canal, a resposta diz que sobrou.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Iterable

from atlas2.parse import Acao, nomes_gerados
from atlas2.texto import chave_de_nome, normalizar

logger = logging.getLogger("atlas2.actions")

LIMITE_CRIACAO = 3      # criar em paralelo demais toma rate limit do Discord
LIMITE_EXCLUSAO = 8     # apagar é leve; paralelo aqui é o que faz a resposta sair na hora


class FalhaBot(Exception):
    """Erro que o usuário PRECISA ler (permissão, não existe, pedido ambíguo)."""


@dataclass
class Contexto:
    guild: Any
    canal: Any
    autor: Any


# ------------------------------------------------------------------ utilidades

def _id_de_mencao(termo: str) -> int | None:
    import re

    m = re.search(r"<[#@&]!?(\d{5,25})>", termo or "")
    if m:
        return int(m.group(1))
    if str(termo or "").isdigit() and len(str(termo)) >= 5:
        return int(termo)
    return None


async def _canais_do_servidor(guild: Any) -> list[Any]:
    """Lista lida AGORA na API (com o cache como reserva, se a rede falhar)."""
    try:
        return list(await guild.fetch_channels())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Não consegui ler os canais na API (%s); usando o cache", exc)
        return list(getattr(guild, "channels", []) or [])


async def achar_canal(guild: Any, termo: str, canais: Iterable[Any] | None = None) -> Any:
    """
    Acha o canal/categoria pelo pedido do usuário: menção, id, nome exato ou nome parecido.

    Ordem importa: exato antes de parecido — foi assim que o bot apagou o canal errado no passado.
    """
    alvo = _id_de_mencao(termo)
    lista = list(canais) if canais is not None else await _canais_do_servidor(guild)
    if alvo is not None:
        for canal in lista:
            if getattr(canal, "id", None) == alvo:
                return canal
    pedido = chave_de_nome(termo)
    for canal in lista:
        if getattr(canal, "name", "") == termo or chave_de_nome(getattr(canal, "name", "")) == pedido:
            return canal
    for canal in lista:
        nome = chave_de_nome(getattr(canal, "name", ""))
        if pedido and (pedido in nome or nome in pedido):
            return canal
    raise FalhaBot(f"Não achei nenhum canal ou categoria chamado **{termo}**.")


def achar_cargo(guild: Any, termo: str) -> Any:
    alvo = _id_de_mencao(termo)
    cargos = list(getattr(guild, "roles", []) or [])
    if alvo is not None:
        for cargo in cargos:
            if getattr(cargo, "id", None) == alvo:
                return cargo
    pedido = chave_de_nome(termo)
    for cargo in cargos:
        if normalizar(getattr(cargo, "name", "")) == normalizar(termo):
            return cargo
    for cargo in cargos:
        if pedido and pedido in chave_de_nome(getattr(cargo, "name", "")):
            return cargo
    raise FalhaBot(f"Não achei nenhum cargo chamado **{termo}**.")


def _e_o_canal_da_conversa(ctx: Contexto, canal: Any) -> bool:
    return getattr(canal, "id", None) == getattr(ctx.canal, "id", None)


async def _em_lotes(itens: list[Any], limite: int, tarefa) -> list[tuple[Any, Exception | None]]:
    """Roda `tarefa` em paralelo com limite; devolve [(item, erro)] na ordem dada."""
    semaforo = asyncio.Semaphore(limite)
    resultados: dict[int, Exception | None] = {}

    async def _uma(indice: int, item: Any) -> None:
        async with semaforo:
            try:
                await tarefa(item)
                resultados[indice] = None
            except Exception as exc:  # noqa: BLE001 - uma falha não pode derrubar o lote
                resultados[indice] = exc

    await asyncio.gather(*(_uma(i, item) for i, item in enumerate(itens)))
    return [(item, resultados.get(i)) for i, item in enumerate(itens)]


async def _categoria_por_nome(guild: Any, nome: str) -> Any | None:
    try:
        canal = await achar_canal(guild, nome)
    except FalhaBot:
        return None
    return canal if str(getattr(getattr(canal, "type", None), "name", "")) == "category" else None


# ------------------------------------------------------------------ ações

async def apagar_canais(ctx: Contexto, dados: dict[str, Any]) -> str:
    guild = ctx.guild
    todos = bool(dados.get("todos"))
    nome_categoria = dados.get("categoria")

    if todos:
        alvos = await _canais_do_servidor(guild)
        if nome_categoria:
            categoria = await _categoria_por_nome(guild, nome_categoria)
            if categoria is None:
                raise FalhaBot(f"Não achei a categoria **{nome_categoria}** para apagar o que tem dentro.")
            alvos = [c for c in alvos if getattr(c, "category_id", None) == categoria.id]
    else:
        alvos = []
        for termo in dados.get("alvos", []):
            alvos.append(await achar_canal(guild, termo))

    mantidos: list[Any] = []
    if todos:
        alvos = [c for c in alvos if not _e_o_canal_da_conversa(ctx, c)]
        if nome_categoria is None:
            mantidos.append(ctx.canal)

    # nada de apagar duas vezes o mesmo canal (nome repetido no pedido)
    vistos: set[Any] = set()
    unicos = []
    for canal in alvos:
        if getattr(canal, "id", None) in vistos:
            continue
        vistos.add(getattr(canal, "id", None))
        unicos.append(canal)
    alvos = unicos

    if not alvos:
        if todos:
            raise FalhaBot("Só existe este canal aqui — não vou apagar o lugar onde estamos falando.")
        raise FalhaBot("Não entendi quais canais apagar. Diga os nomes ou peça 'todos os canais'.")

    apagados: list[str] = []
    falhas: list[str] = []

    async def _apagar(canal: Any) -> None:
        await canal.delete()

    for canal, erro in await _em_lotes(alvos, LIMITE_EXCLUSAO, _apagar):
        nome = getattr(canal, "name", "canal")
        if erro is None:
            apagados.append(f"#{nome}")
        else:
            falhas.append(f"#{nome} ({erro})")

    # Conferência: relê a API e confere o que realmente saiu.
    sobraram = []
    try:
        ids_alvo = {getattr(c, "id", None) for c in alvos}
        sobraram = [c for c in await _canais_do_servidor(guild) if getattr(c, "id", None) in ids_alvo]
    except Exception:  # noqa: BLE001 - sem leitura não se afirma nada
        sobraram = []

    if sobraram:
        for canal in sobraram:
            try:
                await canal.delete()
                apagados.append(f"#{getattr(canal, 'name', 'canal')}")
            except Exception as exc:  # noqa: BLE001
                falhas.append(f"#{getattr(canal, 'name', 'canal')} ({exc})")
        try:
            ids_alvo = {getattr(c, "id", None) for c in alvos}
            sobraram = [c for c in await _canais_do_servidor(guild) if getattr(c, "id", None) in ids_alvo]
        except Exception:  # noqa: BLE001
            sobraram = []

    if not apagados and falhas:
        raise FalhaBot("Não consegui apagar nada: " + "; ".join(falhas[:5]))
    if not apagados:
        raise FalhaBot("Não havia o que apagar (os canais do pedido já não existiam).")

    texto = f"🗑️ Apaguei **{len(apagados)}** canal(is): " + ", ".join(apagados[:15])
    if len(apagados) > 15:
        texto += f" … (+{len(apagados) - 15})"
    if mantidos:
        texto += f"\nℹ️ Mantive <#{getattr(ctx.canal, 'id', '')}> — é aqui que estamos conversando."
    if sobraram:
        nomes = ", ".join(f"#{getattr(c, 'name', 'canal')}" for c in sobraram)
        texto += f"\n⚠️ **Sobrou** (o Discord recusou): {nomes}"
    elif falhas:
        texto += f"\n⚠️ Falhas: {'; '.join(falhas[:5])}"
    else:
        texto += " — conferido no servidor."
    return texto


async def criar_canais(ctx: Contexto, dados: dict[str, Any]) -> str:
    guild = ctx.guild
    tipo = dados.get("tipo") or "text"
    via = guild.create_voice_channel if tipo == "voice" else guild.create_text_channel
    nomes = list(dados.get("nomes") or [])
    quantidade = int(dados.get("quantidade") or 0)
    if quantidade and len(nomes) < quantidade:
        # "crie os canais a e b" (2) ou "crie 5 canais" (nenhum nome): completa o que falta.
        nomes += nomes_gerados(quantidade - len(nomes), tipo)

    categoria = None
    if dados.get("categoria_nova"):
        categoria = await guild.create_category(str(dados["categoria_nova"]))
    elif dados.get("categoria"):
        categoria = await _categoria_por_nome(guild, str(dados["categoria"]))
        if categoria is None:
            raise FalhaBot(f"Não achei a categoria **{dados['categoria']}**.")

    if not nomes:
        raise FalhaBot("Não me disse o nome (nem a quantidade) dos canais.")

    kwargs = {"category": categoria} if categoria is not None else {}
    criados: list[str] = []
    erros: list[str] = []

    async def _criar(nome: str) -> None:
        canal = await via(name=str(nome), **kwargs)
        criados.append(f"<#{getattr(canal, 'id', '')}>")

    for nome, erro in await _em_lotes(nomes, LIMITE_CRIACAO, _criar):
        if erro is not None:
            erros.append(f"#{nome} ({erro})")

    if not criados:
        raise FalhaBot("Nenhum canal foi criado: " + "; ".join(erros[:3]))
    extra = f" na categoria **{dados.get('categoria') or dados.get('categoria_nova')}**" if categoria else ""
    texto = f"✅ Criei {len(criados)} canal(is){extra}: " + ", ".join(criados)
    if erros:
        texto += f"\n⚠️ Falhou: {'; '.join(erros[:3])}"
    return texto


async def criar_categoria(ctx: Contexto, dados: dict[str, Any]) -> str:
    nome = str(dados.get("nome") or "").strip()
    if not nome:
        raise FalhaBot("Não me disse o nome da categoria.")
    categoria = await ctx.guild.create_category(nome)
    return f"✅ Criei a categoria **{categoria.name}** (`{categoria.id}`)."


async def apagar_cargos(ctx: Contexto, dados: dict[str, Any]) -> str:
    guild = ctx.guild
    meus = {getattr(guild.me, "top_role", None)}
    if dados.get("todos"):
        alvos = [r for r in guild.roles
                 if not r.is_default() and not getattr(r, "managed", False) and r not in meus]
    else:
        alvos = [achar_cargo(guild, termo) for termo in dados.get("alvos", [])]
    alvos = [r for r in alvos if r is not None]
    if not alvos:
        raise FalhaBot("Não entendi quais cargos apagar.")

    apagados, falhas = [], []

    async def _apagar(cargo: Any) -> None:
        await cargo.delete()

    for cargo, erro in await _em_lotes(alvos, 4, _apagar):
        nome = getattr(cargo, "name", "cargo")
        (apagados if erro is None else falhas).append(nome if erro is None else f"{nome} ({erro})")
    if not apagados:
        raise FalhaBot("Nenhum cargo foi apagado: " + "; ".join(falhas[:3]))
    texto = f"🗑️ Apaguei {len(apagados)} cargo(s): " + ", ".join(f"**{n}**" for n in apagados)
    if falhas:
        texto += f"\n⚠️ Falhas: {'; '.join(falhas[:3])}"
    return texto


async def criar_cargos(ctx: Contexto, dados: dict[str, Any]) -> str:
    import discord

    guild = ctx.guild
    nomes = [n for n in (dados.get("nomes") or []) if str(n).strip()]
    if not nomes:
        raise FalhaBot("Não me disse o nome do cargo.")
    cor = dados.get("cor")
    criados, erros = [], []

    async def _criar(nome: str) -> None:
        kwargs = {"color": discord.Color(int(cor))} if cor is not None else {}
        cargo = await guild.create_role(name=str(nome), **kwargs)
        criados.append(f"<@&{cargo.id}>")

    for nome, erro in await _em_lotes(nomes, 3, _criar):
        if erro is not None:
            erros.append(f"{nome} ({erro})")
    if not criados:
        raise FalhaBot("Nenhum cargo foi criado: " + "; ".join(erros[:3]))
    texto = f"✅ Criei {len(criados)} cargo(s): " + ", ".join(criados)
    if erros:
        texto += f"\n⚠️ Falhou: {'; '.join(erros[:3])}"
    return texto


async def renomear_canal(ctx: Contexto, dados: dict[str, Any]) -> str:
    canal = await achar_canal(ctx.guild, str(dados.get("alvo") or ""))
    novo = str(dados.get("novo") or "").strip()
    if not novo:
        raise FalhaBot("Não me disse o novo nome.")
    antes = getattr(canal, "name", "")
    await canal.edit(name=novo)
    return f"✅ Renomeei **#{antes}** → **#{novo}** (<#{getattr(canal, 'id', '')}>)."


async def renomear_cargo(ctx: Contexto, dados: dict[str, Any]) -> str:
    cargo = achar_cargo(ctx.guild, str(dados.get("alvo") or ""))
    novo = str(dados.get("novo") or "").strip()
    if not novo:
        raise FalhaBot("Não me disse o novo nome.")
    if getattr(cargo, "managed", False):
        raise FalhaBot(f"O cargo **{cargo.name}** é de um bot/integração — o Discord não deixa eu mexer.")
    antes = cargo.name
    await cargo.edit(name=novo)
    return f"✅ Renomeei o cargo **{antes}** → **{novo}**."


async def mover_canal(ctx: Contexto, dados: dict[str, Any]) -> str:
    canal = await achar_canal(ctx.guild, str(dados.get("alvo") or ""))
    categoria = await _categoria_por_nome(ctx.guild, str(dados.get("categoria") or ""))
    if categoria is None:
        raise FalhaBot(f"Não achei a categoria **{dados.get('categoria')}**.")
    await canal.edit(category=categoria)
    return f"✅ Movi <#{getattr(canal, 'id', '')}> para a categoria **{categoria.name}**."


async def recriar_canal(ctx: Contexto, dados: dict[str, Any]) -> str:
    """Apaga e devolve o canal como estava (mesmo nome, tipo, tópico, posição e categoria)."""
    guild = ctx.guild
    canal = await achar_canal(guild, str(dados.get("alvo") or ""))
    if _e_o_canal_da_conversa(ctx, canal):
        raise FalhaBot("Esse é o canal onde estamos conversando — recriar agora me deixaria mudo. "
                       "Peça para outro canal.")
    tipo = str(getattr(getattr(canal, "type", None), "name", "text"))
    propriedades = {
        "name": getattr(canal, "name", "canal"),
        "topic": getattr(canal, "topic", None),
        "nsfw": getattr(canal, "nsfw", False),
        "slowmode_delay": getattr(canal, "slowmode_delay", 0),
        "position": getattr(canal, "position", 0),
        "category": getattr(canal, "category", None),
        "bitrate": getattr(canal, "bitrate", None),
        "user_limit": getattr(canal, "user_limit", 0),
    }
    categoria = propriedades.pop("category", None)
    propriedades = {k: v for k, v in propriedades.items() if v not in (None, False, 0)}
    if categoria is not None:
        propriedades["category"] = categoria
    if str(getattr(canal, "type", None)) == "voice":
        propriedades.pop("topic", None)
        propriedades.pop("nsfw", None)
    await canal.delete()
    via = guild.create_voice_channel if tipo == "voice" else guild.create_text_channel
    novo = await via(**propriedades)
    return f"♻️ Recriei <#{getattr(novo, 'id', '')}> como estava (mesmo nome, tipo e posição)."


async def limpar_mensagens(ctx: Contexto, dados: dict[str, Any]) -> str:
    canal = ctx.canal
    quantidade = dados.get("quantidade") or 200
    quantidade = max(1, min(int(quantidade), 1000))
    try:
        apagadas = await canal.purge(limit=quantidade, reason="Pedido do dono no chat")
    except Exception as exc:  # noqa: BLE001
        raise FalhaBot(f"Não consegui apagar as mensagens ({exc}). "
                       "Preciso da permissão 'Gerenciar mensagens' aqui.") from exc
    return f"🧹 Apaguei **{len(apagadas)}** mensagem(ns) deste canal."


async def listar_canais(ctx: Contexto, dados: dict[str, Any]) -> str:
    canais = await _canais_do_servidor(ctx.guild)
    categorias = [c for c in canais if str(getattr(getattr(c, "type", None), "name", "")) == "category"]
    texto = [f"📋 **{len(canais)} canais** (e {len(categorias)} categorias) em **{ctx.guild.name}**:"]
    sem_categoria = [c for c in canais if c not in categorias
                     and getattr(c, "category_id", None) is None]
    for categoria in sorted(categorias, key=lambda c: getattr(c, "position", 0)):
        texto.append(f"\n📁 **{categoria.name}**")
        dentro = [c for c in canais if getattr(c, "category_id", None) == categoria.id]
        texto.append("  " + (", ".join(f"<#{c.id}>" for c in dentro) or "_(vazia)_"))
    if sem_categoria:
        texto.append("\n📁 **(sem categoria)**")
        texto.append("  " + ", ".join(f"<#{c.id}>" for c in sem_categoria))
    resultado = "\n".join(texto)
    return resultado if len(resultado) < 1900 else resultado[:1900] + "…"


async def listar_cargos(ctx: Contexto, dados: dict[str, Any]) -> str:
    cargos = [r for r in ctx.guild.roles if not r.is_default()]
    cargos.sort(key=lambda r: r.position, reverse=True)
    lista = ", ".join(f"<@&{r.id}>" for r in cargos[:60])
    return f"🎭 **{len(cargos)} cargos**: {lista}" + ("…" if len(cargos) > 60 else "")


async def info_servidor(ctx: Contexto, dados: dict[str, Any]) -> str:
    guild = ctx.guild
    canais = await _canais_do_servidor(guild)
    dono = getattr(guild, "owner", None) or f"<@{getattr(guild, 'owner_id', '')}>"
    criado = getattr(guild, "created_at", None)
    quando = criado.strftime("%d/%m/%Y") if criado else "?"
    return (f"📊 **{guild.name}**\n"
            f"• 👑 Dono: {dono}\n"
            f"• 👥 Membros: {getattr(guild, 'member_count', len(getattr(guild, 'members', []) or []))}\n"
            f"• 💬 Canais: {len(canais)} · 🎭 Cargos: {len(getattr(guild, 'roles', []) or [])}\n"
            f"• 📅 Criado em: {quando}")


AJUDA = (
    "⚡ **Atlas** — eu faço o que você mandar no servidor. Exemplos:\n"
    "• `apague todos os canais e deixe apenas esse`\n"
    "• `crie 5 canais` · `crie um canal de voz chamado sala-1`\n"
    "• `crie a categoria Informações com os canais regras e avisos`\n"
    "• `apague o canal #avisos` · `renomeie o canal geral para bate-papo`\n"
    "• `mova o canal regras para a categoria Informações`\n"
    "• `crie o cargo Moderador vermelho` · `apague o cargo VIP`\n"
    "• `apague as mensagens desse canal` · `liste os canais` · `informações do servidor`\n"
    "Se o pedido não for nenhum desses, eu penso com a IA e faço do mesmo jeito."
)

CUMPRIMENTO = "Oi! 👋 Me diga o que fazer no servidor — ex.: `liste os canais`."


ACIONADORES = {
    "apagar_canais": lambda ctx, dados: apagar_canais(ctx, dados),
    "criar_canais": lambda ctx, dados: criar_canais(ctx, dados),
    "criar_categoria": lambda ctx, dados: criar_categoria(ctx, dados),
    "apagar_cargos": lambda ctx, dados: apagar_cargos(ctx, dados),
    "criar_cargos": lambda ctx, dados: criar_cargos(ctx, dados),
    "renomear_canal": lambda ctx, dados: renomear_canal(ctx, dados),
    "renomear_cargo": lambda ctx, dados: renomear_cargo(ctx, dados),
    "mover_canal": lambda ctx, dados: mover_canal(ctx, dados),
    "recriar_canal": lambda ctx, dados: recriar_canal(ctx, dados),
    "limpar_mensagens": lambda ctx, dados: limpar_mensagens(ctx, dados),
    "listar_canais": lambda ctx, dados: listar_canais(ctx, dados),
    "listar_cargos": lambda ctx, dados: listar_cargos(ctx, dados),
    "info_servidor": lambda ctx, dados: info_servidor(ctx, dados),
}


async def executar(acao: Acao, ctx: Contexto) -> str:
    if acao.tipo == "ajuda":
        return AJUDA
    if acao.tipo == "cumprimento":
        return CUMPRIMENTO
    funcao = ACIONADORES.get(acao.tipo)
    if funcao is None:
        raise FalhaBot(f"Pedido reconhecido, mas sem ação para '{acao.tipo}'.")
    return await funcao(ctx, acao.dados)
