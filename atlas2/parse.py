"""
O cérebro rápido: transforma o pedido em AÇÃO sem chamar modelo nenhum.

Cada regra aqui existe para um pedido real do dono. O que não casa com nenhuma regra vira
`None` e vai para o modelo (OmniRoute) — devagar, mas só nesse caso.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from atlas2.texto import (
    NUMEROS,
    listar_nomes,
    nomes_entre_aspas,
    normalizar,
    numero_da_frase,
    palavras,
)

# ---------------------------------------------------------------- verbos
VERBO_APAGAR = r"(apag\w*|exclu\w*|delet\w*|remov\w*|tir\w*|destru\w*|zer\w*|cancel\w*)"
VERBO_CRIAR = r"(cri\w*|faz\w*|adicion\w*|mont\w*|constru\w*|ger\w*|abrir|abre)"
VERBO_LIMPAR = r"(limp\w*|apag\w*|exclu\w*|delet\w*|reset\w*)"
VERBO_RENOMEAR = r"(renome\w*|mud\w*|troc\w*|cham\w* de)"
VERBO_MOVER = r"(mov\w*|lev\w*|coloc\w*|mand\w*|pass\w*|jog\w*)"
VERBO_LISTAR = r"(list\w*|mostr\w*|mand\w*|quai\w*|quant\w*|ver|veja|exib\w*|fala)"

RE_APAGAR = re.compile(rf"\b{VERBO_APAGAR}\b")
RE_CRIAR = re.compile(rf"\b{VERBO_CRIAR}\b")
RE_LIMPAR = re.compile(rf"\b{VERBO_LIMPAR}\b")
RE_RENOMEAR = re.compile(rf"\b{VERBO_RENOMEAR}\b")
RE_MOVER = re.compile(rf"\b{VERBO_MOVER}\b")
RE_LISTAR = re.compile(rf"\b{VERBO_LISTAR}\b")

RE_CANAIS = re.compile(r"\b(cana(?:l|is)|categorias?)\b")
RE_CATEGORIA = re.compile(r"\b(categorias?)\b")
RE_CARGOS = re.compile(r"\b(cargos?)\b")
RE_MENSAGENS = re.compile(r"\b(mensagens?|msg|chat|conversa|historico|conversas)\b")
RE_TODOS = re.compile(r"\b(todos|todas|tudo)\b")
RE_MANTER = re.compile(
    r"(\bmenos\b|\bexceto\b|\bdeix\w*\b|\bmanten\w*\b|\bapenas\b|\bso\b|\bsomente\b|"
    r"nao apag\w*|\bfora\b)"
)
RE_ESTE = re.compile(r"\b(esse|essa|este|esta|isso|aqui|atual|deste|dessa)\b")
RE_VOZ = re.compile(r"\b(voz|vocal|voice|audio)\b")
RE_CATEGORIA_ALVO = re.compile(r"\b(?:na|no|para a|para o|pra|em)\s+categorias?\s+([^\s,]+)")
RE_CATEGORIA_PELO_NOME = re.compile(r"\bcategorias?\s+([^\s,]+)")
RE_PARA = re.compile(r"\b(?:para|pra|chamad[oa]s?\s+que nem|como)\s+(.+)$")
RE_COR = re.compile(r"#([0-9a-f]{6})\b")
RE_QUANTIDADE = re.compile(r"(?:^|\s)(\d{1,3})(?=\s|$)")

CORES = {
    "vermelho": 0xE74C3C, "azul": 0x3498DB, "verde": 0x2ECC71, "roxo": 0x9B59B6,
    "amarelo": 0xF1C40F, "laranja": 0xE67E22, "rosa": 0xEB459E, "preto": 0x000001,
    "branco": 0xFFFFFF, "cinza": 0x95A5A6, "ciano": 0x1ABC9C, "dourado": 0xD4AF37,
    "violeta": 0x8E44AD, "turquesa": 0x1ABC9C, "vinho": 0x992D22, "bege": 0xD5C8A4,
}


@dataclass
class Acao:
    """Um pedido reconhecido. `tipo` diz o que fazer; `dados` leva os parâmetros."""

    tipo: str
    dados: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:  # só para log
        return f"{self.tipo}{self.dados if self.dados else ''}"


def _depois_da_categoria(texto: str) -> str | None:
    for rx in (RE_CATEGORIA_ALVO, RE_CATEGORIA_PELO_NOME):
        m = rx.search(texto)
        if m:
            return m.group(1).strip("- ")
    return None


def _so_nomes(texto: str) -> list[str]:
    """Nomes de canal sem tirar número: 'canais um e dois' → ['um', 'dois']."""
    return listar_nomes(texto, manter_numeros=True)


def _caixa_original(original: str, nomes: list[str]) -> list[str]:
    """Devolve os nomes com a grafia do dono: 'moderador' → 'Moderador'."""
    tokens = {}
    for palavra in original.replace(",", " ").split():
        tokens.setdefault(normalizar(palavra), palavra)
    return [tokens.get(normalizar(nome), nome) for nome in nomes]


def _nomes_de_criacao(texto: str) -> list[str]:
    """Nomes ditados para criar: aspas > gatilho ('chamado/canais') > nomes soltos."""
    entre_aspas = nomes_entre_aspas(texto)
    if entre_aspas:
        return entre_aspas
    m = re.search(r"\b(?:cana(?:l|is)|categorias|cargos)\s+(.+)$", texto)
    if m:
        return _so_nomes(m.group(1))
    m = re.search(r"\b(?:chamad[oa]s?|nomead[oa]s?|com o nome|com os nomes|de nome|de nomes|nomes?)\s+(.+)$", texto)
    if m:
        return listar_nomes(m.group(1))
    return listar_nomes(texto)


def _nome_apos_para(texto: str) -> str | None:
    m = RE_PARA.search(texto)
    if not m:
        return None
    nomes = listar_nomes(m.group(1))
    return " ".join(nomes) if nomes else None


def reconhecer(pedido: str) -> Acao | None:  # noqa: C901 - a ordem das regras é o desenho
    """
    Lê o pedido e devolve o que fazer — ou None (aí o modelo decide).

    Nada aqui chama rede: é tudo string, por isso sai em microssegundos.
    """
    t = normalizar(pedido)
    if not t:
        return None
    original = pedido

    # --- quanto o bot está demorando (pedido do dono: velocidade é requisito)
    if re.search(r"\b(tempo|demora|demorando|velocidade|latencia|lento|rapido)\b", t) and \
            not RE_CANAIS.search(t) and not RE_CARGOS.search(t):
        return Acao("tempos")

    # --- papo de ajuda / conversa pura
    if re.search(r"\b(ajuda|help|comandos|o que voce faz|o que vc faz)\b", t):
        return Acao("ajuda")
    if re.fullmatch(r"(oi|ola|opa|bom dia|boa tarde|boa noite|e ai|eai|tudo bem)[!. ]*", t):
        return Acao("cumprimento")

    # --- limpar MENSAGENS (não confundir com apagar canal!)
    if RE_MENSAGENS.search(t) and (RE_LIMPAR.search(t) or re.search(r"\besvazi\w*", t)):
        # "apague TODOS os canais" junto com mensagens = apagar canal; o resto
        # ("apague as mensagens desse canal") é limpar o chat.
        if RE_TODOS.search(t) and RE_CANAIS.search(t):
            return Acao("apagar_canais", {"alvos": [], "todos": True, "manter_atual": True,
                                          "categoria": _depois_da_categoria(t)})
        return Acao("limpar_mensagens", {"quantidade": numero_da_frase(t)})

    # --- informações do servidor
    if re.search(r"\b(informac\w*|info|ficha|dados|detalhes|estatistic\w*|resumo|sobre)\b", t) and \
            re.search(r"\b(servidor|server|guild|grupo)\b", t):
        return Acao("info_servidor")

    # --- listar
    if RE_LISTAR.search(t) and not RE_APAGAR.search(t) and not RE_CRIAR.search(t):
        if RE_CARGOS.search(t):
            return Acao("listar_cargos")
        if RE_CANAIS.search(t):
            return Acao("listar_canais", {"todos": True})
        return None  # "lista o que?" — deixa o modelo entender

    # --- renomear
    if RE_RENOMEAR.search(t) and RE_CARGOS.search(t):
        alvo = _caixa_original(original, listar_nomes(re.sub(r"\b" + VERBO_RENOMEAR + r".*", "", t)))
        novo = _nome_apos_para(t)
        if novo:
            return Acao("renomear_cargo", {"alvo": alvo[0] if alvo else None, "novo": novo})
        return None
    if RE_RENOMEAR.search(t) and RE_CANAIS.search(t):
        m = re.search(r"\bcanal\s+([^\s,]+)", t)
        novo = _nome_apos_para(t)
        if m and novo:
            return Acao("renomear_canal", {"alvo": m.group(1), "novo": novo})
        return None

    # --- mover canal para categoria
    if RE_MOVER.search(t) and RE_CANAIS.search(t):
        categoria = _depois_da_categoria(t)
        m = re.search(r"\bcanal\s+([^\s,]+)", t)
        if categoria and m and normalizar(m.group(1)) != normalizar(categoria):
            return Acao("mover_canal", {"alvo": m.group(1), "categoria": categoria})
        return None

    # --- recriar canal (apaga e devolve igual)
    if re.search(r"\brecri\w*|\brecria\w*|\brecrie\b", t) and RE_CANAIS.search(t):
        m = re.search(r"\bcanal\s+([^\s,]+)", t)
        if m:
            return Acao("recriar_canal", {"alvo": m.group(1)})
        return None

    # --- apagar CARGOS
    if RE_APAGAR.search(t) and RE_CARGOS.search(t) and not RE_CANAIS.search(t):
        todos = bool(RE_TODOS.search(t))
        alvos = [] if todos else listar_nomes(re.sub(r"\b(cargos?)\b", " ", t))
        return Acao("apagar_cargos", {"alvos": alvos, "todos": todos})

    # --- criar CARGOS
    if RE_CRIAR.search(t) and RE_CARGOS.search(t) and not RE_CANAIS.search(t):
        cor = None
        m = RE_COR.search(t)
        if m:
            cor = int(m.group(1), 16)
        else:
            for nome, valor in CORES.items():
                if re.search(rf"\b{nome}\b", t):
                    cor = valor
                    break
        nomes = [n for n in _caixa_original(original, _nomes_de_criacao(re.sub(r"\b(cargos?)\b", " ", t)))
                 if normalizar(n) not in CORES]
        return Acao("criar_cargos", {"nomes": nomes, "cor": cor}) if nomes else None

    # --- apagar CANAIS
    if RE_APAGAR.search(t) and RE_CANAIS.search(t):
        todos = bool(RE_TODOS.search(t))
        manter = bool(RE_MANTER.search(t) and RE_ESTE.search(t)) or bool(RE_TODOS.search(t))
        if todos:
            return Acao("apagar_canais", {"alvos": [], "todos": True, "manter_atual": manter,
                                          "categoria": _depois_da_categoria(t)})
        alvos = _caixa_original(original, listar_nomes(re.sub(r"\b(canais?|categorias?)\b", " ", t)))
        if alvos:
            return Acao("apagar_canais", {"alvos": alvos, "todos": False, "manter_atual": True,
                                          "categoria": _depois_da_categoria(t)})
        return None

    # --- criar CATEGORIA (sozinha, ou já com canais dentro)
    if RE_CRIAR.search(t) and RE_CATEGORIA.search(t):
        nome_categoria = _depois_da_categoria(t)
        if not nome_categoria:
            m = re.search(r"\bcategorias?\s+(?:com o nome|chamada|chamado)?\s*([^\s,]+)", t)
            nome_categoria = m.group(1).strip("- ") if m else None
        dentro: list[str] = []
        m = re.search(r"\b(?:com os )?canais\s+(.+)$", t)
        if m:
            dentro = _so_nomes(m.group(1))
        if nome_categoria and dentro:
            return Acao("criar_canais", {"nomes": dentro, "quantidade": None,
                                         "tipo": "voice" if RE_VOZ.search(t) else "text",
                                         "categoria_nova": nome_categoria})
        if nome_categoria:
            return Acao("criar_categoria", {"nome": nome_categoria})

    # --- criar CANAIS (inclui o "crie 5 canais")
    if RE_CRIAR.search(t) and RE_CANAIS.search(t):
        tipo = "voice" if RE_VOZ.search(t) else "text"
        categoria = _depois_da_categoria(t)
        nomes = [n for n in _caixa_original(original, _nomes_de_criacao(t)) if n != categoria]
        quantidade = numero_da_frase(t)
        if not nomes and quantidade:
            return Acao("criar_canais", {"nomes": [], "quantidade": quantidade, "tipo": tipo,
                                         "categoria": categoria})
        if nomes:
            if quantidade and quantidade > len(nomes):
                return Acao("criar_canais", {"nomes": nomes, "quantidade": quantidade,
                                             "tipo": tipo, "categoria": categoria})
            return Acao("criar_canais", {"nomes": nomes, "quantidade": None, "tipo": tipo,
                                         "categoria": categoria})
        return None

    # --- "apague tudo" (sem dizer o objeto): se é canal ou cargo dá para inferir pelo que existe
    if RE_APAGAR.search(t) and RE_TODOS.search(t):
        return Acao("apagar_canais", {"alvos": [], "todos": True, "manter_atual": True,
                                      "categoria": None})

    return None


def nomes_gerados(quantidade: int, tipo: str) -> list[str]:
    """'crie 5 canais' → canal-1..canal-5 (o dono não ditou nome; a gente cria e mostra)."""
    prefixo = "voz" if tipo == "voice" else "canal"
    return [f"{prefixo}-{i}" for i in range(1, quantidade + 1)]


def somar_palavras(texto: str) -> int | None:  # compatibilidade de leitura
    for palavra in palavras(texto):
        if palavra in NUMEROS:
            return NUMEROS[palavra]
    return None
