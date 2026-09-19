"""Limpeza única dos relatórios já publicados no repo público (18/09).

Os relatórios escritos antes do disfarce carregam nome do servidor, IDs, nome do dono e nomes
de canais/cargos. Este script passa o mesmo mascaramento neles e reescreve no lugar.
Rode uma vez; daqui pra frente quem publica já mascara (sonda, e2e e oi).
"""

from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from core.anonimo import Anonimizador  # noqa: E402

RAIZ = pathlib.Path(__file__).resolve().parents[1]
REPORTS = RAIZ / "reports"

# Nomes reais que apareceram nos relatórios antigos. O nome do PRÓPRIO bot (Atlas) fica visível:
# não é dado de ninguém e é ele que o dono precisa achar na lista do Discord.
SERVIDOR = ["Pinguim"]
PESSOAS = ["ek8a"]
CANAIS = ["atlas-oi-da-ia", "geral", "bate-papo"]
CARGOS = ["Cupido", "iTinder", "Admin", "Atirador", "Comandante", "Elite FF", "Membro",
          "Moderador", "Recruta", "Streamer", "VIP", "asta", "negro"]

anon = Anonimizador()
anon.registrar_varios(SERVIDOR, "servidor")
anon.registrar_varios(PESSOAS, "pessoa")
anon.registrar_varios(CANAIS, "canal")
anon.registrar_varios(CARGOS, "cargo")

# A sonda lista TODOS os cargos do servidor numa tabela. Em vez de adivinhar os nomes, a coluna
# do nome vira "Cargo-N" — menos o cargo do próprio bot, o @everyone e os objetos de teste 🧪.
LINHA_DA_TABELA = re.compile(r"^\| (\d+) \| ([^|]+?) \| (`[^|]*`) \|")
MANTIDOS = {"atlas", "@everyone"}


def limpar_tabela_de_cargos(texto: str) -> str:
    contador = 0

    def troca(linha: str) -> str:
        nonlocal contador
        casado = LINHA_DA_TABELA.match(linha)
        if not casado:
            return linha
        nome = casado.group(2).strip()
        if nome.lower() in MANTIDOS or nome.startswith("🧪"):
            return linha
        contador += 1
        return linha.replace(f"| {casado.group(2)} |", f"| Cargo-{contador} |", 1)

    return "\n".join(troca(linha) for linha in texto.split("\n"))


alvos = sorted(list(REPORTS.glob("*.md")) + list(REPORTS.glob("*.json")) +
               list(REPORTS.glob("*.txt")) + list(RAIZ.glob("*.md")))
for caminho in alvos:
    texto = caminho.read_text(encoding="utf-8")
    # A tabela primeiro (o nome dela é substituído pelo apelido da coluna), depois o resto.
    limpo = limpar_tabela_de_cargos(texto) if caminho.suffix == ".md" else texto
    limpo = anon.mascarar(limpo)
    if limpo != texto:
        caminho.write_text(limpo, encoding="utf-8")
        print(f"limpo: {caminho.relative_to(RAIZ)}")
print(f"{len(alvos)} arquivos varridos")
