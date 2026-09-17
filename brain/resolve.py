"""
Resolução de referências de canais, cargos e membros no servidor.
Aceita menções (<#id>, <@&id>, <@id>), IDs numéricos ou nomes (exatos ou parciais).
NÃO importa discord (duck-typing estrito).
"""

from __future__ import annotations

import re
from typing import Any

from brain.tools import ToolError


def _extract_id(query: str) -> int | None:
    q = query.strip()
    # Menções: <#123>, <@&123>, <@!123>, <@123>
    match = re.search(r"<[@#]&?!?(\d+)>", q)
    if match:
        return int(match.group(1))
    if q.isdigit():
        return int(q)
    return None


def _clean_name(name: str) -> str:
    # Remove hashtags, arrobas e espaços
    cleaned = re.sub(r"^[#@\s]+", "", name).strip().lower()
    return cleaned


def resolve_channel(guild: Any, query: str, channel_type: str | None = None) -> Any:
    """Localiza um canal ou categoria por ID, menção ou nome."""
    q = str(query).strip()
    target_id = _extract_id(q)

    channels = list(getattr(guild, "channels", []))
    # Incluir categorias se estiverem separadas
    categories = list(getattr(guild, "categories", []))
    all_channels = channels + [c for c in categories if c not in channels]

    # 1. Busca por ID
    if target_id is not None:
        for ch in all_channels:
            if getattr(ch, "id", None) == target_id:
                return ch
        # Fallback para get_channel
        getter = getattr(guild, "get_channel", None)
        if getter:
            ch = getter(target_id)
            if ch:
                return ch

    # 2. Busca exata por nome (case-insensitive)
    q_lower = q.lower()
    clean_q = _clean_name(q)

    for ch in all_channels:
        name = getattr(ch, "name", "").lower()
        if name == q_lower or _clean_name(name) == clean_q:
            return ch

    # 3. Busca por "contém"
    for ch in all_channels:
        name = getattr(ch, "name", "").lower()
        if clean_q and (clean_q in name or name in clean_q):
            return ch

    raise ToolError(f"Canal ou categoria '{query}' não foi encontrado no servidor.")


def resolve_role(guild: Any, query: str) -> Any:
    """Localiza um cargo por ID, menção (<@&id>) ou nome."""
    q = str(query).strip()
    target_id = _extract_id(q)

    roles = list(getattr(guild, "roles", []))

    # 1. Busca por ID
    if target_id is not None:
        for r in roles:
            if getattr(r, "id", None) == target_id:
                return r
        getter = getattr(guild, "get_role", None)
        if getter:
            r = getter(target_id)
            if r:
                return r

    # 2. Busca exata por nome
    q_lower = q.lower()
    clean_q = _clean_name(q)

    for r in roles:
        name = getattr(r, "name", "").lower()
        if name == q_lower or _clean_name(name) == clean_q:
            return r

    # 3. Busca por "contém"
    for r in roles:
        name = getattr(r, "name", "").lower()
        if clean_q and (clean_q in name or name in clean_q):
            return r

    raise ToolError(f"Cargo '{query}' não foi encontrado no servidor.")


def resolve_member(guild: Any, query: str) -> Any:
    """Localiza um membro do servidor por ID, menção (<@id>) ou nome."""
    q = str(query).strip()
    target_id = _extract_id(q)

    members = list(getattr(guild, "members", []))

    # 1. Busca por ID
    if target_id is not None:
        for m in members:
            if getattr(m, "id", None) == target_id:
                return m
        getter = getattr(guild, "get_member", None)
        if getter:
            m = getter(target_id)
            if m:
                return m

    # 2. Busca por nome / nick
    q_lower = q.lower()
    clean_q = _clean_name(q)

    for m in members:
        name = getattr(m, "name", "").lower()
        nick = (getattr(m, "nick", "") or "").lower()
        display_name = getattr(m, "display_name", "").lower()

        if q_lower in (name, nick, display_name) or clean_q in (_clean_name(name), _clean_name(nick), _clean_name(display_name)):
            return m

    # 3. Busca por "contém"
    for m in members:
        display_name = getattr(m, "display_name", "").lower()
        if clean_q and clean_q in display_name:
            return m

    raise ToolError(f"Membro '{query}' não foi encontrado no servidor.")
