"""
Utilidade para busca de emojis úteis na organização de servidores.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("atlas.apis.emojis")

EMOJI_CATALOG: dict[str, list[str]] = {
    "voz": ["🔊", "🎙️", "🎧", "🗣️", "📢"],
    "audio": ["🔊", "🎙️", "🎧", "🎵", "🎶"],
    "texto": ["💬", "💭", "📝", "✍️", "📖"],
    "regras": ["📜", "⚖️", "📌", "🛡️", "📋"],
    "avisos": ["📢", "🚨", "📣", "🔔", "⚠️"],
    "anuncios": ["📢", "🚨", "📣", "🔔", "✨"],
    "bem-vindo": ["👋", "🎉", "🌟", "🚪", "🥂"],
    "gamer": ["🎮", "🕹️", "👾", "🏆", "🎯"],
    "jogos": ["🎮", "🕹️", "🎲", "👾", "⚔️"],
    "musica": ["🎵", "🎶", "🎸", "🎹", "🎷"],
    "memes": ["🐸", "🤣", "🎭", "🤡", "🍿"],
    "vip": ["⭐", "💎", "👑", "🔥", "✨"],
    "admin": ["🛡️", "⚙️", "🔧", "👑", "🚨"],
    "staff": ["🛡️", "💼", "👔", "📋", "⚡"],
    "estudos": ["📚", "✏️", "🎓", "🔬", "📖"],
    "geral": ["💬", "✨", "🌍", "☕", "👋"],
    "suporte": ["🎫", "❓", "🛠️", "💡", "🩺"],
    "fotos": ["📷", "📸", "🖼️", "🎨", "👀"],
}


def fallback_emoji_search(query: str) -> list[str]:
    q = query.lower().strip()
    if q in EMOJI_CATALOG:
        return EMOJI_CATALOG[q]

    # Busca parcial por chave
    matches = []
    for key, emojis in EMOJI_CATALOG.items():
        if q in key or key in q:
            matches.extend(emojis)

    if matches:
        # Remover duplicados mantendo ordem
        return list(dict.fromkeys(matches))[:8]

    return ["💬", "✨", "📌", "🎮", "📢"]


async def fetch_emoji_search(query: str) -> list[str]:
    # Usar catálogo resiliente embutido
    return fallback_emoji_search(query)
