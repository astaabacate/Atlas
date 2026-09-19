"""
O cérebro lento: quando o pedido não é reconhecido, o modelo do OmniRoute decide — e pode
chamar as MESMAS ações do caminho rápido (mesmo executor, mesmas proteções).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable

from atlas2.actions import Contexto, FalhaBot, executar
from atlas2.llm import LLM, LLMIndisponivel
from atlas2.parse import Acao

logger = logging.getLogger("atlas2.brain")

MAX_RODADAS = 3
HISTORICO_POR_CANAL = 8

SISTEMA = """Você é o Atlas, bot que organiza servidores de Discord. Você AGE: usa as ferramentas
para criar, apagar, renomear e mover canais, categorias e cargos.

REGRAS:
1. O pedido do usuário já é a autorização: chame a ferramenta na hora, sem pedir confirmação.
2. Responda em português do Brasil, no MÁXIMO 2 linhas, só o resultado. Nada de plano,
   raciocínio, passo a passo ou inglês.
3. Nunca diga que fez algo sem a ferramenta ter confirmado. O texto da ferramenta é a verdade.
4. Para "apague todos os canais", use a ferramenta com {"todos": true} — NUNCA liste nomes.
5. O canal onde vocês conversam nunca é apagado; se pedirem, a ferramenta avisa e segue.

