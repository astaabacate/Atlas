"""
Peças da EXCLUSÃO de canais — separadas para poderem ser testadas sem Discord.

Nasceu de um bug ao vivo (18/09): o dono pediu "apague todos os canais e deixe esse", o bot
apagou 13 e **sobraram canais**. Motivos, os dois reais:

1. a lista vinha do que o MODELO tinha em mãos (o servidor muda enquanto a conversa acontece —
   outro processo criou canais no meio do caminho);
2. ninguém conferia depois: o bot dizia "✅ 13/13 concluídos com sucesso" sem reler o servidor.

Aqui ficam as duas defesas: a lista de "todos" é montada na hora, direto da API, e o resultado
é conferido depois de apagar.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

# Palavras que significam "todos os canais": o pedido não traz nomes, traz a intenção.
PALAVRAS_DE_TUDO = (
    "todos", "todas", "tudo", "all", "*", "todos os canais", "todas as categorias",
    "todos os canais e categorias", "tudo que é canal",
)

# Só entram como "tudo" quando o pedido fala de canais/categorias (nunca de cargos).
_PALAVRA_DE_CANAL = re.compile(r"\b(canais?|categorias?|channels?|categories?)\b", re.I)


def e_pedido_de_todos(itens: Iterable[str]) -> bool:
    """True quando a lista representa 'todos os canais' (ex.: ['*'], ['todos os canais'])."""
    for item in itens or []:
        texto = str(item).strip().lower()
        if not texto:
            continue
        if texto in PALAVRAS_DE_TUDO:
            return True
        # "todos os canais", "todas as categorias", "todos os canais menos o geral"
        if (texto.startswith(("todos ", "todas ", "tudo "))
                and _PALAVRA_DE_CANAL.search(texto)):
            return True
    return False


def e_item_de_tudo(item: str) -> bool:
    """True para UM item que significa tudo (para expandir item a item)."""
    texto = str(item or "").strip().lower()
    if not texto:
        return False
    if texto in PALAVRAS_DE_TUDO:
        return True
    return texto.startswith(("todos ", "todas ", "tudo ")) and bool(_PALAVRA_DE_CANAL.search(texto))


async def canais_do_servidor(guild: Any) -> tuple[list[Any], bool]:
    """
    Todos os canais e categorias do servidor, lidos AGORA.

    Devolve (canais, veio_da_api). Só uma leitura da API permite CONFERIR a exclusão depois —
    com o cache (ou com um duplo de teste) não dá para saber se o canal saiu de verdade, e aí
    a resposta não pode afirmar que conferiu.
    """
    buscador = getattr(guild, "fetch_channels", None)
    if buscador is not None:
        try:
            return list(await buscador()), True
        except Exception:  # noqa: BLE001 - rede/limite: usa o cache
            pass
    canais = list(getattr(guild, "channels", []) or [])
    categorias = list(getattr(guild, "categories", []) or [])
    return canais + [c for c in categorias if c not in canais], False


async def expandir_tudo(guild: Any, itens: list[str], *, fora: Any = None) -> list[Any]:
    """
    Troca 'todos os canais' pela lista REAL do servidor (lida na hora), mantendo o resto.

    `fora` é o canal da conversa — ele nunca entra (o chamador já garante, isto é cinto e
    suspensório).
    """
    id_fora = getattr(fora, "id", None)
    resultado: list[Any] = []
    vistos: set[Any] = set()
    for item in itens or []:
        if not e_item_de_tudo(item):
            continue
        canais, _ = await canais_do_servidor(guild)
        for canal in canais:
            cid = getattr(canal, "id", None)
            if id_fora is not None and cid == id_fora:
                continue
            if cid in vistos:
                continue
            vistos.add(cid)
            resultado.append(canal)
    return resultado


async def ainda_existem(guild: Any, alvos: list[Any]) -> list[Any]:
    """
    Quais dos alvos AINDA estão no servidor depois da exclusão (conferido na API).

    Devolve os próprios canais (frescos), para o chamador poder tentar de novo e para escrever
    na resposta exatamente o que sobrou. Lista vazia = a exclusão pegou.
    """
    ids = {getattr(a, "id", None) for a in alvos}
    ids.discard(None)
    if not ids:
        return []
    canais, veio_da_api = await canais_do_servidor(guild)
    if not veio_da_api:
        # Sem leitura da API não existe conferência — e inventar "sobrou" seria mentira.
        return []
    return [canal for canal in canais if getattr(canal, "id", None) in ids]


def nomes(canais: list[Any]) -> str:
    """'#a, #b' — para a resposta dizer o que ficou."""
    return ", ".join(f"#{getattr(c, 'name', getattr(c, 'id', 'canal'))}" for c in canais)
