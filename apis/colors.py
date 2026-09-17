"""
Utilidades de cores: paleta de cores e nome de cor.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

logger = logging.getLogger("farol.apis.colors")

FALLBACK_PALETTES: dict[str, list[dict[str, str]]] = {
    "gamer": [
        {"name": "Roxo Neon", "hex": "#8A2BE2"},
        {"name": "Verde Cibernético", "hex": "#00FF7F"},
        {"name": "Azul Elétrico", "hex": "#00BFFF"},
        {"name": "Vermelho Carmesim", "hex": "#DC143C"},
        {"name": "Dourado Lendário", "hex": "#FFD700"},
    ],
    "dark": [
        {"name": "Grafite Escuro", "hex": "#23272A"},
        {"name": "Preto Meia-Noite", "hex": "#1A1A1A"},
        {"name": "Cinza Tempestade", "hex": "#4F545C"},
        {"name": "Azul Meia-Noite", "hex": "#191970"},
        {"name": "Roxo Profundo", "hex": "#301934"},
    ],
    "pastel": [
        {"name": "Lavanda Suave", "hex": "#E6E6FA"},
        {"name": "Rosa Pêssego", "hex": "#FFDAB9"},
        {"name": "Verde Menta", "hex": "#98FF98"},
        {"name": "Azul Céu Bebê", "hex": "#87CEEB"},
        {"name": "Amarelo Pastel", "hex": "#FFFACD"},
    ],
    "comunidade": [
        {"name": "Azul Discord", "hex": "#5865F2"},
        {"name": "Verde Sucesso", "hex": "#57F287"},
        {"name": "Amarelo Aviso", "hex": "#FEE75C"},
        {"name": "Fúcsia Destaque", "hex": "#EB459E"},
        {"name": "Vermelho Alerta", "hex": "#ED4245"},
    ],
}

KNOWN_COLORS = {
    "#FF0000": "Vermelho",
    "#00FF00": "Verde",
    "#0000FF": "Azul",
    "#FFFF00": "Amarelo",
    "#FFA500": "Laranja",
    "#800080": "Roxo",
    "#FFC0CB": "Rosa",
    "#000000": "Preto",
    "#FFFFFF": "Branco",
    "#808080": "Cinza",
    "#5865F2": "Azul Discord Blurple",
    "#57F287": "Verde Discord",
    "#FEE75C": "Amarelo Discord",
    "#EB459E": "Fúcsia Discord",
    "#ED4245": "Vermelho Discord",
}


def fallback_color_palette(theme: str = "gamer") -> list[dict[str, str]]:
    key = theme.lower().strip()
    return FALLBACK_PALETTES.get(key, FALLBACK_PALETTES["gamer"])


def fallback_color_name(hex_code: str) -> str:
    cleaned = hex_code.strip().upper()
    if not cleaned.startswith("#"):
        cleaned = f"#{cleaned}"
    if cleaned in KNOWN_COLORS:
        return KNOWN_COLORS[cleaned]
    return f"Cor {cleaned}"


async def fetch_color_palette(theme: str = "gamer") -> list[dict[str, str]]:
    # Tenta obter esquema de TheColorAPI
    seed_map = {
        "gamer": "8A2BE2",
        "dark": "23272A",
        "pastel": "FFDAB9",
        "comunidade": "5865F2",
    }
    hex_seed = seed_map.get(theme.lower().strip(), "5865F2")
    url = f"https://www.thecolorapi.com/scheme?hex={hex_seed}&mode=analogic&count=5"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5.0)) as resp:
            if resp.status == 200:
                data = await resp.json()
                colors = data.get("colors", [])
                if colors:
                    return [
                        {"name": c.get("name", {}).get("value", "Cor"), "hex": c.get("hex", {}).get("value", "")}
                        for c in colors
                    ]
    return fallback_color_palette(theme)


async def fetch_color_name(hex_code: str) -> str:
    cleaned = hex_code.strip().lstrip("#")
    url = f"https://www.thecolorapi.com/id?hex={cleaned}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5.0)) as resp:
            if resp.status == 200:
                data = await resp.json()
                name = data.get("name", {}).get("value")
                if name:
                    return name
    return fallback_color_name(hex_code)
