"""
Snapshot da estrutura atual do servidor para injeção no prompt de sistema.
NÃO importa discord (duck-typing estrito).
"""

from __future__ import annotations

from typing import Any


def build_server_snapshot(guild: Any) -> str:
    """
    Gera um resumo em texto da estrutura real de canais e cargos do servidor.
    O LLM usa isso para nunca inventar IDs ou nomes.
    """
    if guild is None:
        return "Estrutura do servidor indisponível."

    guild_name = getattr(guild, "name", "Servidor")
    guild_id = getattr(guild, "id", "")

    lines: list[str] = [f"ESTRUTURA ATUAL DO SERVIDOR '{guild_name}' (ID: {guild_id}):"]

    # Categorias e canais
    categories = list(getattr(guild, "categories", []))
    all_channels = list(getattr(guild, "channels", []))

    if categories:
        lines.append("\nCATEGORIAS E CANAIS:")
        categorized_channel_ids = set()
        for cat in sorted(categories, key=lambda c: getattr(c, "position", 0)):
            cat_name = getattr(cat, "name", "")
            cat_id = getattr(cat, "id", "")
            lines.append(f"- 📁 [Categoria] {cat_name} (ID: {cat_id})")

            cat_channels = getattr(cat, "channels", [])
            for ch in sorted(cat_channels, key=lambda c: getattr(c, "position", 0)):
                ch_id = getattr(ch, "id", "")
                ch_name = getattr(ch, "name", "")
                ch_type = getattr(getattr(ch, "type", None), "name", "channel")
                categorized_channel_ids.add(ch_id)
                lines.append(f"  - #{ch_name} (tipo: {ch_type}, ID: {ch_id})")

        # Canais sem categoria
        uncategorized = [ch for ch in all_channels if getattr(ch, "id", None) not in categorized_channel_ids and ch not in categories]
        if uncategorized:
            lines.append("- [Sem categoria]:")
            for ch in sorted(uncategorized, key=lambda c: getattr(c, "position", 0)):
                ch_id = getattr(ch, "id", "")
                ch_name = getattr(ch, "name", "")
                ch_type = getattr(getattr(ch, "type", None), "name", "channel")
                lines.append(f"  - #{ch_name} (tipo: {ch_type}, ID: {ch_id})")
    elif all_channels:
        lines.append("\nCANAIS:")
        for ch in sorted(all_channels, key=lambda c: getattr(c, "position", 0)):
            ch_id = getattr(ch, "id", "")
            ch_name = getattr(ch, "name", "")
            lines.append(f"- #{ch_name} (ID: {ch_id})")

    # Cargos principais (limitados para não estourar prompt)
    roles = list(getattr(guild, "roles", []))
    if roles:
        lines.append("\nCARGOS:")
        sorted_roles = sorted(roles, key=lambda r: getattr(r, "position", 0), reverse=True)
        for r in sorted_roles[:25]:
            r_name = getattr(r, "name", "")
            r_id = getattr(r, "id", "")
            lines.append(f"- @{r_name} (ID: {r_id})")

    return "\n".join(lines)
