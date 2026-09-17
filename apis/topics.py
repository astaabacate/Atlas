"""
Sugestão de tópicos e descrições para canais do Discord.
"""

from __future__ import annotations

import random

TOPICS_BY_CATEGORY: dict[str, list[str]] = {
    "geral": [
        "Espaço aberto para conversar sobre qualquer assunto! Respeite as regras.",
        "Ponto de encontro da comunidade para trocar ideias e bater papo diário.",
        "Café virtual: converse sobre seu dia, novidades e faça novas amizades.",
    ],
    "gamer": [
        "Compartilhe suas gameplays, convide a galera para jogar e busque duo/squad!",
        "Discussões sobre lançamentos, notas de atualização e setups gamer.",
        "Espaço para clipes incríveis, jogadas épicas e fails engraçados.",
    ],
    "estudos": [
        "Foco e concentração: tire dúvidas sobre matérias e compartilhe resumos.",
        "Canal de estudos e produtividade — compartilhe suas metas do dia!",
        "Dicas acadêmicas, livros e recursos educacionais recomendados.",
    ],
    "memes": [
        "Apenas memes de qualidade. Proibido conteúdo ofensivo ou NSFW.",
        "Zona livre de risadas: envie seus melhores vídeos e imagens divertidas.",
    ],
    "anuncios": [
        "Fique por dentro das novidades, atualizações e eventos do servidor!",
        "Comunicados oficiais da moderação e notícias importantes da comunidade.",
    ],
}


def fallback_topic_suggest(category: str = "geral") -> str:
    cat = category.lower().strip()
    pool = TOPICS_BY_CATEGORY.get(cat, TOPICS_BY_CATEGORY["geral"])
    return random.choice(pool)


async def fetch_topic_suggest(category: str = "geral") -> str:
    return fallback_topic_suggest(category)
