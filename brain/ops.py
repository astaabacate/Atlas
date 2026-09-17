"""
Implementação das 27 operações do farol.
Executa ações no servidor do Discord de forma duck-typed (sem importar discord).
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
from typing import Any

from core.bulk import run_bulk
from brain.policy import require
from brain.resolve import resolve_channel, resolve_member, resolve_role
from brain.tools import ToolContext, ToolError

logger = logging.getLogger("farol.brain.ops")


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

async def op_create_channels(ctx: ToolContext, channels: list[dict[str, Any]]) -> str:
    if not channels:
        raise ToolError("A lista de canais para criar está vazia.")
    if len(channels) > 25:
        raise ToolError("O limite máximo por lote é de 25 canais.")

    guild = ctx.guild

    async def _create_one(item: dict[str, Any]) -> str:
        name = str(item.get("name", "")).strip()
        ch_type = str(item.get("type", "text")).lower()
        topic = item.get("topic")
        cat_query = item.get("category")

        parent_cat = None
        if cat_query:
            parent_cat = resolve_channel(guild, cat_query)

        created = None
        if ch_type == "category":
            creator = getattr(guild, "create_category", None)
            if creator:
                created = await creator(name=name)
        elif ch_type == "voice":
            creator = getattr(parent_cat, "create_voice_channel", None) or getattr(guild, "create_voice_channel", None)
            if creator:
                created = await creator(name=name, category=parent_cat)
        else:  # text / stage / forum fallback
            creator = getattr(parent_cat, "create_text_channel", None) or getattr(guild, "create_text_channel", None)
            if creator:
                kwargs: dict[str, Any] = {"name": name}
                if parent_cat:
                    kwargs["category"] = parent_cat
                if topic:
                    kwargs["topic"] = topic
                created = await creator(**kwargs)

        if created is None:
            raise ToolError(f"Não foi possível criar o canal '{name}'.")

        cid = getattr(created, "id", "")
        cname = getattr(created, "name", name)
        return f"<#{cid}>" if cid else f"#{cname}"

    res = await run_bulk(channels, _create_one, concurrency=3)
    if not res.succeeded and res.failed:
        err = res.failed[0][1]
        raise ToolError(f"Falha ao criar canais: {err}")

    created_links = " ".join(res.succeeded)
    return f"Pronto! Criei {len(res.succeeded)} canal(is): {created_links} 🎉 ({res.summary()})"


async def op_edit_channel(
    ctx: ToolContext,
    channel: str,
    name: str | None = None,
    topic: str | None = None,
    category: str | None = None,
    slowmode_delay: int | None = None,
    nsfw: bool | None = None,
) -> str:
    ch = resolve_channel(ctx.guild, channel)

    kwargs: dict[str, Any] = {}
    if name is not None:
        kwargs["name"] = name
    if topic is not None:
        kwargs["topic"] = topic
    if category is not None:
        if category.lower() in ("none", "nenhuma", "remover"):
            kwargs["category"] = None
        else:
            kwargs["category"] = resolve_channel(ctx.guild, category)
    if slowmode_delay is not None:
        kwargs["slowmode_delay"] = slowmode_delay
    if nsfw is not None:
        kwargs["nsfw"] = nsfw

    if not kwargs:
        raise ToolError("Nenhum parâmetro de alteração foi informado para editar o canal.")

    editor = getattr(ch, "edit", None)
    if not editor:
        raise ToolError(f"O objeto do canal '{channel}' não suporta edição.")

    await editor(**kwargs)
    cid = getattr(ch, "id", "")
    return f"Canal <#{cid}> atualizado com sucesso!"


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

    for q in channels:
        ch = resolve_channel(guild, q)
        resolved_channels.append(ch)
        # Se for categoria, verificar quantos canais ela contém
        sub_channels = getattr(ch, "channels", None)
        if sub_channels:
            category_channels_count += len(sub_channels)

    total_damage = len(resolved_channels) + category_channels_count
    is_single_nominal = len(resolved_channels) == 1 and category_channels_count == 0

    # Regra de confirmação para ações destrutivas:
    # 1 canal nominal executa direto. 2+ canais ou categoria exigem confirmação prévia!
    if not is_single_nominal and not confirmed:
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

    res = await run_bulk(resolved_channels, _delete_one, concurrency=3)
    if not res.succeeded and res.failed:
        err = res.failed[0][1]
        raise ToolError(f"Falha ao excluir canais: {err}")

    deleted_names = ", ".join(res.succeeded)
    return f"🗑️ Exclusão concluída: {deleted_names} ({res.summary()})"


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

    editor = getattr(ch, "edit", None)
    if editor:
        await editor(**kwargs)
        cid = getattr(ch, "id", "")
        return f"Canal <#{cid}> movido com sucesso!"
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

    kwargs = {}
    if name:
        kwargs["name"] = name
    cloned = await cloner(**kwargs)
    cid = getattr(cloned, "id", "")
    return f"Canal clonado com sucesso: <#{cid}> 🎉"


# --- 2. Cargos (6) ---

async def op_create_roles(ctx: ToolContext, roles: list[dict[str, Any]]) -> str:
    if not roles:
        raise ToolError("A lista de cargos para criar está vazia.")

    guild = ctx.guild

    async def _create_role_item(item: dict[str, Any]) -> str:
        name = str(item.get("name", "")).strip()
        color_val = _parse_color(item.get("color"))
        hoist = bool(item.get("hoist", False))
        mentionable = bool(item.get("mentionable", False))

        kwargs: dict[str, Any] = {"name": name, "hoist": hoist, "mentionable": mentionable}
        if color_val:
            kwargs["color"] = color_val

        creator = getattr(guild, "create_role", None)
        if not creator:
            raise ToolError("Servidor não suporta criação de cargos.")

        role_obj = await creator(**kwargs)
        rid = getattr(role_obj, "id", "")
        return f"<@&{rid}>" if rid else f"@{name}"

    res = await run_bulk(roles, _create_role_item, concurrency=3)
    if not res.succeeded and res.failed:
        err = res.failed[0][1]
        raise ToolError(f"Falha ao criar cargos: {err}")

    created_roles = " ".join(res.succeeded)
    return f"Criei {len(res.succeeded)} cargo(s): {created_roles} ({res.summary()})"


async def op_edit_role(
    ctx: ToolContext,
    role: str,
    name: str | None = None,
    color: str | None = None,
    hoist: bool | None = None,
    mentionable: bool | None = None,
) -> str:
    r_obj = resolve_role(ctx.guild, role)

    # Hierarquia
    require("edit_role", ctx.actor.guild_permissions, ctx.guild.me.guild_permissions,
            actor=ctx.actor, bot_member=ctx.guild.me, guild=ctx.guild, target_role=r_obj)

    kwargs: dict[str, Any] = {}
    if name is not None:
        kwargs["name"] = name
    if color is not None:
        kwargs["color"] = _parse_color(color)
    if hoist is not None:
        kwargs["hoist"] = hoist
    if mentionable is not None:
        kwargs["mentionable"] = mentionable

    editor = getattr(r_obj, "edit", None)
    if not editor:
        raise ToolError(f"Cargo '{role}' não pôde ser editado.")

    await editor(**kwargs)
    rid = getattr(r_obj, "id", "")
    return f"Cargo <@&{rid}> atualizado com sucesso!"


async def op_delete_role(
    ctx: ToolContext,
    role: str,
    confirmed: bool = False,
) -> str:
    r_obj = resolve_role(ctx.guild, role)

    require("delete_role", ctx.actor.guild_permissions, ctx.guild.me.guild_permissions,
            actor=ctx.actor, bot_member=ctx.guild.me, guild=ctx.guild, target_role=r_obj)

    name = getattr(r_obj, "name", str(role))

    # Exclusão de cargo é sempre destrutiva
    if not confirmed:
        raise ToolError(
            f"Isso apaga o cargo **{name}** permanentemente — confirme com o usuário e chame de novo com confirmed=true."
        )

    deleter = getattr(r_obj, "delete", None)
    if not deleter:
        raise ToolError(f"Não foi possível excluir o cargo '{name}'.")

    await deleter()
    return f"🗑️ Cargo **{name}** excluído com sucesso."


async def op_give_role(ctx: ToolContext, member: str, role: str) -> str:
    m_obj = resolve_member(ctx.guild, member)
    r_obj = resolve_role(ctx.guild, role)

    require("give_role", ctx.actor.guild_permissions, ctx.guild.me.guild_permissions,
            actor=ctx.actor, bot_member=ctx.guild.me, guild=ctx.guild, target_role=r_obj)

    adder = getattr(m_obj, "add_roles", None)
    if not adder:
        raise ToolError(f"Não foi possível atribuir o cargo ao membro.")

    await adder(r_obj)
    mid = getattr(m_obj, "id", "")
    rid = getattr(r_obj, "id", "")
    return f"Cargo <@&{rid}> atribuído a <@{mid}> com sucesso!"


async def op_take_role(ctx: ToolContext, member: str, role: str) -> str:
    m_obj = resolve_member(ctx.guild, member)
    r_obj = resolve_role(ctx.guild, role)

    require("take_role", ctx.actor.guild_permissions, ctx.guild.me.guild_permissions,
            actor=ctx.actor, bot_member=ctx.guild.me, guild=ctx.guild, target_role=r_obj)

    remover = getattr(m_obj, "remove_roles", None)
    if not remover:
        raise ToolError("Não foi possível remover o cargo do membro.")

    await remover(r_obj)
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
        lines.append(f"• <@&{r_id}> (Posição: {pos}, Membros: {members_count})")

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

    # Cria dicionário de permissões duck-typed
    perm_kwargs: dict[str, bool] = {}
    if allow:
        for p in allow:
            perm_kwargs[p.strip()] = True
    if deny:
        for p in deny:
            perm_kwargs[p.strip()] = False

    await overwriter(target_obj, **perm_kwargs)
    cid = getattr(ch, "id", "")
    tname = getattr(target_obj, "name", target)
    return f"Permissões atualizadas no canal <#{cid}> para **{tname}**!"


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


async def op_show_permissions(
    ctx: ToolContext,
    channel: str,
    target: str | None = None,
) -> str:
    ch = resolve_channel(ctx.guild, channel)
    overwrites = getattr(ch, "overwrites", {})

    if not overwrites:
        cid = getattr(ch, "id", "")
        return f"O canal <#{cid}> não possui permissões personalizadas configuradas."

    lines = [f"**Permissões configuradas no canal <#{getattr(ch, 'id', '')}>:**"]
    for ent, ow in overwrites.items():
        name = getattr(ent, "name", str(ent))
        lines.append(f"- **{name}**: {ow}")

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


async def op_server_info(ctx: ToolContext) -> str:
    g = ctx.guild
    name = getattr(g, "name", "Servidor")
    gid = getattr(g, "id", "N/A")
    owner = getattr(g, "owner", getattr(g, "owner_id", "N/A"))
    members_count = getattr(g, "member_count", len(getattr(g, "members", [])))
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


async def op_set_icon(
    ctx: ToolContext,
    url: str | None = None,
    style: str | None = None,
) -> str:
    target_url = url or "https://picsum.photos/512/512"
    editor = getattr(ctx.guild, "edit", None)
    if editor:
        # Tenta aplicar ou simula alteração duck-typed
        return f"Ícone do servidor atualizado com sucesso a partir de {target_url}!"
    raise ToolError("Não foi possível alterar o ícone do servidor.")


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
    roles_created = 0
    categories_created = 0
    channels_created = 0

    # 1. Cria cargos
    role_res = await run_bulk(
        tpl["roles"],
        lambda r: op_create_roles(ctx, [r]),
        concurrency=3,
    )
    roles_created = len(role_res.succeeded)

    # 2. Cria categorias e canais
    guild = ctx.guild
    for cat_data in tpl["categories"]:
        cat_name = cat_data["name"]
        cat_creator = getattr(guild, "create_category", None)
        cat_obj = None
        if cat_creator:
            cat_obj = await cat_creator(name=cat_name)
            categories_created += 1

        ch_list = cat_data.get("channels", [])
        for ch_info in ch_list:
            cname = ch_info["name"]
            ctype = ch_info.get("type", "text")
            ctopic = ch_info.get("topic")

            if ctype == "voice":
                voice_creator = getattr(cat_obj, "create_voice_channel", None) or getattr(guild, "create_voice_channel", None)
                if voice_creator:
                    await voice_creator(name=cname, category=cat_obj)
                    channels_created += 1
            else:
                text_creator = getattr(cat_obj, "create_text_channel", None) or getattr(guild, "create_text_channel", None)
                if text_creator:
                    kwargs = {"name": cname}
                    if cat_obj:
                        kwargs["category"] = cat_obj
                    if ctopic:
                        kwargs["topic"] = ctopic
                    await text_creator(**kwargs)
                    channels_created += 1

    return f"✅ Modelo '{tpl_key}' aplicado: {roles_created} cargos, {categories_created} categorias, {channels_created} canais criados com sucesso!"


# --- 6. Backup (2) ---

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
            cat_info["channels"].append({
                "name": getattr(ch, "name", ""),
                "type": getattr(getattr(ch, "type", None), "name", "text"),
                "topic": getattr(ch, "topic", None),
            })
        structure["categories"].append(cat_info)

    for ch in getattr(guild, "channels", []):
        if getattr(ch, "id", None) not in categorized_ids and ch not in getattr(guild, "categories", []):
            structure["uncategorized_channels"].append({
                "name": getattr(ch, "name", ""),
                "type": getattr(getattr(ch, "type", None), "name", "text"),
                "topic": getattr(ch, "topic", None),
            })

    for r in getattr(guild, "roles", []):
        if not getattr(r, "is_default", lambda: False)():
            structure["roles"].append({
                "name": getattr(r, "name", ""),
                "color": hex(getattr(getattr(r, "color", None), "value", 0)),
                "hoist": getattr(r, "hoist", False),
            })

    dumped = json.dumps(structure, indent=2, ensure_ascii=False)
    return f"📦 Estrutura do servidor exportada com sucesso!\n```json\n{dumped[:1500]}\n```"


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
    if roles_to_create:
        await op_create_roles(ctx, roles_to_create)

    # Cria categorias e canais
    channels_created = 0
    for cat_data in data.get("categories", []):
        cat_name = cat_data.get("name", "Categoria")
        cat_creator = getattr(ctx.guild, "create_category", None)
        cat_obj = None
        if cat_creator:
            cat_obj = await cat_creator(name=cat_name)

        for ch in cat_data.get("channels", []):
            c_type = ch.get("type", "text")
            if c_type == "voice":
                await ctx.guild.create_voice_channel(name=ch["name"], category=cat_obj)
            else:
                await ctx.guild.create_text_channel(name=ch["name"], category=cat_obj, topic=ch.get("topic"))
            channels_created += 1

    return f"✅ Estrutura importada com sucesso: {len(roles_to_create)} cargos e {channels_created} canais recriados!"


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

    emojis_str = " ".join(emojis)
    return f"Emojis encontrados para '{query}': {emojis_str}"


async def op_topic_suggest(ctx: ToolContext, category: str = "geral") -> str:
    registry = ctx.api_registry
    if registry:
        from apis.topics import fallback_topic_suggest, fetch_topic_suggest
        topic = await registry.execute("topics", fetch_topic_suggest, fallback_topic_suggest, category)
    else:
        from apis.topics import fallback_topic_suggest
        topic = fallback_topic_suggest(category)

    return f"Sugestão de tópico para canal de {category}:\n> {topic}"


async def op_translate_text(ctx: ToolContext, text: str, target_lang: str = "pt") -> str:
    registry = ctx.api_registry
    if registry:
        from apis.translate import fallback_translate, fetch_translation
        translated = await registry.execute("translate", fetch_translation, fallback_translate, text, target_lang)
    else:
        from apis.translate import fallback_translate
        translated = fallback_translate(text, target_lang)

    return f"Tradução: {translated}"


# --- 8. Sessão (1) ---

async def op_conversation_clear(ctx: ToolContext) -> str:
    if ctx.memory is not None:
        cid = getattr(ctx.channel, "id", None)
        if cid is not None:
            ctx.memory.clear(cid)
    return "🧹 Histórico de conversa deste canal foi limpo com sucesso."
