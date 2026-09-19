"""Texto: tirar acento, comparar nomes, achar listas de nomes. Sem dependência nenhuma."""

from __future__ import annotations

import re
import unicodedata

# Palavras que NUNCA são nome de canal/cargo (verbos, artigos, preposições, objetos).
PALAVRAS_VAZIAS = {
    "a", "as", "o", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das", "em", "no",
    "na", "nos", "nas", "por", "para", "pra", "com", "sem", "e", "ou", "que", "se", "meu", "minha",
    "seu", "sua", "este", "esta", "esse", "essa", "isso", "isto", "aquele", "aquela", "aqui",
    "ali", "la", "lá", "ja", "já", "agora", "tudo", "todos", "todas", "todo", "toda", "mais",
    "menos", "exceto", "so", "só", "apenas", "deixe", "deixa", "deixar", "mantenha", "manter",
    "apague", "apaga", "apagar", "exclua", "excluir", "exclui", "delete", "deletar", "deleta",
    "remova", "remover", "remove", "limpe", "limpar", "limpa", "tire", "tirar", "tira", "destrua",
    "destruir", "zere", "zerar", "crie", "cria", "criar", "faca", "fazer", "faz", "adicione",
    "adicionar", "adiciona", "monte", "montar", "monta", "construa", "construir", "renomeie",
    "renomear", "renomeia", "mude", "mudar", "muda", "troque", "trocar", "troca", "mova", "mover",
    "move", "leve", "levar", "leva", "coloque", "colocar", "coloca", "canal", "canais", "categoria",
    "categorias", "cargo", "cargos", "servidor", "mensagem", "mensagens", "chat", "conversa",
    "historico", "texto", "voz", "vocal", "voice", "text", "chamado", "chamada", "chamados",
    "chamadas", "nome", "nomes", "nomeado", "nomeada", "nomeados", "nomeadas", "novo", "nova", "novos",
    "novas", "chamados:", "de:", "id", "todos", "minhas", "meus",

    # números por extenso entram na contagem, não no nome
    "dois", "duas", "tres", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez", "vinte",
    "trinta", "quarenta", "cinquenta",
}

NUMEROS = {
    "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6,
    "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12, "quinze": 15,
    "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50,
}


def sem_acento(texto: str) -> str:
    """'Informações' → 'informacoes' (o dono escreve com e sem acento; tem que dar na mesma)."""
    base = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in base if not unicodedata.combining(c))


def normalizar(texto: str) -> str:
    """Caixa baixa, sem acento, espaço único — a forma em que o parser pensa."""
    return re.sub(r"\s+", " ", sem_acento(texto or "").lower()).strip()


def tirar_mencao(texto: str, ids: list[int]) -> str:
    """Tira <@id> e <@!id> do começo da mensagem (sobra só o pedido)."""
    limpo = texto or ""
    for i in ids:
        limpo = re.sub(rf"<@!?{i}>", " ", limpo)
    return re.sub(r"\s+", " ", limpo).strip()


def chave_de_nome(nome: str) -> str:
    """Como o Discord: caixa baixa, acento fora, espaço vira traço (nome de canal)."""
    return normalizar(nome).replace(" ", "-")


def nomes_entre_aspas(texto: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"[\"“”'‘’]([^\"“”'‘’]{1,80})[\"“”'‘’]", texto)]


def palavras(texto: str) -> list[str]:
    return [p for p in re.split(r"[\s,]+", texto or "") if p]


def nomes_soltos(texto: str, manter_numeros: bool = False) -> list[str]:
    """
    Nomes de canal dentro de uma frase: as palavras que não são verbo/artigo/objeto.

    Canal no Discord não tem espaço (vira traço), então palavra solta é exatamente o que o
    usuário escreve quando fala de canal: "apague o caps-voz e o caps-texto".
    """
    saida: list[str] = []
    for palavra in palavras(texto):
        # número é quantidade por padrão ("crie 3 canais"); quando o usuário está DITANDO nomes
        # ("crie os canais um e dois"), ele é nome — o canal dele se chama "um".
        if palavra.isdigit() or palavra in NUMEROS:
            if manter_numeros:
                saida.append(palavra)
            continue
        if palavra in PALAVRAS_VAZIAS:
            continue
        saida.append(palavra)
    return saida


def numero_da_frase(texto: str) -> int | None:
    """Quantidade pedida: '5 canais', 'três canais'."""
    m = re.search(r"(?:^|\s)(\d{1,3})(?=\s|$)", texto or "")
    if m:
        valor = int(m.group(1))
        return valor if 0 < valor <= 200 else None
    for palavra in palavras(texto):
        if palavra in NUMEROS:
            return NUMEROS[palavra]
    return None


def listar_nomes(texto: str, manter_numeros: bool = False) -> list[str]:
    """
    Lista de nomes ditada pelo usuário, na ordem: aspas primeiro, senão os nomes soltos.

    "apague os canais caps-voz, caps-texto e tipo-forum" → [caps-voz, caps-texto, tipo-forum]
    """
    entre_aspas = nomes_entre_aspas(texto)
    if entre_aspas:
        return entre_aspas
    return nomes_soltos(texto, manter_numeros=manter_numeros)
