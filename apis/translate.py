"""
Tradução de textos para auxílio na criação de canais multilíngues e descrições.
"""

from __future__ import annotations

import logging
import urllib.parse

import aiohttp

logger = logging.getLogger("atlas.apis.translate")


def fallback_translate(text: str, target_lang: str = "pt") -> str:
    # Se falhar ou offline, retorna o próprio texto com aviso ou tradução simples
    return text


async def fetch_translation(text: str, target_lang: str = "pt") -> str:
    # Usa endpoint público do MyMemory
    encoded_text = urllib.parse.quote(text)
    url = f"https://api.mymemory.translated.net/get?q={encoded_text}&langpair=en|{target_lang}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5.0)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    matches = data.get("responseData", {}).get("translatedText")
                    if matches:
                        return matches
    except Exception as exc:
        logger.debug("Falha na tradução externa: %s", exc)
    return fallback_translate(text, target_lang)
