"""
Deixa os relatórios publicados sem dado do servidor de ninguém.

O repositório é PÚBLICO e os logs do Actions também: nome de servidor, ID, nome de canal, nome
de cargo e link de mensagem de um cliente não podem aparecer ali. Este módulo troca esses
pedaços por apelidos estáveis ("Servidor-1", "Canal-2", "Cargo-3") e mascara IDs, menções e
links. O mesmo nome recebe sempre o mesmo apelido, então o relatório continua legível e
comparável entre execuções.

Regra de ouro: mascarar NUNCA pode derrubar o relatório — na dúvida, o texto volta como veio.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

# IDs do Discord (snowflakes) têm 17 a 20 dígitos.
PADRAO_ID = re.compile(r"(?<!\d)\d{17,20}(?!\d)")
MENCAO_CARGO = re.compile(r"<@&\d+>")
MENCAO_PESSOA = re.compile(r"<@!?\d+>")
MENCAO_CANAL = re.compile(r"<#\d+>")
LINK_DE_MENSAGEM = re.compile(r"discord(?:app)?\.com/channels/\S+")

# Apelidos que substituem menções cruas (quando o ID já foi mascarado não dá para saber o tipo).
APELIDO_CARGO = "<@&cargo>"
APELIDO_PESSOA = "<@pessoa>"
APELIDO_CANAL = "<#canal>"
APELIDO_MENSAGEM = "discord.com/channels/<servidor>/<canal>/<mensagem>"

# Nome curto demais não é mascarado: trocar "a" por um apelido destruiria o texto inteiro.
MINIMO_PARA_MASCARAR = 3


class Anonimizador:
    """Troca nomes reais por apelidos estáveis e mascara IDs/menções/links."""

    def __init__(self) -> None:
        self._apelidos: dict[str, str] = {}
        self._contagem: dict[str, int] = {}

    # ------------------------------------------------------------------ registro
    def registrar(self, nome: Any, categoria: str) -> str:
        """Apelida um nome real ("Servidor do Cliente" → "Servidor-1"). Devolve o apelido."""
        texto = "" if nome is None else str(nome).strip()
        if len(texto) < MINIMO_PARA_MASCARAR:
            return texto
        if texto in self._apelidos:
            return self._apelidos[texto]
        categoria = (categoria or "item").strip().lower()
        self._contagem[categoria] = self._contagem.get(categoria, 0) + 1
        apelido = f"{categoria.capitalize()}-{self._contagem[categoria]}"
        self._apelidos[texto] = apelido
        return apelido

    def registrar_varios(self, nomes: Iterable[Any], categoria: str) -> None:
        for nome in nomes or []:
            self.registrar(nome, categoria)

    @property
    def nomes_conhecidos(self) -> dict[str, str]:
        return dict(self._apelidos)

    # ------------------------------------------------------------------ mascaramento
    def mascarar(self, texto: Any) -> str:
        """Devolve o texto sem nomes/IDs/menções/links do servidor. Nunca levanta."""
        if texto is None:
            return ""
        try:
            saida = str(texto)
        except Exception:  # noqa: BLE001 - objeto exótico: melhor devolver algo do que quebrar
            return ""
        try:
            # Nomes primeiro (mais longos antes, para não picar um nome que contém outro),
            # depois menções, links e, por fim, qualquer ID solto que tenha sobrado.
            for nome, apelido in sorted(self._apelidos.items(), key=lambda par: -len(par[0])):
                if nome and nome in saida:
                    saida = saida.replace(nome, apelido)
            saida = MENCAO_CARGO.sub(APELIDO_CARGO, saida)
            saida = MENCAO_PESSOA.sub(APELIDO_PESSOA, saida)
            saida = MENCAO_CANAL.sub(APELIDO_CANAL, saida)
            saida = LINK_DE_MENSAGEM.sub(APELIDO_MENSAGEM, saida)
            saida = PADRAO_ID.sub("<id>", saida)
        except Exception:  # noqa: BLE001 - relatório nunca cai por causa do disfarce
            return str(texto)
        return saida

    # ------------------------------------------------------------------ relatórios prontos
    def mascarar_estrutura(self, dado: Any) -> Any:
        """Aplica o disfarce em listas/dicionários (o JSON do relatório)."""
        if isinstance(dado, str):
            return self.mascarar(dado)
        if isinstance(dado, dict):
            return {chave: self.mascarar_estrutura(valor) for chave, valor in dado.items()}
        if isinstance(dado, list):
            return [self.mascarar_estrutura(item) for item in dado]
        return dado