ESTRUTURA ATUAL (nomes e ids reais):
{estrutura}
"""


def limpar_resposta(texto: str) -> str:
    """
    Tira o que não é resposta: rascunho do modelo, cerca de código e sobra de prompt.
    """
    limpo = texto or ""
    limpo = re.sub(r"<(think|reasoning|analysis|rascunho)>.*?</\1>", " ", limpo,
                   flags=re.IGNORECASE | re.DOTALL)
    limpo = re.sub(r"^\s*(final answer|resposta final|answer)\s*[:\-]\s*", "", limpo,
                   flags=re.IGNORECASE)
    limpo = re.sub(r"```[a-z]*\n?", "", limpo)
    limpo = re.sub(r"\n{3,}", "\n\n", limpo)
    return limpo.strip()


def estrutura_do_servidor(guild: Any, limite: int = 160) -> str:
    """Lista compacta de categorias/canais/cargos com os IDs reais (para não inventar nome)."""
    linhas: list[str] = []
    canais = list(getattr(guild, "channels", []) or [])
    categorias = [c for c in canais if str(getattr(getattr(c, "type", None), "name", "")) == "category"]
    for categoria in sorted(categorias, key=lambda c: getattr(c, "position", 0)):
        linhas.append(f"[categoria] {categoria.name} id={categoria.id}")
        for canal in canais:
            if getattr(canal, "category_id", None) == categoria.id:
                linhas.append(f"  #{canal.name} id={canal.id}")
    for canal in canais:
        if getattr(canal, "category_id", None) is None and canal not in categorias:
            linhas.append(f"#{canal.name} id={canal.id} (sem categoria)")
    for cargo in list(getattr(guild, "roles", []) or [])[:40]:
        if not cargo.is_default():
            linhas.append(f"[cargo] {cargo.name} id={cargo.id}")
    if len(linhas) > limite:
        linhas = linhas[:limite] + [f"... (+{len(linhas) - limite} itens)"]
    return "\n".join(linhas) or "(servidor vazio)"


def _ferramentas() -> list[dict[str, Any]]:
    def ferramenta(nome: str, descricao: str, propriedades: dict[str, Any],
                   obrigatorios: list[str]) -> dict[str, Any]:
        return {"type": "function", "function": {
            "name": nome, "description": descricao,
            "parameters": {"type": "object", "properties": propriedades, "required": obrigatorios}}}

    texto = {"type": "string"}
    lista = {"type": "array", "items": {"type": "string"}}
    return [
        ferramenta("apagar_canais", "Apaga canais/categorias. Para 'apague todos os canais' use "
                   "todos=true com a lista vazia.", {
                       "alvos": {**lista, "description": "nomes, menções ou ids (quando não é todos)"},
                       "todos": {"type": "boolean"},
                       "categoria": {**texto, "description": "limita a uma categoria"}},
                   []),
        ferramenta("criar_canais", "Cria canais de texto ou de voz.", {
            "nomes": lista, "quantidade": {"type": "integer"}, "tipo": texto,
            "categoria": texto, "categoria_nova": texto}, []),
        ferramenta("criar_categoria", "Cria uma categoria.", {"nome": texto}, ["nome"]),
        ferramenta("apagar_cargos", "Apaga cargos.", {"alvos": lista, "todos": {"type": "boolean"}}, []),
        ferramenta("criar_cargos", "Cria cargos.", {
            "nomes": lista, "cor": {"type": "integer", "description": "cor em decimal (0xRRGGBB)"}},
            []),
        ferramenta("renomear_canal", "Renomeia um canal.", {"alvo": texto, "novo": texto},
                   ["alvo", "novo"]),
        ferramenta("renomear_cargo", "Renomeia um cargo.", {"alvo": texto, "novo": texto},
                   ["alvo", "novo"]),
        ferramenta("mover_canal", "Move um canal para uma categoria.", {"alvo": texto, "categoria": texto},
                   ["alvo", "categoria"]),
        ferramenta("recriar_canal", "Apaga e recria o canal como estava.", {"alvo": texto}, ["alvo"]),
        ferramenta("limpar_mensagens", "Apaga as mensagens deste canal.",
                   {"quantidade": {"type": "integer"}}, []),
        ferramenta("listar_canais", "Lista os canais do servidor.", {}, []),
        ferramenta("listar_cargos", "Lista os cargos do servidor.", {}, []),
        ferramenta("info_servidor", "Mostra nome, dono, membros, canais e cargos.", {}, []),
    ]


FERRAMENTAS = _ferramentas()

TOOLS_QUE_APAGAM = {"apagar_canais", "apagar_cargos", "limpar_mensagens"}


class Cerebro:
    def __init__(self, llm: LLM) -> None:
        self.llm = llm
        self.historico: dict[int, list[dict[str, Any]]] = {}

    def esquecer(self, canal_id: int) -> None:
        self.historico.pop(canal_id, None)

    def _lembrar(self, canal_id: int, entrada: dict[str, Any]) -> None:
        memoria = self.historico.setdefault(canal_id, [])
        memoria.append(entrada)
        del memoria[:-HISTORICO_POR_CANAL]

    async def responder(
        self,
        pedido: str,
        ctx: Contexto,
        ao_pedaco: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        canal_id = getattr(ctx.canal, "id", 0)
        mensagens: list[dict[str, Any]] = [
            {"role": "system", "content": SISTEMA.format(estrutura=estrutura_do_servidor(ctx.guild))}
        ]
        mensagens.extend(self.historico.get(canal_id, []))
        mensagens.append({"role": "user", "content": pedido})

        executados: list[str] = []
        for rodada in range(MAX_RODADAS):
            try:
                resposta = await self.llm.conversar(
                    mensagens, FERRAMENTAS, ao_pedaco if rodada == 0 else None
                )
            except LLMIndisponivel as exc:
                if executados:
                    return "✅ Fiz: " + "; ".join(executados) + f"\n(o resumo do modelo falhou: {exc})"
                raise FalhaBot(
                    "Não reconheci esse pedido e a IA não respondeu agora "
                    f"({exc}). Tente de novo ou peça algo como `crie 5 canais`."
                ) from exc

            if not resposta.chamadas:
                final = limpar_resposta(resposta.texto) or "Feito!"
                self._lembrar(canal_id, {"role": "user", "content": pedido})
                self._lembrar(canal_id, {"role": "assistant", "content": final})
                return final

            mensagens.append({
                "role": "assistant", "content": resposta.texto or "",
                "tool_calls": [{"id": c.id, "type": "function",
                                "function": {"name": c.nome, "arguments": c.argumentos or "{}"}}
                               for c in resposta.chamadas],
            })
            for chamada in resposta.chamadas:
                acao = Acao(chamada.nome, chamada.dados)
                try:
                    resultado = await executar(acao, ctx)
                except FalhaBot as exc:
                    resultado = f"Erro: {exc}"
                except Exception as exc:  # noqa: BLE001 - erro inesperado vira texto para o modelo
                    logger.exception("Ação %s falhou", chamada.nome)
                    resultado = f"Erro inesperado: {exc}"
                executados.append(resultado.splitlines()[0][:180])
                mensagens.append({"role": "tool", "tool_call_id": chamada.id,
                                  "name": chamada.nome, "content": resultado})

        return "✅ Fiz: " + "; ".join(executados) if executados else "Feito!"
