"""
Funções auxiliares para manipulação de mensagens do Discord.
"""

from __future__ import annotations

import re


def split_message(text: str, limit: int = 2000) -> list[str]:
    """
    Divide um texto longo em blocos de no máximo `limit` caracteres (padrão 2000 do Discord).
    Preserva blocos de código markdown (fecha e reabre no bloco seguinte).
    """
    if not text:
        return [""]
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current_chunk: list[str] = []
    current_len = 0
    in_codeblock = False
    codeblock_lang = ""

    lines = text.split("\n")

    for line in lines:
        line_len = len(line) + 1  # contando o \n

        # Verifica abertura/fechamento de codeblock na linha
        codeblock_match = re.search(r"```(\w*)", line)
        toggles = line.count("```")

        # Se uma única linha for maior que o limite, precisamos fatiá-la
        if line_len > limit:
            # Descarrega o que já temos
            if current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_len = 0

            # Fatiar a linha longa
            start = 0
            while start < len(line):
                end = start + (limit - 10 if in_codeblock else limit)
                slice_text = line[start:end]
                if in_codeblock:
                    chunks.append(f"```{codeblock_lang}\n{slice_text}\n```")
                else:
                    chunks.append(slice_text)
                start = end
            continue

        # Se adicionar a linha ultrapassar o limite
        needed_overhead = (len(f"\n```{codeblock_lang}") + len("\n```")) if in_codeblock else 0
        if current_len + line_len + needed_overhead > limit:
            if in_codeblock:
                current_chunk.append("```")
                chunks.append("\n".join(current_chunk))
                current_chunk = [f"```{codeblock_lang}"]
                current_len = len(current_chunk[0]) + 1
            else:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_len = 0

        current_chunk.append(line)
        current_len += line_len

        # Atualiza estado do codeblock
        if toggles % 2 != 0:
            if in_codeblock:
                in_codeblock = False
                codeblock_lang = ""
            else:
                in_codeblock = True
                if codeblock_match:
                    codeblock_lang = codeblock_match.group(1)

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return [c for c in chunks if c.strip() or c == ""]
