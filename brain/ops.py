"""
Implementação das 27 operações do atlas.
Executa ações no servidor do Discord de forma duck-typed (sem importar discord).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from typing import Any

from core.bulk import run_bulk

# Teto de mensagens por chamada (o Discord limita bulk delete a 100 por vez;
# 500 é o máximo que o bot aceita numa única ordem, em lotes internos do purge).
MAX_PURGE_MESSAGES = 500
from brain.policy import require
from brain.resolve import resolve_channel, resolve_member, resolve_role
from brain.ops_delete import (  # noqa: E402 - helpers testáveis da exclusão
    ainda_existem,
    e_item_de_tudo,
    e_pedido_de_todos,
    expandir_tudo,
    nomes,
)

from brain.tools import ToolContext, ToolError

logger = logging.getLogger("atlas.brain.ops")

# ---------------------------------------------------------------------------
# Permissões: nome amigável (PT-BR ou EN) → atributo do Discord
# ---------------------------------------------------------------------------
# O bot recebe pedido em português ("dê ver canal e enviar mensagens para @Membros"),
# mas o discord.py só aceita os atributos em inglês. Sem esta tradução o Python estoura
# `TypeError: got an unexpected keyword argument` — foi o que a auditoria encontrou em
# `set_permissions`, que repassava o texto do usuário direto para a API.
#
# A tabela de bits permite montar o campo `permissions` do cargo e LER de volta o que um
# cargo já tem (o discord.py só lê `.value`). O teste `TestMapaDePermissoes` confere cada
# bit contra o discord.py instalado: se a biblioteca mudar, o teste acusa.
PERMISSOES: dict[str, int] = {
    "create_instant_invite": 1 << 0,
    "kick_members": 1 << 1,
    "ban_members": 1 << 2,
    "administrator": 1 << 3,
    "manage_channels": 1 << 4,
    "manage_guild": 1 << 5,
    "add_reactions": 1 << 6,
    "view_audit_log": 1 << 7,
    "priority_speaker": 1 << 8,
    "stream": 1 << 9,
    "view_channel": 1 << 10,
    "send_messages": 1 << 11,
    "send_tts_messages": 1 << 12,
    "manage_messages": 1 << 13,
    "embed_links": 1 << 14,
    "attach_files": 1 << 15,
    "read_message_history": 1 << 16,
    "mention_everyone": 1 << 17,
    "use_external_emojis": 1 << 18,
    "view_guild_insights": 1 << 19,
    "connect": 1 << 20,
    "speak": 1 << 21,
    "mute_members": 1 << 22,
    "deafen_members": 1 << 23,
    "move_members": 1 << 24,
    "use_voice_activation": 1 << 25,
    "change_nickname": 1 << 26,
    "manage_nicknames": 1 << 27,
    "manage_roles": 1 << 28,
    "manage_webhooks": 1 << 29,
    "manage_guild_expressions": 1 << 30,
    "use_application_commands": 1 << 31,
    "request_to_speak": 1 << 32,
    "manage_events": 1 << 33,
    "manage_threads": 1 << 34,
    "create_public_threads": 1 << 35,
    "create_private_threads": 1 << 36,
    "use_external_stickers": 1 << 37,
    "send_messages_in_threads": 1 << 38,
    "use_embedded_activities": 1 << 39,
    "moderate_members": 1 << 40,
    "view_creator_monetization_analytics": 1 << 41,
    "use_soundboard": 1 << 42,
    "create_expressions": 1 << 43,
    "create_events": 1 << 44,
    "use_external_sounds": 1 << 45,
    "send_voice_messages": 1 << 46,
    "set_voice_channel_status": 1 << 48,
    "send_polls": 1 << 49,
    "use_external_apps": 1 << 50,
}

# Nomes alternativos (versões antigas da API e como as pessoas realmente escrevem)
ALIASES_PERMISSOES: dict[str, str] = {
    "manage_emojis_and_stickers": "manage_guild_expressions",
    "manage_emojis": "manage_guild_expressions",
    "use_slash_commands": "use_application_commands",
    "manage_guild_expressions_and_stickers": "manage_guild_expressions",
    "guild_expressions": "manage_guild_expressions",
    "use_external_emoji": "use_external_emojis",
    "read_history": "read_message_history",
    "view_audit_logs": "view_audit_log",
    "send_message": "send_messages",
    "view_channels": "view_channel",
}

# PT-BR → atributo (a chave é normalizada: minúscula, sem acento, espaço→_)
PERMISSOES_PT: dict[str, str] = {
    "ver_canal": "view_channel",
    "visualizar_canal": "view_channel",
    "ver_canais": "view_channel",
    "acessar_canal": "view_channel",
    "enviar_mensagens": "send_messages",
    "enviar_mensagem": "send_messages",
    "gerenciar_mensagens": "manage_messages",
    "apagar_mensagens": "manage_messages",
    "gerenciar_canais": "manage_channels",
    "gerenciar_cargos": "manage_roles",
    "gerenciar_servidor": "manage_guild",
    "administrador": "administrator",
    "admin": "administrator",
    "anexar_arquivos": "attach_files",
    "enviar_arquivos": "attach_files",
    "incorporar_links": "embed_links",
    "ler_historico": "read_message_history",
    "ver_historico": "read_message_history",
    "historico_de_mensagens": "read_message_history",
    "mencionar_todos": "mention_everyone",
    "mencionar_everyone": "mention_everyone",
    "conectar": "connect",
    "falar": "speak",
    "silenciar_membros": "mute_members",
    "mutar_membros": "mute_members",
    "ensurdecer_membros": "deafen_members",
    "mover_membros": "move_members",
    "usar_ativacao_por_voz": "use_voice_activation",
    "mudar_apelido": "change_nickname",
    "gerenciar_apelidos": "manage_nicknames",
    "gerenciar_webhooks": "manage_webhooks",
    "criar_convite": "create_instant_invite",
    "criar_convites": "create_instant_invite",
    "expulsar_membros": "kick_members",
    "banir_membros": "ban_members",
    "adicionar_reacoes": "add_reactions",
    "gerenciar_threads": "manage_threads",
    "criar_threads_publicas": "create_public_threads",
    "criar_threads_privadas": "create_private_threads",
    "usar_comandos": "use_application_commands",
    "usar_comandos_de_aplicacao": "use_application_commands",
    "usar_emojis_externos": "use_external_emojis",
    "usar_figurinhas_externas": "use_external_stickers",
    "prioridade_de_fala": "priority_speaker",
    "transmitir": "stream",
    "moderar_membros": "moderate_members",
    "ver_registro_de_auditoria": "view_audit_log",
    "gerenciar_eventos": "manage_events",
    "usar_atividades": "use_embedded_activities",
    "usar_placar_de_som": "use_soundboard",
    "criar_expressoes": "create_expressions",
    "criar_eventos": "create_events",
    "usar_sons_externos": "use_external_sounds",
    "enviar_mensagens_de_voz": "send_voice_messages",
    "definir_status_do_canal_de_voz": "set_voice_channel_status",
    "enviar_enquetes": "send_polls",
    "usar_apps_externos": "use_external_apps",
    "criar_expressoes_e_figurinhas": "create_expressions",
}


def _normalizar_permissao(nome: str) -> str:
    """minúsculas, sem acento, espaços/hífens viram underscore."""
    import unicodedata

    texto = unicodedata.normalize("NFKD", str(nome))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[\s\-]+", "_", texto.strip().lower())


def resolver_permissao(nome: str) -> str:
    """Traduz o nome (PT-BR, EN, com acento ou espaço) para o atributo do Discord."""
    chave = _normalizar_permissao(nome)
    if chave in PERMISSOES:
        return chave
    if chave in ALIASES_PERMISSOES:
        return ALIASES_PERMISSOES[chave]
    if chave in PERMISSOES_PT:
        return PERMISSOES_PT[chave]
    # "gerenciar mensagens" chega como 'gerenciar_mensagens' na primeira tentativa
    sem_gerenciar = chave[10:] if chave.startswith("gerenciar_") else None
    if sem_gerenciar:
        direto = f"manage_{sem_gerenciar}"
        if direto in PERMISSOES:
            return direto
    sugestoes = [n for n in PERMISSOES if chave and (chave[:4] in n or n[:4] in chave)][:5]
    raise ToolError(
        f"Não conheço a permissão '{nome}'. Use o nome do Discord em inglês "
        f"(ex.: view_channel, send_messages, manage_messages) ou em português "
        f"(ex.: ver canal, enviar mensagens, gerenciar mensagens)."
        + (f" Parecidas: {', '.join(sugestoes)}." if sugestoes else "")
    )


def resolver_permissoes(nomes: list[str]) -> list[str]:
    """Traduz uma lista, sem repetir e mantendo a ordem pedida."""
    saida: list[str] = []
    for nome in nomes or []:
        attr = resolver_permissao(nome)
        if attr not in saida:
            saida.append(attr)
    return saida


class Permissoes:
    """
    Bitfield de permissões duck-typed (o discord.py só lê `.value`).

    Mantém `brain/ops.py` sem importar discord — o resto do módulo é testado com objetos
    falsos — e o teste `TestMapaDePermissoes` garante que a tabela bate com o discord.py.
    """

    def __init__(self, nomes: list[str] | None = None, value: int = 0) -> None:
        total = value
        for attr in resolver_permissoes(list(nomes or [])):
            total |= PERMISSOES[attr]
        self.value = total

    def nomes(self) -> list[str]:
        """Nomes das permissões ligadas (para exportar/derivar relatórios)."""
        return [n for n, bit in PERMISSOES.items() if self.value & bit]

    def __or__(self, outro: "Permissoes") -> "Permissoes":
        return Permissoes(value=self.value | outro.value)

    def __eq__(self, outro: Any) -> bool:
        return getattr(outro, "value", None) == self.value

    def __repr__(self) -> str:
        return f"<Permissoes {self.value}>"


def permissoes_do_cargo(cargo: Any) -> Permissoes:
    """Lê as permissões de um cargo real do discord.py (que expõe `.value`)."""
    return Permissoes(value=int(getattr(getattr(cargo, "permissions", None), "value", 0) or 0))



async def _create_guild_channel(
    guild: Any,
    parent_cat: Any,
    kind: str,
    name: str,
    **extra: Any,
) -> Any:
    """
    Cria um canal de texto/voz dentro (ou fora) de uma categoria SEM repetir 'category'.

    No discord.py, `CategoryChannel.create_text_channel(name, **options)` já delega para
    `guild.create_text_channel(name, category=self, **options)`. Se passarmos `category`
    de novo, o Python estoura `TypeError: got multiple values for keyword argument 'category'`
    (era o que quebrava a criação de canais dentro de categorias e o apply_template).

    Regra: o método da categoria é chamado SEM `category`; o da guild, COM.
    """
    # kind = 'text' | 'voice' | 'stage' → create_text_channel / create_voice_channel / ...
    nome_metodo = f"create_{kind}_channel"

    creator_cat = getattr(parent_cat, nome_metodo, None) if parent_cat is not None else None
    if creator_cat is not None:
        return await _criar_com_retentativa(creator_cat, name=name, **extra)

    creator_guild = getattr(guild, nome_metodo, None)
    if creator_guild is None:
        return None
    if parent_cat is not None:
        extra["category"] = parent_cat
    return await _criar_com_retentativa(creator_guild, name=name, **extra)


async def _posicao_real(guild: Any, canal: Any, pedida: int) -> Any:
    """Posição efetiva do canal depois da edição (o Discord ordena junto com os vizinhos)."""
    cid = getattr(canal, "id", None)
    fetcher = getattr(guild, "fetch_channel", None)
    if cid is not None and fetcher is not None:
        try:
            fresco = await fetcher(cid)
            return getattr(fresco, "position", pedida)
        except Exception:  # noqa: BLE001 - sem rede/permissão, fica com o valor local
            pass
    return getattr(canal, "position", pedida)


def _validar_bitrate(guild: Any, valor: Any) -> int:
    """
    Valida o bitrate contra o limite REAL do servidor.

    O Discord recusa acima do teto do servidor (96 kbps sem boost, 128/256/384 com boosts) com
    um `400 Invalid Form Body` cripto — a auditoria pegou isso ao pedir 128000 num servidor sem
    boost. `Guild.bitrate_limit` diz o teto; sem ele, caímos no máximo teórico.
    """
    numero = _validar_faixa("bitrate", valor, 8000, 384_000)
    teto = getattr(guild, "bitrate_limit", None)
    try:
        teto = int(teto) if teto is not None else 384_000
    except (TypeError, ValueError):
        teto = 384_000
    if numero > teto:
        raise ToolError(
            f"O bitrate máximo deste servidor é {teto} bps ({teto // 1000} kbps) — pedi "
            f"{numero}. Ele sobe com os boosts do servidor (128k/256k/384k)."
        )
    return numero


def _traduzir_erro_de_canal(tipo: str, exc: Exception) -> str:
    """Erro cru do Discord sobre tipo de canal vira explicação em português."""
    texto = str(exc)
    if "50024" in texto or "channel type" in texto.lower():
        if tipo == "stage":
            return ("canal de palco (stage) só existe em servidor com o recurso **Comunidade** "
                    "ativado — sem isso o Discord recusa a criação.")
        if tipo == "forum":
            return ("canal de fórum precisa do recurso **Comunidade** ativado no servidor para o "
                    "Discord aceitar.")
        if tipo == "news":
            return ("canal de anúncios exige o recurso **Comunidade** e permissão de anúncios.")
    return texto


def _validar_faixa(nome: str, valor: Any, minimo: int, maximo: int) -> int:
    """Valida faixa numérica com mensagem em português (o Discord devolve erro cru)."""
    rotulos = {"slowmode_delay": "modo lento (slowmode)", "bitrate": "bitrate",
               "user_limit": "limite de usuários"}
    rotulo = rotulos.get(nome, nome)
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        raise ToolError(f"O valor de {rotulo} precisa ser um número inteiro (recebi {valor!r}).")
    if numero < minimo or numero > maximo:
        raise ToolError(f"O valor de {rotulo} precisa estar entre {minimo} e {maximo} (recebi {numero}).")
    return numero


def _parse_color(color_val: str | None) -> Any:
    if not color_val:
        return None
    c = color_val.strip().lstrip("#")
    try:
        val = int(c, 16)
        # Retorna um objeto simples duck-typed compatível com discord.Color
        class SimpleColor:
            def __init__(self, value: int):
                self.value = value
        return SimpleColor(val)
    except ValueError:
        return None


# --- 1. Canais (5) ---

async def _criar_canal_do_item(guild: Any, item: dict[str, Any]) -> Any:
    """
    Cria UM canal a partir do item (mesma lógica para `create_channels` e `import_structure`).

    `type` é respeitado de verdade: antes, `stage` e `forum` caíam no ramo de texto e o bot
    dizia "criei o canal" entregando um canal de texto — a auditoria pegou essa mentira.
    """
    tipos_conhecidos = ("text", "voice", "category", "stage", "forum", "news",
                        "texto", "voz", "categoria", "palco", "anuncio")

    name = str(item.get("name", "")).strip()
    if not name:
        raise ToolError("Todo canal precisa de um nome.")
    ch_type = str(item.get("type", "text")).lower()
    if ch_type not in tipos_conhecidos:
        raise ToolError(
            f"Tipo de canal '{ch_type}' não existe. Use: text, voice, category, stage ou forum."
        )
    if ch_type in ("texto",):
        ch_type = "text"
    elif ch_type in ("voz",):
        ch_type = "voice"
    elif ch_type in ("categoria",):
        ch_type = "category"
    elif ch_type in ("palco",):
        ch_type = "stage"
    elif ch_type in ("anuncio",):
        ch_type = "news"

    topic = item.get("topic")
    cat_query = item.get("category")

    parent_cat = None
    if cat_query:
        parent_cat = resolve_channel(guild, cat_query)

    created = None
    if ch_type == "category":
        creator = getattr(guild, "create_category", None)
        if creator:
            extras: dict[str, Any] = {}
            if item.get("position") is not None:
                extras["position"] = int(item["position"])
            created = await _criar_com_retentativa(creator, name=name, **extras)
    elif ch_type == "voice":
        extras = {}
        if item.get("user_limit") is not None:
            extras["user_limit"] = _validar_faixa("user_limit", item["user_limit"], 0, 99)
        if item.get("bitrate") is not None:
            extras["bitrate"] = _validar_bitrate(guild, item["bitrate"])
        if item.get("position") is not None:
            extras["position"] = int(item["position"])
        created = await _create_guild_channel(guild, parent_cat, "voice", name, **extras)
    elif ch_type == "forum":
        # discord.py 2.x: `create_forum` (não existe `create_forum_channel`), e o tópico é a
        # descrição do fórum. Antes o fórum caía no ramo de texto: o bot dizia "criei o canal"
        # entregando um canal de texto — a auditoria pegou essa mentira.
        extras = {"topic": topic} if topic else {}
        if parent_cat is not None:
            extras["category"] = parent_cat
        criador_forum = getattr(guild, "create_forum", None)
        if criador_forum is None:
            raise ToolError("Este ambiente não sabe criar canal de fórum (discord.py sem `create_forum`).")
        created = await _criar_com_retentativa(criador_forum, name=name, **extras)
    elif ch_type == "stage":
        created = await _create_guild_channel(guild, parent_cat, "stage", name)
    else:  # text / news
        extras = {"topic": topic} if topic else {}
        if item.get("nsfw") is not None:
            extras["nsfw"] = bool(item["nsfw"])
        if item.get("slowmode_delay") is not None:
            extras["slowmode_delay"] = _validar_faixa("slowmode_delay", item["slowmode_delay"],
                                                      0, 21_600)
        if item.get("position") is not None:
            extras["position"] = int(item["position"])
        created = await _create_guild_channel(guild, parent_cat, "text", name, **extras)

    if created is None:
        raise ToolError(
            f"Não foi possível criar o canal '{name}' do tipo '{ch_type}' "
            "(o servidor não expõe esse tipo para o bot)."
        )

    return created


async def op_create_channels(ctx: ToolContext, channels: list[dict[str, Any]]) -> str:
    if not channels:
        raise ToolError("A lista de canais para criar está vazia.")
    if len(channels) > 25:
        raise ToolError("O limite máximo por lote é de 25 canais.")

    guild = ctx.guild

    # Canal com o MESMO nome já existente não vira cópia: o dono do servidor reclamou de canais
    # duplicados (a conversa repetia o pedido e o modelo repetia a chamada). Se for para ter uma
    # cópia de verdade, o caminho é `clone_channel` — aí a cópia é o pedido, não um engano.
    por_nome: dict[str, list[Any]] = {}
    for canal in getattr(guild, "channels", []):
        por_nome.setdefault(str(getattr(canal, "name", "")).strip().casefold(), []).append(canal)

    alvos_apagados = {str(a).strip().casefold() for a in (getattr(ctx, "alvos_apagados", None) or set())}
    pulados: list[str] = []

    def _vai_ser_apagado(nome: str, objeto: Any) -> bool:
        """O canal que já existe com esse nome está na lista de exclusão desta mensagem?"""
        ident = str(getattr(objeto, "id", "")).strip().casefold()
        return nome.strip().casefold() in alvos_apagados or (ident and ident in alvos_apagados)

    def _ja_existe(nome: str, parent: Any, pediu_lugar: bool) -> Any:
        """
        Devolve o canal que torna esta criação uma duplicata, ou None.

        - pedido SEM categoria: qualquer canal com o mesmo nome já atende (era repetição do pedido);
        - pedido COM categoria: só é duplicata se houver o mesmo nome NAQUELE lugar — pedir um
          lugar diferente é escolha do usuário, não engano.
        """
        candidatos = por_nome.get(nome.strip().casefold(), [])
        if not candidatos:
            return None
        if not pediu_lugar:
            return candidatos[0]
        alvo_id = getattr(parent, "id", None)
        return next((c for c in candidatos
                     if getattr(getattr(c, "category", None), "id", None) == alvo_id), None)

    async def _create_one(item: dict[str, Any]) -> str:
        nome = str(item.get("name", "")).strip()
        categoria_item = item.get("category")
        parent = None
        if categoria_item:
            try:
                parent = resolve_channel(guild, str(categoria_item))
            except Exception:  # noqa: BLE001 - categoria inválida: deixa a criação reclamar
                parent = None
        ja_existe = _ja_existe(nome, parent, pediu_lugar=bool(categoria_item))
        if nome and ja_existe is not None and not _vai_ser_apagado(nome, ja_existe):
            pulados.append(nome)
            return f"#{nome} (já existia — não dupliquei)"

        chave = nome.strip().casefold()
        reserva = _NomeReservado(parent)
        if nome:
            por_nome.setdefault(chave, []).append(reserva)
        try:
            created = await _criar_canal_do_item(guild, item)
        except BaseException:
            if nome and reserva in por_nome.get(chave, []):
                por_nome[chave].remove(reserva)  # a criação falhou: libera o nome
            raise
        if nome:
            por_nome[chave] = [created if c is reserva else c for c in por_nome.get(chave, [])]
        cid = getattr(created, "id", "")
        cname = getattr(created, "name", item.get("name", ""))
        return f"<#{cid}>" if cid else f"#{cname}"

    res = await run_bulk(channels, _create_one, concurrency=3)
    if not res.succeeded and res.failed:
        err = res.failed[0][1]
        tipo_pedido = str(channels[0].get("type", "text")).lower() if channels else "text"
        raise ToolError(f"Falha ao criar canais: {_traduzir_erro_de_canal(tipo_pedido, err)}")

    criados = [c for c in res.succeeded if "(já existia" not in c]
    created_links = " ".join(criados)
    aviso = ""
    if pulados:
        nomes = ", ".join(f"**#{n}**" for n in pulados[:5])
        aviso = (f" ⚠️ {len(pulados)} já existia(m) com esse nome no mesmo lugar e eu NÃO "
                 f"dupliquei: {nomes} (quer uma cópia de verdade? me peça para clonar o canal).")
    if not criados:
        return f"Nenhum canal novo criado.{aviso}".strip()
    return (f"Pronto! Criei {len(criados)} canal(is): {created_links} 🎉 "
            f"({res.summary()}){aviso}")


async def op_edit_channel(
    ctx: ToolContext,
    channel: str,
    name: str | None = None,
    topic: str | None = None,
    category: str | None = None,
    slowmode_delay: int | None = None,
    nsfw: bool | None = None,
    bitrate: int | None = None,
    user_limit: int | None = None,
    position: int | None = None,
) -> str:
    ch = resolve_channel(ctx.guild, channel)

    kwargs: dict[str, Any] = {}
    if name is not None:
        kwargs["name"] = str(name).strip()
        if not kwargs["name"]:
            raise ToolError("O nome do canal não pode ficar vazio.")
    if topic is not None:
        kwargs["topic"] = topic
    if category is not None:
        if category.lower() in ("none", "nenhuma", "remover"):
            kwargs["category"] = None
        else:
            kwargs["category"] = resolve_channel(ctx.guild, category)
    if slowmode_delay is not None:
        kwargs["slowmode_delay"] = _validar_faixa("slowmode_delay", slowmode_delay, 0, 21_600)
    if nsfw is not None:
        kwargs["nsfw"] = bool(nsfw)
    if bitrate is not None:
        kwargs["bitrate"] = _validar_bitrate(ctx.guild, bitrate)
    if user_limit is not None:
        kwargs["user_limit"] = _validar_faixa("user_limit", user_limit, 0, 99)
    if position is not None:
        if int(position) < 0:
            raise ToolError("A posição do canal não pode ser negativa.")
        kwargs["position"] = int(position)

    if not kwargs:
        raise ToolError("Nenhum parâmetro de alteração foi informado para editar o canal.")

    editor = getattr(ch, "edit", None)
    if not editor:
        raise ToolError(f"O objeto do canal '{channel}' não suporta edição.")

    await editor(**kwargs)
    cid = getattr(ch, "id", "")
    mudancas = sorted(kwargs)
    if "position" in kwargs:
        real = await _posicao_real(ctx.guild, ch, kwargs["position"])
        return (f"Canal <#{cid}> atualizado com sucesso "
                f"({', '.join(mudancas)}; posição pedida {kwargs['position']}, real {real}).")
    return f"Canal <#{cid}> atualizado com sucesso ({', '.join(mudancas)})."


def _e_o_canal_da_conversa(ctx: ToolContext, ch: Any) -> bool:
    """True quando o canal é AQUELE onde o pedido foi feito (a conversa em andamento)."""
    atual = getattr(ctx, "channel", None)
    if atual is None or ch is None:
        return False
    if ch is atual:
        return True
    id_atual = getattr(atual, "id", None)
    id_alvo = getattr(ch, "id", None)
    return id_atual is not None and id_atual == id_alvo


async def op_delete_channels(
    ctx: ToolContext,
    channels: list[str],
    confirmed: bool = False,
) -> str:
    if not channels:
        raise ToolError("Nenhum canal foi informado para exclusão.")

    guild = ctx.guild
    resolved_channels = []
    category_channels_count = 0
    mantido: Any = None
    # "apague TODOS os canais" não pode depender da lista que o modelo tinha em mãos: o servidor
    # muda enquanto a conversa acontece (foi assim que sobrou canal — bug ao vivo de 18/09).
    # Aqui a lista de "todos" é montada NA HORA, direto da API.
    pedido_de_todos = e_pedido_de_todos(channels)
    if pedido_de_todos:
        expandidos = await expandir_tudo(guild, list(channels), fora=ctx.channel)
        if not expandidos:
            # Sem lista lida agora não se apaga "todos": seria adivinhar. Melhor dizer que não
            # deu e deixar o dono tentar de novo do que apagar um subconjunto e chamar de tudo.
            raise ToolError(
                "Não consegui ler a lista de canais do servidor agora (o Discord não respondeu). "
                "Tente de novo em alguns segundos — não vou apagar 'todos' no escuro."
            )
        # Os canais expandidos entram já resolvidos (são objetos frescos da API): passar por
        # nome/id de novo só daria chance de errar por causa do cache velho.
        channels = [*[c for c in channels if not e_item_de_tudo(c)], *expandidos]
        logger.info("Exclusão de TODOS os canais: %d alvo(s) lido(s) agora da API",
                    len(expandidos))
        if getattr(ctx, "channel", None) is not None:
            mantido = ctx.channel  # a nota "menos esse" vale também no caminho de "todos"
    # Bug do dono (18/09): "apague todos os canais menos esse" — o modelo mandou a lista com o
    # canal da conversa dentro e o bot apagou o canal onde estava falando (o pedido dizia o
    # contrário e a resposta nem teria onde aparecer). Canal da conversa NUNCA entra na lista.
    for q in channels:
        ch = q if not isinstance(q, str) else resolve_channel(guild, q)
        if _e_o_canal_da_conversa(ctx, ch):
            mantido = ch
            continue
        resolved_channels.append(ch)
        # Se for categoria, verificar quantos canais ela contém
        sub_channels = getattr(ch, "channels", None)
        if sub_channels:
            category_channels_count += len(sub_channels)

    if mantido is None:
        # Cinto de segurança: mesma proteção quando o alvo vem resolvido por outro caminho.
        for ch in list(resolved_channels):
            if _e_o_canal_da_conversa(ctx, ch):
                mantido = ch
                resolved_channels.remove(ch)
                category_channels_count = 0
                break
    nota_do_canal_atual = ""
    if mantido is not None:
        id_mantido = getattr(mantido, "id", "")
        nota_do_canal_atual = (f" Mantive <#{id_mantido}> fora da lista: "
                               "é aqui que estamos conversando (menos esse).")

    if not resolved_channels:
        raise ToolError(
            "Não vou apagar o canal onde estamos conversando: sem ele eu não teria como te "
            "responder. Se for para apagar este canal, faça pelas configurações do Discord "
            "(ou me peça para apagar as MENSAGENS daqui, com clear_messages)."
        )

    total_damage = len(resolved_channels) + category_channels_count
    is_single_nominal = len(resolved_channels) == 1 and category_channels_count == 0

    # Política de confirmação (CONFIRM_DESTRUCTIVE):
    # - desligada (padrão): quem pediu já autorizou — apaga e informa o resultado na hora;
    # - ligada: 1 canal nominal executa direto, 2+ canais ou categoria pedem confirmação.
    if ctx.confirm_destructive and not is_single_nominal and not confirmed:
        names = [getattr(c, "name", str(c)) for c in resolved_channels]
        names_str = ", ".join(f"**{n}**" for n in names)
        raise ToolError(
            f"Isso apaga {total_damage} canal(is) ({names_str}) — confirme com o usuário e chame de novo com confirmed=true."
        )

    async def _delete_one(ch_obj: Any) -> str:
        name = getattr(ch_obj, "name", "canal")
        deleter = getattr(ch_obj, "delete", None)
        if deleter:
            await deleter()
            return f"#{name}"
        raise ToolError(f"Canal '{name}' não pôde ser excluído.")

    res = await run_bulk(resolved_channels, _delete_one, concurrency=6)
    if not res.succeeded and res.failed:
        # Nada saiu: diz QUAIS falharam e por quê — "Falha ao excluir canais" sozinho não ajuda.
        err = res.failed[0][1]
        raise ToolError(f"Nenhum canal foi excluído. Falhas: {nomes([c for c, _ in res.failed])} "
                        f"({err})")

    # Conferência: o Discord pode ter recusado sem erro (canal já apagado, cache velho) e a
    # resposta não pode dizer "concluído" com canal em pé. Relê a lista e tenta UMA vez mais.
    restantes = await ainda_existem(guild, resolved_channels)
    if restantes:
        logger.info("Exclusão: %d canal(is) ainda em pé; tentando de novo", len(restantes))
        await run_bulk(restantes, _delete_one, concurrency=6)
        restantes = await ainda_existem(guild, resolved_channels)

    deleted_names = ", ".join(res.succeeded)
    if restantes:
        # Honestidade acima de tudo: diz o que sobrou e por quê, em vez de "concluído".
        return (f"🗑️ Apaguei {len(res.succeeded)} canal(is) ({res.summary()}). "
                f"NÃO consegui apagar: {nomes(restantes)} — o Discord recusou; tente de novo "
                f"ou apague pela interface.{nota_do_canal_atual}")
    return (f"🗑️ Exclusão concluída e conferida na API: {deleted_names} "
            f"({res.summary()}).{nota_do_canal_atual}")


async def op_move_channel(
    ctx: ToolContext,
    channel: str,
    category: str | None = None,
    position: int | None = None,
) -> str:
    ch = resolve_channel(ctx.guild, channel)
    kwargs: dict[str, Any] = {}
    if category is not None:
        if category.lower() in ("none", "nenhuma", "remover"):
            kwargs["category"] = None
        else:
            kwargs["category"] = resolve_channel(ctx.guild, category)
    if position is not None:
        kwargs["position"] = position

    if not kwargs:
        raise ToolError(
            "Diga para onde mover: informe a categoria de destino e/ou a posição "
            "(hoje o canal não foi movido)."
        )
    if "position" in kwargs and kwargs["position"] < 0:
        raise ToolError("A posição não pode ser negativa.")

    editor = getattr(ch, "edit", None)
    if editor:
        await editor(**kwargs)
        cid = getattr(ch, "id", "")
        detalhe = []
        if "category" in kwargs:
            alvo_cat = getattr(kwargs["category"], "name", "sem categoria")
            detalhe.append(f"categoria: {alvo_cat}")
        if "position" in kwargs:
            real = await _posicao_real(ctx.guild, ch, kwargs["position"])
            detalhe.append(f"posição pedida {kwargs['position']}, real {real}")
        return f"Canal <#{cid}> movido com sucesso ({', '.join(detalhe)})."
    raise ToolError("Não foi possível mover o canal.")


async def op_clone_channel(
    ctx: ToolContext,
    channel: str,
    name: str | None = None,
) -> str:
    ch = resolve_channel(ctx.guild, channel)
    cloner = getattr(ch, "clone", None)
    if not cloner:
        raise ToolError(f"O canal '{channel}' não suporta clonagem.")

    nome_original = getattr(ch, "name", str(channel))
    kwargs = {}
    if name:
        kwargs["name"] = name
    cloned = await cloner(**kwargs)
    cid = getattr(cloned, "id", "")

    # O clone do discord.py copia tópico/NSFW/modo lento/categoria/permissões (e, em voz,
    # bitrate+limite) — mas NÃO copia a POSIÇÃO: o "canal recriado" caía no fim da lista.
    posicao = getattr(ch, "position", None)
    aviso_posicao = ""
    editor = getattr(cloned, "edit", None)
    if posicao is not None and callable(editor):
        try:
            await editor(position=int(posicao))
            aviso_posicao = f", posição {int(posicao)}"
        except Exception as exc:  # noqa: BLE001 - a cópia já existe; a posição é o acabamento
            aviso_posicao = f" (⚠️ não consegui copiar a posição {int(posicao)}: {exc})"

    return (f"Canal clonado: <#{cid}> 🎉 (copiei tópico, NSFW, modo lento, categoria e "
            f"permissões{aviso_posicao}). O original **#{nome_original}** continua aí — se ele não "
            "devia ficar, me diga que eu apago.")


# --- 2. Cargos (6) ---

async def op_create_roles(
    ctx: ToolContext,
    roles: list[dict[str, Any]],
    permissions: list[str] | None = None,
    position: int | None = None,
) -> str:
    if not roles:
        raise ToolError("A lista de cargos para criar está vazia.")
    if len(roles) > 25:
        raise ToolError("O limite máximo por lote é de 25 cargos.")

    guild = ctx.guild
    permissoes_globais = [str(p) for p in (permissions or [])]

    # Nome já existente NÃO vira cargo duplicado: o dono do servidor reclamou de cargos
    # repetidos criados por uma ordem só (o modelo repetia a chamada / a conversa repetia o
    # pedido). Criar de novo com o mesmo nome é quase sempre engano; se for de propósito, o
    # caminho é editar o cargo que existe.
    existentes = {str(getattr(r, "name", "")).strip().casefold(): r
                  for r in getattr(guild, "roles", [])
                  if not getattr(r, "is_default", lambda: False)()}
    # Alvos que a MESMA mensagem vai apagar: recriar ("apague o cargo X e crie X de novo") não
    # é duplicata — Se não for isso, o "apague X" cairia num cargo que acabou de nascer.
    alvos_apagados = {str(a).strip().casefold() for a in (getattr(ctx, "alvos_apagados", None) or set())}
    pulados: list[str] = []

    def _vai_ser_apagado(nome: str, objeto: Any) -> bool:
        ident = str(getattr(objeto, "id", "")).strip().casefold()
        return nome.strip().casefold() in alvos_apagados or (ident and ident in alvos_apagados)

    async def _create_role_item(item: dict[str, Any]) -> str:
        name = str(item.get("name", "")).strip()
        if not name:
            raise ToolError("Todo cargo precisa de um nome.")
        chave = name.casefold()
        ja_existe = existentes.get(chave)
        if ja_existe is not None and not _vai_ser_apagado(name, ja_existe):
            pulados.append(name)
            return f"@{name} (já existia — não dupliquei)"
        # reserva ANTES do await: o lote é concorrente (3 por vez) e dois itens com o mesmo nome
        # passariam juntos pela conferência acima (era assim que nascia cargo duplicado)
        existentes[chave] = _NomeReservado()
        color_val = _parse_color(item.get("color"))
        hoist = bool(item.get("hoist", False))
        mentionable = bool(item.get("mentionable", False))
        # permissões podem vir na chamada (para todos) ou dentro de cada item do lote
        nomes = item.get("permissions", permissoes_globais) or []
        if isinstance(nomes, str):
            nomes = [p for p in re.split(r"[,\n;]+", nomes) if p.strip()]

        kwargs: dict[str, Any] = {"name": name, "hoist": hoist, "mentionable": mentionable}
        if color_val:
            kwargs["color"] = color_val
        if nomes:
            kwargs["permissions"] = Permissoes([str(p) for p in nomes])
        posicao_item = item.get("position", position)
        if posicao_item is not None:
            kwargs["position"] = int(posicao_item)

        creator = getattr(guild, "create_role", None)
        if not creator:
            raise ToolError("Servidor não suporta criação de cargos.")

        try:
            role_obj = await _criar_com_retentativa(creator, **kwargs)
        except BaseException:
            existentes.pop(chave, None)  # a criação falhou: libera o nome
            raise
        existentes[chave] = role_obj  # o lote não repete este nome nem que ele seja apagado
        rid = getattr(role_obj, "id", "")
        return f"<@&{rid}>" if rid else f"@{name}"

    res = await run_bulk(roles, _create_role_item, concurrency=3)
    if not res.succeeded and res.failed:
        err = res.failed[0][1]
        raise ToolError(f"Falha ao criar cargos: {err}")

    criados_de_verdade = max(0, len(res.succeeded) - len(pulados))
    created_roles = " ".join(r for r in res.succeeded if "(já existia" not in r)
    aviso_duplicado = ""
    if pulados:
        nomes_pulados = ", ".join(f"**{n}**" for n in pulados[:5])
        aviso_duplicado = (f" ⚠️ {len(pulados)} cargo(s) já existiam e eu NÃO dupliquei: "
                           f"{nomes_pulados} (se quiser mudar, me peça para editar o cargo).")

    # Honestidade: cargo criado nasce embaixo na hierarquia. Se o meu cargo mais alto estiver
    # no chão do servidor, eu crio mas NÃO consigo editar/apagar depois — o dono precisa saber
    # disso na hora (a matriz ao vivo pegou exatamente esse caso).
    aviso = ""
    posicao_bot = await _posicao_do_topo(ctx, getattr(guild, "me", None))
    if posicao_bot:
        pedidos = {str(r.get("name", "")).strip() for r in roles}
        criados_no_teto = [r for r in getattr(guild, "roles", [])
                           if getattr(r, "name", "") in pedidos
                           and getattr(r, "position", 0) >= posicao_bot]
        if criados_no_teto:
            aviso = (f" ⚠️ Meu cargo mais alto está na posição {posicao_bot}, e "
                     f"{len(criados_no_teto)} cargo(s) criado(s) ficaram nessa altura ou acima: "
                     "eu NÃO vou conseguir editá-los nem apagá-los (regra de hierarquia do "
                     "Discord). Suba o meu cargo se quiser gerenciá-los.")

    if not criados_de_verdade:
        return (f"Nenhum cargo novo criado.{aviso_duplicado}".strip())

    if permissoes_globais:
        nomes_txt = ", ".join(resolver_permissoes(permissoes_globais))
        return (f"Criei {criados_de_verdade} cargo(s) com as permissões [{nomes_txt}]: "
                f"{created_roles} ({res.summary()}).{aviso}{aviso_duplicado}")
    return (f"Criei {criados_de_verdade} cargo(s): {created_roles} ({res.summary()})."
            f"{aviso}{aviso_duplicado}")


async def op_edit_role(
    ctx: ToolContext,
    role: str,
    name: str | None = None,
    color: str | None = None,
    hoist: bool | None = None,
    mentionable: bool | None = None,
    permissions: list[str] | None = None,
    position: int | None = None,
) -> str:
    r_obj = resolve_role(ctx.guild, role)

    # Hierarquia (empate = tenta de verdade e traduz o que o Discord responder)
    pos_bot = await _posicao_do_topo(ctx, ctx.guild.me)
    empatado = await _exige_cargo_gerenciavel(ctx, "edit_role", r_obj, pos_bot=pos_bot)

    kwargs: dict[str, Any] = {}
    if name is not None:
        kwargs["name"] = name
    if color is not None:
        cor = _parse_color(color)
        if cor is None:
            raise ToolError(f"Cor '{color}' não é um hexadecimal válido (ex.: #5865F2).")
        kwargs["color"] = cor
    if hoist is not None:
        kwargs["hoist"] = hoist
    if mentionable is not None:
        kwargs["mentionable"] = mentionable
    if permissions is not None:
        # substitui o conjunto de permissões pelo pedido (nomes PT-BR ou EN)
        kwargs["permissions"] = Permissoes([str(p) for p in permissions])
    if position is not None:
        if int(position) < 0:
            raise ToolError("A posição do cargo não pode ser negativa.")
        kwargs["position"] = int(position)

    if not kwargs:
        raise ToolError(
            "Nada para editar: informe nome, cor, hoist, mentionable, permissions ou position."
        )

    editor = getattr(r_obj, "edit", None)
    if not editor:
        raise ToolError(f"Cargo '{role}' não pôde ser editado.")

    try:
        await editor(**kwargs)
    except Exception as exc:  # noqa: BLE001 - recusa do Discord: traduz e diz o que fazer
        if empatado:
            raise _recusa_do_discord(ctx, r_obj, exc, pos_bot, "editar") from exc
        raise
    rid = getattr(r_obj, "id", "")
    mudancas = ", ".join(sorted(kwargs))
    return f"Cargo <@&{rid}> atualizado com sucesso ({mudancas})."


def _nome_do_meu_cargo(ctx: ToolContext) -> str:
    """Nome do cargo mais alto do bot — é ele que o dono precisa arrastar para cima."""
    topo = getattr(getattr(ctx.guild, "me", None), "top_role", None)
    return str(getattr(topo, "name", "") or "atlas")


def _instrucao_hierarquia(pos_alvo: int | None, pos_bot: int, bot_name: str = "atlas") -> str:
    """
    O QUE fazer para o bot poder gerenciar o cargo — em português e com o caminho exato.

    Sem isso a resposta era só "não consigo apagar", e o dono do servidor ficava sem saber que a
    solução é subir o cargo do bot (regra de hierarquia do Discord).

    A DIREÇÃO da lista entrou depois do print do dono (18/09): no celular a tela de cargos é
    INVERTIDA em relação ao PC — o @everyone (o cargo mais fraco de todos) aparece primeiro e os
    cargos mais fortes ficam no fim. Quem lê "o bot está em 3º" naquele print está lendo o 3º mais
    FRACO. Dizer só "arraste para cima" faz o dono arrastar para o lado errado.
    """
    onde = (f"Hoje o meu está na posição {pos_bot} e esse aí na posição {pos_alvo}. "
            if pos_alvo is not None else f"Hoje o meu está na posição {pos_bot}. ")
    return (
        "O Discord só me deixa mexer em cargos ABAIXO do meu cargo mais alto (cargo mais alto = "
        "mais poder). " + onde +
        "Em **Configurações do Servidor → Cargos**, arraste o cargo "
        f"**{bot_name}** (o meu) para ficar ACIMA dos que você quer que eu gerencie. "
        "Atenção à direção da "
        "lista: no **PC** o mais forte fica no **topo**; no **celular** a lista é invertida (o "
        "@everyone aparece primeiro) e o mais forte fica no **fim** — é para lá que o meu cargo "
        "tem que ir. Depois me peça de novo."
    )


def _e_bloqueio_do_bot(mensagem: str) -> bool:
    """A recusa veio da hierarquia do MEU cargo (não da hierarquia do autor)."""
    return "do meu cargo mais alto" in mensagem


def _e_bloqueio_de_hierarquia(mensagem: str) -> bool:
    return _e_bloqueio_do_bot(mensagem) or "maior ou igual à do seu cargo mais alto" in mensagem


async def _exige_cargo_gerenciavel(
    ctx: ToolContext,
    ferramenta: str,
    cargo: Any,
    *,
    pos_bot: int | None = None,
    pos_actor: int | None = None,
) -> bool:
    """
    Confere permissões e hierarquia do cargo alvo; devolve True quando a MEDIÇÃO empatou.

    Empate (cargo na MESMA posição do meu topo) NÃO é recusa provada: o cache de posições
    pode estar velho e, acima de tudo, quem decide é o Discord. No empate devolvemos True
    para o chamador tentar de verdade e traduzir a resposta real. Recusa por posição
    rigorosamente ACIMA do meu topo continua bloqueada na hora, com o caminho da solução.

    Bug que isto corrige (relato do dono, 18/09): o teste ao vivo anotava "o Discord
    recusa" sem NUNCA ter perguntado ao Discord — a recusa era do nosso gate.

    Medição crua de 18/09 (scripts/sonda_hierarquia.py, falando direto com a API): pedir para
    pôr um cargo na MESMA posição do topo do bot não cria empate nenhum — o Discord o coloca
    logo ABAIXO (posição 26 quando o topo era 27). Ou seja, a regra que vale é a mesma que
    está aqui: estritamente abaixo. O empate só aparece com cache velho; nesse caso vale
    tentar, porque quem decide é a API.
    """
    bot_pos = pos_bot if pos_bot is not None else await _posicao_do_topo(ctx, ctx.guild.me)
    actor_pos = pos_actor if pos_actor is not None else await _posicao_do_topo(ctx, ctx.actor)
    try:
        require(ferramenta, ctx.actor.guild_permissions, ctx.guild.me.guild_permissions,
                actor=ctx.actor, bot_member=ctx.guild.me, guild=ctx.guild, target_role=cargo,
                bot_top_position=bot_pos, actor_top_position=actor_pos)
    except ToolError as exc:
        mensagem = str(exc)
        if not _e_bloqueio_de_hierarquia(mensagem):
            raise
        pos_alvo = int(getattr(cargo, "position", 0) or 0)
        if _e_bloqueio_do_bot(mensagem):
            if pos_alvo > bot_pos:
                raise ToolError(
                    f"{mensagem} {_instrucao_hierarquia(pos_alvo, bot_pos, _nome_do_meu_cargo(ctx))}"
                )
            return True  # mesma posição do meu topo: vale perguntar ao Discord
        if pos_alvo > (actor_pos or 0):
            raise  # acima do cargo de quem pediu: recusa clara, não é empate
        return True  # mesma posição do autor: idem, quem decide é o Discord
    return False


def _recusa_do_discord(ctx: ToolContext, cargo: Any, exc: Exception, pos_bot: int,
                       verbo: str) -> ToolError:
    """Traduz a recusa REAL do Discord (com o corpo do erro) e diz o que fazer."""
    nome = getattr(cargo, "name", "cargo")
    return ToolError(
        f"O Discord recusou {verbo} **{nome}** ({exc}). "
        f"{_instrucao_hierarquia(getattr(cargo, 'position', 0), pos_bot, _nome_do_meu_cargo(ctx))}"
    )


async def op_delete_role(
    ctx: ToolContext,
    role: str,
    confirmed: bool = False,
) -> str:
    r_obj = resolve_role(ctx.guild, role)

    pos_bot = await _posicao_do_topo(ctx, ctx.guild.me)
    empatado = await _exige_cargo_gerenciavel(ctx, "delete_role", r_obj, pos_bot=pos_bot)

    name = getattr(r_obj, "name", str(role))

    # Exclusão de cargo é destrutiva: pede confirmação só no modo cauteloso.
    if ctx.confirm_destructive and not confirmed:
        raise ToolError(
            f"Isso apaga o cargo **{name}** permanentemente — confirme com o usuário e chame de novo com confirmed=true."
        )

    deleter = getattr(r_obj, "delete", None)
    if not deleter:
        raise ToolError(f"Não foi possível excluir o cargo '{name}'.")

    try:
        await deleter()
    except Exception as exc:  # noqa: BLE001 - recusa do Discord: traduz e diz o que fazer
        if empatado:
            raise _recusa_do_discord(ctx, r_obj, exc, pos_bot, "apagar") from exc
        raise
    return f"🗑️ Cargo **{name}** excluído com sucesso."


async def op_delete_roles(
    ctx: ToolContext,
    roles: list[str],
    confirmed: bool = False,
) -> str:
    """
    Apaga VÁRIOS cargos de uma vez, dizendo com honestidade o que saiu e o que ficou de fora.

    Pedido comum ("apague todos os cargos") virava uma sequência de erros soltos: o modelo tentava
    um por um, cada um batia na hierarquia e o cliente ficava sem entender o que aconteceu nem o
    que fazer. Aqui: apaga o que dá, lista o que não dá (com o motivo) e explica o caminho para
    resolver — arrastar o cargo do bot para cima.
    """
    if not roles:
        raise ToolError("Nenhum cargo foi informado para exclusão.")

    guild = ctx.guild
    pos_bot = await _posicao_do_topo(ctx, guild.me)
    pos_actor = await _posicao_do_topo(ctx, ctx.actor)

    # Permissões de quem pediu e do bot: se faltar, é erro do pedido e vale avisar na hora.
    require("delete_roles", ctx.actor.guild_permissions, guild.me.guild_permissions,
            actor=ctx.actor, bot_member=guild.me, guild=guild)

    resolvidos: list[Any] = []
    bloqueados: list[tuple[str, str]] = []
    for query in roles:
        try:
            resolvidos.append(resolve_role(guild, str(query)))
        except ToolError as exc:
            bloqueados.append((str(query), str(exc)))

    # Confirmação só no modo cauteloso (igual à exclusão em lote de canais).
    if ctx.confirm_destructive and len(resolvidos) > 1 and not confirmed:
        nomes = ", ".join(f"**{getattr(r, 'name', '?')}**" for r in resolvidos[:8])
        raise ToolError(
            f"Isso apaga {len(resolvidos)} cargos ({nomes}) — confirme com o usuário e chame de "
            "novo com confirmed=true."
        )

    apagados: list[str] = []
    for r_obj in resolvidos:
        nome = getattr(r_obj, "name", "cargo")
        try:
            empatado = await _exige_cargo_gerenciavel(
                ctx, "delete_role", r_obj, pos_bot=pos_bot, pos_actor=pos_actor)
        except ToolError as exc:
            bloqueados.append((nome, str(exc)))
            continue

        deleter = getattr(r_obj, "delete", None)
        if not deleter:
            bloqueados.append((nome, "o objeto deste cargo não permite exclusão"))
            continue
        try:
            await deleter()
            apagados.append(nome)
        except Exception as exc:  # noqa: BLE001 - recusa do Discord
            if _e_bloqueio_de_hierarquia(str(exc)) or "Missing Permissions" in str(exc) or empatado:
                bloqueados.append((nome, _instrucao_hierarquia(getattr(r_obj, "position", 0),
                                                               pos_bot or 0,
                                                               _nome_do_meu_cargo(ctx))))
            else:
                bloqueados.append((nome, f"o Discord recusou: {exc}"))

    if not apagados and not bloqueados:
        raise ToolError("Não encontrei nenhum cargo com esses nomes.")

    partes: list[str] = []
    if apagados:
        partes.append(f"🗑️ Apaguei {len(apagados)} cargo(s): " + ", ".join(f"**{n}**" for n in apagados[:12])
                      + (" …" if len(apagados) > 12 else ""))
    if bloqueados:
        so_instrucao = all("Discord só me deixa" in m for _, m in bloqueados)
        resumo = (f"Não consegui apagar {len(bloqueados)} cargo(s) — todos estão no nível ou ACIMA "
                  f"do meu cargo (posição {pos_bot})."
                  if so_instrucao else
                  f"Não consegui apagar {len(bloqueados)} cargo(s): "
                  + "; ".join(f"**{n}** ({m})" for n, m in bloqueados[:6])
                  + (" …" if len(bloqueados) > 6 else ""))
        partes.append(resumo)
        if so_instrucao:
            partes.append(_instrucao_hierarquia(None, pos_bot or 0, _nome_do_meu_cargo(ctx)))
    if not apagados:
        partes.append("Nada foi apagado nesta rodada.")

    return " ".join(partes)


def _cargos_do_membro(membro: Any) -> set[int]:
    """
    IDs dos cargos de um membro.

    `Member.roles` é montado a partir do cache de cargos do servidor: se o cache estiver vazio,
    o discord.py simplesmente descarta os cargos e `top_role` cai no @everyone (posição 0).
    Aí os IDs crus do membro são a única pista — é o que permite conferir a hierarquia na API.
    """
    ids = {getattr(r, "id", None) for r in (getattr(membro, "roles", None) or [])}
    ids.discard(None)
    if not ids:
        ids = {i for i in (getattr(membro, "_roles", None) or []) if isinstance(i, int)}
    return ids


def _erro_transitorio(exc: Exception) -> bool:
    """
    Erro de infraestrutura do Discord (5xx), não de pedido ruim.

    A matriz ao vivo pegou `503 Service Unavailable — Service error -27` na criação de um cargo:
    o cargo não nasceu e as verificações seguintes caíram em cascata. Um 5xx do Discord significa
    que a ação NÃO foi executada, então vale uma segunda tentativa antes de desistir.
    """
    # Só 5xx CONFIRMADO (status na resposta). Antes havia também casamento por texto, e um
    # timeout ambíguo podia ser repetido — se a criação tivesse dado certo, repetir geraria
    # cargo/canal DUPLICADO (o dono do servidor viu cargos repetidos).
    status = getattr(exc, "status", None)
    return isinstance(status, int) and status >= 500


async def _com_retentativa(chamada: Any, *args: Any, **kwargs: Any) -> Any:
    """
    Executa a chamada; se o Discord responder 5xx, tenta UMA vez de novo.

    Vale para criar (cargo/canal/fórum) e para apagar em lote: um 5xx do Discord significa que a
    ação NÃO foi executada — foi o que fez o `clear_messages` "falhar" sem apagar nada.
    """
    try:
        return await chamada(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - só reenvia se for erro de infraestrutura
        if not _erro_transitorio(exc):
            raise
        logger.warning("Discord devolveu erro transitório (%s); tentando mais uma vez", exc)
        await asyncio.sleep(1.0)
        return await chamada(*args, **kwargs)


async def _criar_com_retentativa(criadora: Any, **kwargs: Any) -> Any:
    """Atalho para as criações (nome por extenso fica legível nos pontos de chamada)."""
    return await _com_retentativa(criadora, **kwargs)


async def _posicao_do_topo(ctx: ToolContext, membro: Any) -> int:
    """
    Posição do cargo mais alto de um membro, conferida na API quando o cache engana.

    Foi o que a matriz ao vivo pegou: o bot RECUSAVA editar um cargo que ele mesmo tinha
    acabado de criar, porque o cache de cargos do servidor estava vazio e `Member.top_role`
    respondia @everyone (posição 0) — "cargo acima ou na mesma posição do meu".
    """
    if membro is None:
        return 0
    topo = getattr(membro, "top_role", None)
    pos = getattr(topo, "position", None)
    resolvido = pos is not None and not getattr(topo, "is_default", lambda: False)()
    if resolvido and pos:
        return int(pos)

    busca = getattr(ctx.guild, "fetch_roles", None)
    if busca is not None:
        try:
            frescos = await busca()
        except Exception:  # noqa: BLE001 - na dúvida, fica com o que o cache disse
            frescos = []
        ids = _cargos_do_membro(membro)
        if frescos and ids:
            return max((int(getattr(r, "position", 0)) for r in frescos
                        if getattr(r, "id", None) in ids), default=int(pos or 0))
    return int(pos or 0)


async def _membro_do_servidor(ctx: ToolContext, query: str) -> Any:
    """
    Localiza um membro aceitando o cache local, mas caindo na API quando ele não está lá.

    Acontece quando a intent de membros está desligada no Developer Portal: o cache fica vazio e
    `resolve_member` não acha ninguém. Sem isso, dar/tirar cargo de um membro REAL falhava com
    "Membro '<id>' não foi encontrado no servidor" — foi o que a matriz ao vivo pegou.
    """
    try:
        return resolve_member(ctx.guild, query)
    except ToolError:
        texto = str(query).strip()
        achado = re.search(r"\d{5,}", texto)
        alvo_id = int(achado.group()) if achado else None
        busca = getattr(ctx.guild, "fetch_member", None)
        if alvo_id is not None and busca is not None:
            try:
                return await busca(alvo_id)
            except Exception as exc:  # noqa: BLE001 - sem membro na API, erro original abaixo
                raise ToolError(
                    f"Membro '{query}' não foi encontrado no servidor ({exc})."
                ) from exc
        raise


async def op_give_role(ctx: ToolContext, member: str, role: str) -> str:
    m_obj = await _membro_do_servidor(ctx, member)
    r_obj = resolve_role(ctx.guild, role)

    pos_bot = await _posicao_do_topo(ctx, ctx.guild.me)
    empatado = await _exige_cargo_gerenciavel(ctx, "give_role", r_obj, pos_bot=pos_bot)

    adder = getattr(m_obj, "add_roles", None)
    if not adder:
        raise ToolError("Não foi possível atribuir o cargo ao membro.")

    try:
        await adder(r_obj)
    except Exception as exc:  # noqa: BLE001 - recusa do Discord: traduz e diz o que fazer
        if empatado:
            raise _recusa_do_discord(ctx, r_obj, exc, pos_bot, "atribuir") from exc
        raise
    mid = getattr(m_obj, "id", "")
    rid = getattr(r_obj, "id", "")
    return f"Cargo <@&{rid}> atribuído a <@{mid}> com sucesso!"


async def op_take_role(ctx: ToolContext, member: str, role: str) -> str:
    m_obj = await _membro_do_servidor(ctx, member)
    r_obj = resolve_role(ctx.guild, role)

    pos_bot = await _posicao_do_topo(ctx, ctx.guild.me)
    empatado = await _exige_cargo_gerenciavel(ctx, "take_role", r_obj, pos_bot=pos_bot)

    remover = getattr(m_obj, "remove_roles", None)
    if not remover:
        raise ToolError("Não foi possível remover o cargo do membro.")

    try:
        await remover(r_obj)
    except Exception as exc:  # noqa: BLE001 - recusa do Discord: traduz e diz o que fazer
        if empatado:
            raise _recusa_do_discord(ctx, r_obj, exc, pos_bot, "tirar") from exc
        raise
    mid = getattr(m_obj, "id", "")
    rid = getattr(r_obj, "id", "")
    return f"Cargo <@&{rid}> removido de <@{mid}> com sucesso."


async def op_list_roles(ctx: ToolContext) -> str:
    roles = list(getattr(ctx.guild, "roles", []))
    if not roles:
        return "Nenhum cargo encontrado no servidor."

    sorted_roles = sorted(roles, key=lambda r: getattr(r, "position", 0), reverse=True)
    lines = ["**Cargos do Servidor:**"]
    for r in sorted_roles:
        r_id = getattr(r, "id", "")
        r_name = getattr(r, "name", "")
        members_count = len(getattr(r, "members", []))
        pos = getattr(r, "position", 0)
        lines.append(f"• <@&{r_id}> (**{r_name}** — posição {pos}, {members_count} membro(s))")

    return "\n".join(lines)


# --- 3. Permissões (4) ---

async def op_set_permissions(
    ctx: ToolContext,
    channel: str,
    target: str,
    allow: list[str] | None = None,
    deny: list[str] | None = None,
) -> str:
    ch = resolve_channel(ctx.guild, channel)

    # Identificar target como cargo ou membro
    target_obj = None
    try:
        target_obj = resolve_role(ctx.guild, target)
    except ToolError:
        target_obj = resolve_member(ctx.guild, target)

    overwriter = getattr(ch, "set_permissions", None)
    if not overwriter:
        raise ToolError(f"Canal '{channel}' não suporta configuração de permissões.")

    # Traduz PT-BR/acentos para os atributos do Discord antes de chegar na API: o
    # discord.py só aceita os nomes em inglês e estoura TypeError com qualquer outro.
    permitidas = resolver_permissoes(list(allow or []))
    negadas = resolver_permissoes(list(deny or []))
    conflito = [n for n in permitidas if n in negadas]
    if conflito:
        raise ToolError(
            "A mesma permissão não pode ser permitida e negada ao mesmo tempo: "
            + ", ".join(conflito)
            + ". Escolha um dos lados."
        )
    if not permitidas and not negadas:
        raise ToolError(
            "Diga o que permitir (allow) e/ou o que negar (deny) — "
            "ex.: allow=['ver canal'], deny=['enviar mensagens']."
        )

    perm_kwargs: dict[str, bool] = {n: True for n in permitidas}
    perm_kwargs.update({n: False for n in negadas})

    await overwriter(target_obj, **perm_kwargs)
    cid = getattr(ch, "id", "")
    tname = getattr(target_obj, "name", target)
    detalhe = []
    if permitidas:
        detalhe.append("✅ " + ", ".join(permitidas))
    if negadas:
        detalhe.append("🚫 " + ", ".join(negadas))
    return (f"Permissões atualizadas no canal <#{cid}> para **{tname}**: "
            + " | ".join(detalhe))


async def op_clear_permissions(ctx: ToolContext, channel: str, target: str) -> str:
    ch = resolve_channel(ctx.guild, channel)
    try:
        target_obj = resolve_role(ctx.guild, target)
    except ToolError:
        target_obj = resolve_member(ctx.guild, target)

    overwriter = getattr(ch, "set_permissions", None)
    if overwriter:
        await overwriter(target_obj, overwrite=None)
        cid = getattr(ch, "id", "")
        tname = getattr(target_obj, "name", target)
        return f"Permissões personalizadas removidas do canal <#{cid}> para **{tname}**."
    raise ToolError("Não foi possível limpar permissões do canal.")


async def op_sync_permissions(ctx: ToolContext, channel: str) -> str:
    ch = resolve_channel(ctx.guild, channel)
    editor = getattr(ch, "edit", None)
    if editor:
        await editor(sync_permissions=True)
        cid = getattr(ch, "id", "")
        return f"Permissões do canal <#{cid}> sincronizadas com a categoria com sucesso!"
    raise ToolError("Não foi possível sincronizar as permissões do canal.")


def _format_overwrite(ow: Any) -> str:
    """Traduz um PermissionOverwrite em algo legível (allow/deny/neutro)."""
    pair = getattr(ow, "pair", None)
    if pair is None:
        return str(ow)
    try:
        allow, deny = pair()
        allowed = [name for name, value in allow if value]
        denied = [name for name, value in deny if value]
    except Exception:  # noqa: BLE001 - objeto duck-typed sem iterador de permissões
        return str(ow)

    if not allowed and not denied:
        return "neutro (sem alterações)"
    parts = []
    if allowed:
        parts.append("✅ " + ", ".join(allowed))
    if denied:
        parts.append("🚫 " + ", ".join(denied))
    return " | ".join(parts)


async def _find_overwrite_entity(ctx: ToolContext, target: str) -> Any:
    """
    Aceita membro ou cargo como alvo (nome, ID ou menção).

    Se o cache local não tiver o membro (acontece quando a intent de membros está desligada
    no Developer Portal), busca direto na API pelo ID — foi assim que o teste ao vivo pegou
    `show_permissions(target=<id do dono>)` falhando.
    """
    erros: list[str] = []
    for resolver in (resolve_role, resolve_member):
        try:
            return resolver(ctx.guild, target)
        except Exception as exc:  # noqa: BLE001 - tenta o próximo resolvedor
            erros.append(str(exc))

    query = str(target).strip()
    alvo_id = int(query) if query.isdigit() else None
    if alvo_id is not None:
        for nome_busca in ("fetch_member", "fetch_role"):
            busca = getattr(ctx.guild, nome_busca, None)
            if busca is None:
                continue
            try:
                return await busca(alvo_id)
            except Exception as exc:  # noqa: BLE001 - tenta a próxima busca
                erros.append(f"{nome_busca}({alvo_id}): {exc}")

    raise ToolError(
        f"Não encontrei nenhum cargo ou membro chamado '{target}' no servidor. "
        f"({erros[0] if erros else ''})"
    )


async def _canal_sincronizado(guild: Any, ch: Any) -> Any:
    """
    Devolve o canal com o estado ATUAL do servidor.

    O objeto do cache local pode estar um instante atrás (ex.: uma permissão recém-criada),
    e aí `show_permissions` mostraria "não tem permissões personalizadas" logo depois de
    alguém configurá-las — foi o que o teste ao vivo pegou.
    """
    cid = getattr(ch, "id", None)
    fetcher = getattr(guild, "fetch_channel", None)
    if cid is None or fetcher is None:
        return ch
    try:
        atualizado = await fetcher(cid)
    except Exception:  # noqa: BLE001 - sem rede/permissão, segue com o cache
        return ch
    return atualizado if atualizado is not None else ch


async def op_show_permissions(
    ctx: ToolContext,
    channel: str,
    target: str | None = None,
) -> str:
    ch = await _canal_sincronizado(ctx.guild, resolve_channel(ctx.guild, channel))
    overwrites = getattr(ch, "overwrites", {})
    cid = getattr(ch, "id", "")

    if target:
        ent = await _find_overwrite_entity(ctx, target)
        ow = None
        for candidate, candidate_ow in overwrites.items():
            same_id = getattr(candidate, "id", None) is not None and getattr(candidate, "id", None) == getattr(ent, "id", None)
            same_name = getattr(candidate, "name", None) == getattr(ent, "name", None)
            if same_id or same_name:
                ow = candidate_ow
                break
        if ow is None:
            return f"O {getattr(ent, 'name', target)} não tem permissões personalizadas no canal <#{cid}> (herda as do servidor)."
        return f"**Permissões de {getattr(ent, 'name', target)} em <#{cid}>:**\n{_format_overwrite(ow)}"

    if not overwrites:
        return f"O canal <#{cid}> não possui permissões personalizadas configuradas."

    lines = [f"**Permissões configuradas no canal <#{cid}>:**"]
    for ent, ow in overwrites.items():
        name = getattr(ent, "name", str(ent))
        lines.append(f"- **{name}**: {_format_overwrite(ow)}")

    return "\n".join(lines)


# --- 4. Servidor (3) ---

async def op_edit_server(
    ctx: ToolContext,
    name: str | None = None,
    description: str | None = None,
) -> str:
    kwargs: dict[str, Any] = {}
    if name is not None:
        kwargs["name"] = name
    if description is not None:
        kwargs["description"] = description

    if not kwargs:
        raise ToolError("Nenhum dado informado para editar o servidor.")

    editor = getattr(ctx.guild, "edit", None)
    if editor:
        await editor(**kwargs)
        return "Informações do servidor atualizadas com sucesso!"
    raise ToolError("Servidor não suporta edição.")


def resumo_de_tempos(registros: Any) -> str:
    """
    Resumo honesto do tempo das últimas respostas — SÓ números, nunca conteúdo de conversa.

    É a resposta para "por que o bot demora?": separa o que foi gasto falando com o modelo do que
    foi gasto executando as ações no Discord.
    """
    amostras = [float(r.get("total", 0.0)) for r in (registros or [])]
    if not amostras:
        return ("Ainda não respondi nada nesta sessão do bot (nenhuma medida de tempo disponível). "
                "Me peça de novo depois de algumas tarefas.")
    llm = sorted(float(r.get("llm", 0.0)) for r in registros)
    ferr = sorted(float(r.get("ferramentas", 0.0)) for r in registros)

    def mediana(valores: list[float]) -> float:
        if not valores:
            return 0.0
        meio = len(valores) // 2
        if len(valores) % 2:
            return valores[meio]
        return (valores[meio - 1] + valores[meio]) / 2

    ordenadas = sorted(amostras)
    return (
        f"⏱️ **Tempo das últimas {len(amostras)} respostas**\n"
        f"• mediana: **{mediana(ordenadas):.1f}s** (melhor {ordenadas[0]:.1f}s, pior {ordenadas[-1]:.1f}s)\n"
        f"• falando com o modelo: {mediana(llm):.1f}s\n"
        f"• executando as ações no Discord: {mediana(ferr):.1f}s\n"
        "Se a mediana estiver alta, o gargalo é o modelo gratuito (fila/limite de uso) e não as "
        "ações — cadastrar mais chaves de provedores gratuitos deixa a resposta mais rápida."
    )


async def op_performance_report(ctx: ToolContext) -> str:
    return resumo_de_tempos(getattr(ctx, "tempos", None))


async def op_server_info(ctx: ToolContext) -> str:
    g = ctx.guild
    name = getattr(g, "name", "Servidor")
    gid = getattr(g, "id", "N/A")
    # `guild.owner` é None quando o membro não está no cache; aí aparecia "Dono: None".
    # O ID sempre existe e vira menção — melhor que um "None" mentiroso.
    owner_id = getattr(g, "owner_id", None)
    owner = f"<@{owner_id}>" if owner_id else getattr(g, "owner", None) or "N/A"
    # `member_count` é None quando o Discord não manda a contagem (sem intent de membros):
    # aparecia "Membros: None". Aí vale o tamanho do cache, e "?" se nem isso houver.
    members_count = (getattr(g, "member_count", None) or len(getattr(g, "members", [])) or "?")
    channels_count = len(getattr(g, "channels", []))
    roles_count = len(getattr(g, "roles", []))
    created_at = getattr(g, "created_at", "N/A")

    return (
        f"📊 **Informações de {name}:**\n"
        f"• **ID:** `{gid}`\n"
        f"• **Dono:** {owner}\n"
        f"• **Membros:** {members_count}\n"
        f"• **Canais:** {channels_count}\n"
        f"• **Cargos:** {roles_count}\n"
        f"• **Criado em:** {created_at}"
    )


MAX_ICON_BYTES = 8 * 1024 * 1024  # limite do Discord para ícones
ICON_STYLE_COLORS: dict[str, tuple[int, int, int]] = {
    "gamer": (124, 58, 237),
    "minimal": (17, 24, 39),
    "comunidade": (16, 185, 129),
    "estudos": (37, 99, 235),
    "neon": (236, 72, 153),
    "fofo": (244, 114, 182),
}
DEFAULT_ICON_COLOR = (88, 101, 242)


def _solid_png(rgb: tuple[int, int, int], size: int = 256) -> bytes:
    """Gera um PNG válido (gradiente vertical suave) sem dependências externas."""
    import struct
    import zlib

    base = bytes(rgb)
    light = bytes(min(255, int(c + (255 - c) * 0.45)) for c in rgb)

    def chunk(tag: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", crc)

    rows = bytearray()
    for y in range(size):
        mix = y / max(1, size - 1)
        row_color = bytes(int(base[i] + (light[i] - base[i]) * mix) for i in range(3))
        rows += b"\x00" + row_color * size

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )


def _decode_data_uri(url: str) -> bytes | None:
    """Aceita 'data:image/png;base64,...' (útil para testes e para o agente)."""
    if not url.lower().startswith("data:"):
        return None
    header, _, payload = url.partition(",")
    if not payload:
        raise ToolError("Data URI de imagem inválida (sem conteúdo).")
    if ";base64" not in header.lower():
        raise ToolError("Data URI de imagem precisa ser base64.")
    try:
        return base64.b64decode(payload, validate=True)
    except Exception as exc:  # noqa: BLE001 - mensagem amigável para o usuário
        raise ToolError(f"Data URI de imagem inválida: {exc}") from exc


async def _download_image(url: str) -> bytes:
    """Baixa a imagem da URL com limite de tamanho e checagem de tipo."""
    import aiohttp  # import tardio: mantém o módulo leve e testável sem rede

    timeout = aiohttp.ClientTimeout(total=20.0)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    raise ToolError(f"Não consegui baixar a imagem (HTTP {resp.status}): {url}")
                ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                data = await resp.read()
    except ToolError:
        raise
    except asyncio.TimeoutError as exc:
        raise ToolError(f"Tempo esgotado ao baixar a imagem: {url}") from exc
    except Exception as exc:  # noqa: BLE001 - erro de rede vira mensagem para o usuário
        raise ToolError(f"Falha ao baixar a imagem ({exc}): {url}") from exc

    if not data:
        raise ToolError(f"A imagem em {url} veio vazia.")
    if len(data) > MAX_ICON_BYTES:
        raise ToolError(
            f"A imagem tem {len(data) // 1024} KB e o Discord aceita no máximo "
            f"{MAX_ICON_BYTES // (1024 * 1024)} MB para ícone."
        )
    if ctype and not ctype.startswith("image/") and ctype not in (
        "application/octet-stream",
        "binary/octet-stream",
    ):
        raise ToolError(f"A URL não devolveu uma imagem (Content-Type: {ctype}).")
    return data


async def op_set_icon(
    ctx: ToolContext,
    url: str | None = None,
    style: str | None = None,
) -> str:
    """
    Altera o ícone do servidor de verdade.

    - `url` http(s) → baixa a imagem e envia os bytes para o Discord;
    - `url` data URI base64 → usa os bytes direto;
    - `style` → gera uma imagem local (sem rede) no tom daquele estilo.
    """
    editor = getattr(ctx.guild, "edit", None)
    if editor is None:
        raise ToolError("Não foi possível alterar o ícone do servidor.")

    if url:
        raw: bytes | None = _decode_data_uri(url)
        image = raw if raw is not None else await _download_image(url)
        origem = f"a partir de {url}" if raw is None else "a partir da imagem enviada"
    else:
        key = (style or "").strip().lower()
        color = ICON_STYLE_COLORS.get(key, DEFAULT_ICON_COLOR)
        image = _solid_png(color)
        origem = f"com o estilo '{key}'" if key else "com um estilo padrão"

    try:
        await editor(icon=image)
    except Exception as exc:  # noqa: BLE001 - erro do Discord vira mensagem clara
        raise ToolError(f"O Discord recusou o novo ícone: {exc}") from exc

    return f"Ícone do servidor atualizado com sucesso {origem}!"


# --- 5. Modelos (1) ---

TEMPLATES_DATA: dict[str, dict[str, Any]] = {
    "gamer": {
        "roles": [
            {"name": "Admin", "color": "#ED4245", "hoist": True},
            {"name": "Moderador", "color": "#5865F2", "hoist": True},
            {"name": "Streamer", "color": "#9B59B6", "hoist": True},
            {"name": "VIP", "color": "#F1C40F", "hoist": True},
            {"name": "Membro", "color": "#95A5A6", "hoist": False},
        ],
        "categories": [
            {
                "name": "📢 INFORMAÇÕES",
                "channels": [
                    {"name": "boas-vindas", "type": "text", "topic": "Boas-vindas aos novos membros!"},
                    {"name": "regras", "type": "text", "topic": "Regras da comunidade."},
                    {"name": "anúncios", "type": "text", "topic": "Novidades e avisos oficiais."},
                ],
            },
            {
                "name": "💬 COMUNIDADE",
                "channels": [
                    {"name": "geral", "type": "text", "topic": "Bate-papo geral da comunidade."},
                    {"name": "memes", "type": "text", "topic": "Espaço de memes e diversão."},
                    {"name": "setups", "type": "text", "topic": "Mostre seu setup gamer!"},
                ],
            },
            {
                "name": "🎮 JOGOS & VOZ",
                "channels": [
                    {"name": "procurar-grupo", "type": "text", "topic": "Encontre duo ou squad para jogar."},
                    {"name": "Lobby 1", "type": "voice"},
                    {"name": "Lobby 2", "type": "voice"},
                    {"name": "Squad", "type": "voice"},
                    {"name": "AFK", "type": "voice"},
                ],
            },
        ],
    },
    "estudos": {
        "roles": [
            {"name": "Professor / Monitor", "color": "#3498DB", "hoist": True},
            {"name": "Estudante", "color": "#2ECC71", "hoist": True},
        ],
        "categories": [
            {
                "name": "📚 BEM-VINDO",
                "channels": [
                    {"name": "apresentação", "type": "text"},
                    {"name": "avisos", "type": "text"},
                ],
            },
            {
                "name": "📝 DISCUSSÃO",
                "channels": [
                    {"name": "dúvidas", "type": "text"},
                    {"name": "materiais", "type": "text"},
                ],
            },
            {
                "name": "🎧 SALAS DE ESTUDO",
                "channels": [
                    {"name": "Silêncio (Pomodoro)", "type": "voice"},
                    {"name": "Estudo em Grupo", "type": "voice"},
                ],
            },
        ],
    },
    "comunidade": {
        "roles": [
            {"name": "Staff", "color": "#E67E22", "hoist": True},
            {"name": "Veterano", "color": "#9B59B6", "hoist": True},
            {"name": "Membro", "color": "#34495E", "hoist": False},
        ],
        "categories": [
            {
                "name": "🌐 GERAL",
                "channels": [
                    {"name": "regras", "type": "text"},
                    {"name": "bate-papo", "type": "text"},
                ],
            },
            {
                "name": "🎨 CRIATIVIDADE",
                "channels": [
                    {"name": "artes", "type": "text"},
                    {"name": "projetos", "type": "text"},
                ],
            },
            {
                "name": "🎙️ VOZ",
                "channels": [
                    {"name": "Conversa", "type": "voice"},
                    {"name": "Música", "type": "voice"},
                ],
            },
        ],
    },
}


async def op_apply_template(ctx: ToolContext, template: str) -> str:
    tpl_key = template.lower().strip()
    if tpl_key not in TEMPLATES_DATA:
        raise ToolError(f"Modelo '{template}' desconhecido. Escolha entre: gamer, estudos, comunidade.")

    tpl = TEMPLATES_DATA[tpl_key]
    guild = ctx.guild
    problemas: list[str] = []

    # 1. Cria cargos (um a um para saber exatamente o que falhou — resumo nunca mente)
    roles_created = 0
    for cargo in tpl["roles"]:
        try:
            await op_create_roles(ctx, [cargo])
            roles_created += 1
        except Exception as exc:  # noqa: BLE001 - segue aplicando e relata no fim
            problemas.append(f"cargo {cargo.get('name', '?')}: {exc}")

    # 2. Cria categorias e canais pelo MESMO caminho do create_channels
    #    (tipo respeitado de verdade; template com fórum/palco não vira texto calado)
    categories_created = 0
    channels_created = 0
    for cat_data in tpl["categories"]:
        cat_name = cat_data["name"]
        cat_creator = getattr(guild, "create_category", None)
        cat_obj = None
        if cat_creator:
            try:
                cat_obj = await cat_creator(name=cat_name)
                categories_created += 1
            except Exception as exc:  # noqa: BLE001
                problemas.append(f"categoria {cat_name}: {exc}")
                continue

        for ch_info in cat_data.get("channels", []):
            item = dict(ch_info)
            if cat_obj is not None:
                item["category"] = str(getattr(cat_obj, "id", ""))
            try:
                await _criar_canal_do_item(guild, item)
                channels_created += 1
            except Exception as exc:  # noqa: BLE001
                problemas.append(f"canal {ch_info.get('name', '?')}: {exc}")

    resumo = (f"✅ Modelo '{tpl_key}' aplicado com sucesso: {roles_created} cargo(s), "
              f"{categories_created} categoria(s) e {channels_created} canal(is) criados.")
    if problemas:
        resumo += (f" ⚠️ {len(problemas)} item(ns) NÃO foram criados: "
                   + "; ".join(problemas[:4]))
    return resumo


# --- 6. Backup (2) ---

class _NomeReservado:
    """
    Marca um nome que JÁ está sendo criado neste lote.

    O lote roda com concorrência 3 (`run_bulk`), então dois itens com o mesmo nome chegam juntos
    na criação: quem confere duplicata DEPOIS do `await` deixa os dois passarem (aconteceu no
    servidor do dono: uma chamada só criou 2 canais iguais). A reserva entra na lista ANTES do
    `await` e é trocada pelo objeto criado quando ele nasce.
    """

    def __init__(self, categoria: Any = None) -> None:
        self.id = None
        self.category = categoria


def _exportar_canal(ch: Any) -> dict[str, Any]:
    """Campos do canal que o import sabe recriar (tipo, tópico, nsfw, slowmode, bitrate...)."""
    info: dict[str, Any] = {
        "name": getattr(ch, "name", ""),
        "type": getattr(getattr(ch, "type", None), "name", "text"),
    }
    topic = getattr(ch, "topic", None)
    if topic:
        info["topic"] = topic
    if getattr(ch, "nsfw", False):
        info["nsfw"] = True
    slowmode = getattr(ch, "slowmode_delay", 0) or 0
    if slowmode:
        info["slowmode_delay"] = int(slowmode)
    bitrate = getattr(ch, "bitrate", None)
    if bitrate:
        info["bitrate"] = int(bitrate)
    limite = getattr(ch, "user_limit", None)
    if limite:
        info["user_limit"] = int(limite)
    if getattr(ch, "position", None) is not None:
        info["position"] = int(getattr(ch, "position"))
    return info


async def op_export_structure(ctx: ToolContext) -> str:
    guild = ctx.guild
    structure: dict[str, Any] = {
        "name": getattr(guild, "name", "Servidor"),
        "categories": [],
        "uncategorized_channels": [],
        "roles": [],
    }

    categorized_ids = set()
    for cat in getattr(guild, "categories", []):
        cat_info = {
            "name": getattr(cat, "name", ""),
            "channels": [],
        }
        for ch in getattr(cat, "channels", []):
            cid = getattr(ch, "id", None)
            categorized_ids.add(cid)
            cat_info["channels"].append(_exportar_canal(ch))
        structure["categories"].append(cat_info)

    for ch in getattr(guild, "channels", []):
        if getattr(ch, "id", None) not in categorized_ids and ch not in getattr(guild, "categories", []):
            structure["uncategorized_channels"].append(_exportar_canal(ch))

    for r in getattr(guild, "roles", []):
        if not getattr(r, "is_default", lambda: False)():
            # guarda TUDO que o create_roles sabe recriar (senão o import degrada o servidor)
            structure["roles"].append({
                "name": getattr(r, "name", ""),
                "color": "#%06x" % int(getattr(getattr(r, "color", None), "value", 0) or 0),
                "hoist": bool(getattr(r, "hoist", False)),
                "mentionable": bool(getattr(r, "mentionable", False)),
                "permissions": permissoes_do_cargo(r).nomes(),
                "position": getattr(r, "position", None),
            })

    # sem indentação o JSON fica ~40% menor e quase sempre cabe na mensagem do Discord; se
    # ainda não couber, o aviso é EXPLÍCITO (antes o JSON era cortado no meio, sem aviso, e o
    # resultado não podia ser importado de volta — a auditoria pegou isso no round-trip).
    dumped = json.dumps(structure, ensure_ascii=False, separators=(",", ":"))
    limite = 1800
    if len(dumped) <= limite:
        return f"📦 Estrutura exportada ({len(dumped)} caracteres):\n```json\n{dumped}\n```"
    partes = (len(dumped) + limite - 1) // limite
    n_canais = sum(len(c["channels"]) for c in structure["categories"])
    n_canais += len(structure["uncategorized_channels"])
    # O que fica FORA do recorte precisa ser dito: sem isso o dono não sabe se o export pegou os
    # cargos e as permissões (eles vêm depois dos canais no JSON e caem no corte).
    return (f"📦 Estrutura exportada, mas o JSON completo tem {len(dumped)} caracteres e não cabe "
            f"numa mensagem do Discord (limite ~2000; daria {partes} mensagens). No total, o "
            f"export guardou {n_canais} canal(is) em {len(structure['categories'])} categoria(s) e "
            f"{len(structure['roles'])} cargo(s) — cada cargo com as permissões, hoist e "
            f"mentionable dele. Aqui vão os primeiros {limite} caracteres para conferência "
            f"(os cargos ficam fora deste pedaço):\n```json\n{dumped[:limite]}\n```\n"
            "⚠️ **Este recorte NÃO serve para importar** (está cortado). Se o objetivo é "
            "backup/restauração, faça por partes (uma categoria por vez) — o Discord não aceita "
            "um JSON deste tamanho numa mensagem só.")


async def op_import_structure(ctx: ToolContext, structure_json: str | None = None) -> str:
    content = structure_json
    if not content and ctx.attachments:
        # Lê anexo
        att = ctx.attachments[0]
        reader = getattr(att, "read", None)
        if reader:
            bytes_data = await reader()
            content = bytes_data.decode("utf-8", errors="ignore")

    if not content:
        raise ToolError("Nenhum JSON de estrutura foi fornecido ou anexado à mensagem.")

    try:
        data = json.loads(content)
    except Exception as exc:
        raise ToolError(f"Arquivo ou JSON inválido: {exc}")

    roles_to_create = data.get("roles", [])
    total_roles = 0
    if roles_to_create:
        await op_create_roles(ctx, roles_to_create)
        total_roles = len(roles_to_create)

    canais_criados = 0
    problemas: list[str] = []

    async def _importar_canal(item: dict[str, Any], dentro_de: str | None = None) -> None:
        nonlocal canais_criados
        dados = dict(item)
        if dentro_de:
            dados["category"] = dentro_de
        try:
            await _criar_canal_do_item(ctx.guild, dados)
            canais_criados += 1
        except Exception as exc:  # noqa: BLE001 - segue importando o resto e relata no fim
            problemas.append(f"{item.get('name', '?')}: {exc}")

    # categorias (com os canais dentro) e, depois, os canais que estavam sem categoria
    for cat_data in data.get("categories", []):
        cat_name = cat_data.get("name", "Categoria")
        cat_creator = getattr(ctx.guild, "create_category", None)
        if cat_creator:
            await cat_creator(name=cat_name)
        for ch in cat_data.get("channels", []):
            await _importar_canal(ch, dentro_de=cat_name)

    for ch in data.get("uncategorized_channels", []):
        await _importar_canal(ch)

    resumo = (f"✅ Estrutura importada: {total_roles} cargo(s) e {canais_criados} canal(is) "
              "recriados com tipo, tópico, nsfw, slowmode, bitrate, limite de usuários e posição.")
    if problemas:
        resumo += f" ⚠️ {len(problemas)} item(ns) falharam: " + "; ".join(problemas[:3])
    return resumo


# --- 7. APIs (5) ---

async def op_color_palette(ctx: ToolContext, query: str = "gamer") -> str:
    registry = ctx.api_registry
    if registry:
        from apis.colors import fallback_color_palette, fetch_color_palette
        colors = await registry.execute("colors", fetch_color_palette, fallback_color_palette, query)
    else:
        from apis.colors import fallback_color_palette
        colors = fallback_color_palette(query)

    lines = [f"🎨 **Paleta temática '{query}':**"]
    for c in colors:
        lines.append(f"• `{c.get('hex')}` - **{c.get('name')}**")
    return "\n".join(lines)


async def op_color_name(ctx: ToolContext, hex_code: str) -> str:
    # HEX inválido devolvia "A cor `zzzz` é conhecida como **Cor #ZZZZ**" — inventar nome para
    # qualquer coisa não é resposta. Melhor recusar e mostrar o formato certo.
    limpo = str(hex_code or "").strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", limpo) and not re.fullmatch(r"[0-9a-fA-F]{3}", limpo):
        raise ToolError(
            f"'{hex_code}' não é um código HEX válido — use 6 dígitos, como #5865F2 "
            "(ou 3 dígitos, como #F0F)."
        )
    hex_code = f"#{limpo.upper()}"

    registry = ctx.api_registry
    if registry:
        from apis.colors import fallback_color_name, fetch_color_name
        name = await registry.execute("colors", fetch_color_name, fallback_color_name, hex_code)
    else:
        from apis.colors import fallback_color_name
        name = fallback_color_name(hex_code)

    return f"A cor `{hex_code}` é conhecida como **{name}**."


async def op_emoji_search(ctx: ToolContext, query: str) -> str:
    registry = ctx.api_registry
    if registry:
        from apis.emojis import fallback_emoji_search, fetch_emoji_search
        emojis = await registry.execute("emojis", fetch_emoji_search, fallback_emoji_search, query)
    else:
        from apis.emojis import fallback_emoji_search
        emojis = fallback_emoji_search(query)

    if not emojis:
        return f"Não encontrei emojis para '{query}'. Tente uma palavra mais simples (ex.: 'festa', 'jogo')."
    return f"Emojis encontrados para '{query}': {' '.join(emojis)}"


async def op_topic_suggest(ctx: ToolContext, category: str = "geral") -> str:
    registry = ctx.api_registry
    if registry:
        from apis.topics import fallback_topic_suggest, fetch_topic_suggest
        topic = await registry.execute("topics", fetch_topic_suggest, fallback_topic_suggest, category)
    else:
        from apis.topics import fallback_topic_suggest
        topic = fallback_topic_suggest(category)

    from apis.topics import TOPICS_BY_CATEGORY

    aviso = ""
    if str(category or "").strip().lower() not in TOPICS_BY_CATEGORY:
        aviso = f" (não conheço a categoria '{category}', usei o tom geral)"
    return f"Sugestão de tópico para canal de {category}{aviso}:\n> {topic}"


async def op_translate_text(ctx: ToolContext, text: str, target_lang: str = "pt") -> str:
    registry = ctx.api_registry
    if registry:
        from apis.translate import fallback_translate, fetch_translation
        translated = await registry.execute("translate", fetch_translation, fallback_translate, text, target_lang)
    else:
        from apis.translate import fallback_translate
        translated = fallback_translate(text, target_lang)

    original = str(text or "").strip()
    if not original:
        raise ToolError("Não há texto para traduzir.")

    traducao = str(translated or "").strip()
    if traducao == original and target_lang.lower() not in ("pt", "pt-br", "português", "portugues"):
        # o fallback dos tradutores devolve o PRÓPRIO texto: dizer "Tradução: <texto original>"
        # seria mentir para o usuário. Melhor avisar que o tradutor não respondeu.
        return (f"⚠️ Não consegui falar com o tradutor agora, então NÃO traduzi. "
                f"Texto original:\n> {original}")
    return f"Tradução: {traducao}"


# --- 8. Sessão (1) ---

async def op_diagnostic_report(ctx: ToolContext, limit: int = 80) -> str:
    """
    Manda por MENSAGEM DIRETA (só para quem pediu) um arquivo com a conversa recente do canal e o
    tempo das últimas respostas.

    Por que existe: para consertar "o bot demorou / tive que pedir várias vezes" é preciso ver a
    conversa de verdade. O log do GitHub Actions é PÚBLICO (o repositório é público), então o
    caminho é a DM: o conteúdo fica entre o bot e quem pediu — que já tem acesso ao canal — e pode
    ser repassado a quem dá suporte sem virar log público.
    """
    canal = ctx.channel
    historico = getattr(canal, "history", None)
    if not callable(historico):
        raise ToolError("Não consigo ler o histórico deste canal para montar o diagnóstico.")
    limite = max(1, min(int(limit or 80), 200))

    linhas: list[str] = []
    try:
        async for msg in historico(limit=limite):
            quando = getattr(msg, "created_at", None)
            autor = getattr(getattr(msg, "author", None), "display_name", None) or "?"
            eh_bot = bool(getattr(getattr(msg, "author", None), "bot", False))
            conteudo = str(getattr(msg, "content", "") or "").strip()
            if not conteudo and getattr(msg, "attachments", None):
                conteudo = "[anexo]"
            if len(conteudo) > 1500:
                conteudo = conteudo[:1500] + " …(cortado)"
            marca = "🐟 bot" if eh_bot else autor
            linhas.append(f"[{quando}] {marca}: {conteudo}")
    except Exception as exc:  # noqa: BLE001 - sem histórico, ainda vale o relatório de tempo
        linhas.append(f"(não consegui ler o histórico deste canal: {exc})")

    linhas.reverse()  # da mensagem mais antiga para a mais nova
    corpo = (
        "Atlas — diagnóstico da conversa\n"
        f"servidor: {getattr(ctx.guild, 'name', '?')} · canal: #{getattr(canal, 'name', '?')}\n"
        f"{resumo_de_tempos(getattr(ctx, 'tempos', None))}\n"
        "\n--- conversa (mais antiga primeiro) ---\n"
        + "\n".join(linhas)
    )

    # DM: só para quem pediu (já tem acesso a este canal).
    enviei = ""
    autor = ctx.actor
    if autor is not None and hasattr(autor, "send"):
        try:
            await autor.send(content="Aqui está o diagnóstico da nossa conversa (arquivo). "
                                     "Se puder, repasse para quem dá suporte ao Atlas.",
                             file=_arquivo_de_texto("atlas-diagnostico.txt", corpo))
            enviei = "Mandei o arquivo na sua **mensagem direta**"
        except Exception as exc:  # noqa: BLE001 - DM fechada/menor de idade: cai no canal
            logger.info("diagnóstico por DM falhou (%s); tentando no canal", exc)

    if not enviei:
        enviar = getattr(canal, "send", None)
        if callable(enviar):
            try:
                await enviar(file=_arquivo_de_texto("atlas-diagnostico.txt", corpo))
                enviei = "Não consegui abrir sua DM, então mandei o arquivo aqui no canal"
            except Exception as exc:  # noqa: BLE001
                raise ToolError(f"Não consegui entregar o diagnóstico: {exc}")
        else:
            raise ToolError("Não tenho como te enviar o arquivo do diagnóstico neste canal.")

    return (f"{enviei}: a conversa recente (até {limite} mensagens) com data/hora + o tempo das "
            f"últimas respostas ({resumo_de_tempos(getattr(ctx, 'tempos', None))}). "
            "É só repassar o arquivo.")


def _arquivo_de_texto(nome: str, conteudo: str) -> Any:
    """`discord.File` quando o discord.py está disponível; senão, um anexo simples."""
    try:
        import io

        import discord

        return discord.File(io.BytesIO(conteudo.encode("utf-8")), filename=nome)
    except Exception:  # noqa: BLE001 - testes/ambientes sem discord.py
        import types

        return types.SimpleNamespace(filename=nome, content=conteudo)


async def op_conversation_clear(ctx: ToolContext) -> str:
    """Limpa a MEMÓRIA do bot. Não toca nas mensagens do canal — a resposta diz isso."""
    havia = False
    if ctx.memory is not None:
        from brain.memory import memory_key

        cid = getattr(ctx.channel, "id", None)
        if cid is not None:
            # mesma chave usada pelo agente: servidor + canal (isolamento entre servidores)
            chave = memory_key(getattr(ctx.guild, "id", None), cid)
            havia = bool(ctx.memory.get_history(chave))
            ctx.memory.clear(chave)
    return (
        "🧹 Limpei a MINHA memória desta conversa (esqueci o que foi dito antes). "
        + ("Havia histórico guardado. " if havia else "Não havia nada guardado. ")
        + "As mensagens do canal continuam aí — se o pedido era apagá-las, use clear_messages."
    )


async def op_clear_messages(
    ctx: ToolContext,
    channel: str = "",
    limit: int = 50,
    confirmed: bool = False,
) -> str:
    """Apaga mensagens do canal DE VERDADE (bulk delete). Só relata o que apagou."""
    alvo = resolve_channel(ctx.guild, channel) if channel else ctx.channel
    if alvo is None:
        raise ToolError(f"Canal '{channel}' não encontrado para limpar as mensagens.")

    require("clear_messages", ctx.actor.guild_permissions, ctx.guild.me.guild_permissions,
            actor=ctx.actor, bot_member=ctx.guild.me, guild=ctx.guild)

    try:
        quantas = int(limit)
    except (TypeError, ValueError):
        raise ToolError(f"O limite precisa ser um número inteiro entre 1 e {MAX_PURGE_MESSAGES} "
                        f"(recebi {limit!r}).")
    if quantas < 1 or quantas > MAX_PURGE_MESSAGES:
        raise ToolError(f"O limite precisa estar entre 1 e {MAX_PURGE_MESSAGES} (recebi {quantas}).")

    if ctx.confirm_destructive and not confirmed:
        raise ToolError(
            f"Isso apaga até {quantas} mensagem(ns) de {getattr(alvo, 'name', 'canal')} — "
            "confirme com o usuário e chame de novo com confirmed=true."
        )

    purger = getattr(alvo, "purge", None)
    if callable(purger):
        apagadas = await _com_retentativa(purger, limit=quantas)
        total = len(apagadas) if hasattr(apagadas, "__len__") else quantas
    else:
        history = getattr(alvo, "history", None)
        if not callable(history):
            raise ToolError(
                f"Não consigo listar mensagens de '{getattr(alvo, 'name', 'canal')}' "
                "(o canal não expõe histórico nem purge)."
            )
        total = 0
        async for mensagem in history(limit=quantas):
            deleter = getattr(mensagem, "delete", None)
            if callable(deleter):
                await deleter()
                total += 1

    nome = getattr(alvo, "name", "canal")
    if total == 0:
        return f"🧹 Não havia mensagens para apagar em #{nome}."

    # O bulk delete do Discord IGNORA mensagens com mais de 14 dias. Dizer "o chat está limpo"
    # com mensagens antigas ainda ali seria mentira — então a resposta confere e avisa.
    sobrou_antiga = False
    historico = getattr(alvo, "history", None)
    if callable(historico):
        try:
            async for _antiga in historico(limit=1, oldest_first=True):
                sobrou_antiga = True
                break
        except Exception:  # noqa: BLE001 - se não der para conferir, não afirma nada
            sobrou_antiga = False

    if sobrou_antiga:
        return (f"🗑️ Apaguei {total} mensagem(ns) em #{nome}. Ainda SOBRARAM mensagens antigas: "
                "o Discord não apaga em lote nada com mais de 14 dias (só uma a uma).")
    return f"🗑️ Apaguei {total} mensagem(ns) em #{nome}. O chat está limpo."
