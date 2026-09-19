"""
Testa de verdade a API do OmniRoute (gateway que junta vários provedores num endereço só).

Por que este script existe: o dono pediu para conferir se a chave dele responde. O sandbox de
desenvolvimento NÃO alcança a API (o TLS é cortado: HTTP 000), então o teste roda no GitHub
Actions, onde a rede é aberta — e a chave fica no SEGREDO do repositório, nunca no código.

O que ele verifica, em ordem:
  1. `GET {base}/models` — a porta está aberta e a chave é aceita;
  2. `POST {base}/chat/completions` — uma resposta de verdade, com o tempo medido;
  3. a MESMA chamada com `tools` — se o gateway entrega function calling (é disso que o bot
     depende para criar/apagar canais);
  4. uma segunda chamada simples — a rotação entre provedores continua respondendo.

Uso local (o dono, na máquina dele):
    OMNIROUTE_API_KEY=... OMNIROUTE_BASE_URL=https://SEU-ENDEREÇO/v1 \
        python scripts/testar_omniroute.py

O relatório sai mascarado (`reports/omniroute-latest.md`): a chave NUNCA aparece, e o endereço
também não (só "HOST" + o esquema) — o repositório é público.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"

# Modelo padrão: "auto" é o que a documentação do OmniRoute recomenda (ele escolhe o provedor).
MODELO_PADRAO = "auto"


def mascarar_host(base: str) -> str:
    """Esquema + 'HOST': nada de publicar o endereço do dono em relatório de repo público."""
    esquema = base.split("://", 1)[0] if "://" in base else "https"
    return f"{esquema}://HOST"


class Resultado:
    def __init__(self) -> None:
        self.linhas: list[tuple[str, str, str]] = []

    def add(self, status: str, nome: str, detalhe: str = "") -> None:
        self.linhas.append((status, nome, detalhe))
        icone = {PASS: "✅", FAIL: "❌", WARN: "⚠️"}.get(status, "•")
        print(f"  {icone} [{status}] {nome}" + (f" — {detalhe}" if detalhe else ""), flush=True)

    @property
    def falhas(self) -> int:
        return sum(1 for s, _, _ in self.linhas if s == FAIL)


def _chamar(url: str, chave: str, corpo: dict | None, timeout: float) -> tuple[int, dict, float]:
    """Faz uma chamada e devolve (status, json, segundos). Nunca loga a chave."""
    dados = json.dumps(corpo).encode() if corpo is not None else None
    pedido = urllib.request.Request(url, data=dados, method="POST" if corpo is not None else "GET")
    pedido.add_header("Authorization", f"Bearer {chave}")
    pedido.add_header("Content-Type", "application/json")
    pedido.add_header("User-Agent", "atlas-teste-omniroute/1.0")
    inicio = time.monotonic()
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
            texto = resposta.read().decode("utf-8", "replace")
            return resposta.status, _como_json(texto), time.monotonic() - inicio
    except urllib.error.HTTPError as exc:
        corpo_erro = exc.read().decode("utf-8", "replace")[:400]
        return exc.code, {"erro_http": corpo_erro}, time.monotonic() - inicio
    except Exception as exc:  # noqa: BLE001 - rede: devolve o motivo, não a chave
        return 0, {"erro": f"{type(exc).__name__}: {exc}"[:200]}, time.monotonic() - inicio


def _como_json(texto: str) -> dict:
    try:
        valor = json.loads(texto)
        return valor if isinstance(valor, dict) else {"resposta": valor}
    except Exception:  # noqa: BLE001 - alguns erros vêm em texto puro
        return {"resposta_crua": texto[:400]}


def testar(base: str, chave: str, modelo: str, timeout: float) -> list[tuple[str, str, str]]:
    base = base.rstrip("/")
    r = Resultado()

    status, corpo, segundos = _chamar(f"{base}/models", chave, None, timeout)
    if status == 200:
        modelos = corpo.get("data") or corpo.get("models") or []
        r.add(PASS, "lista de modelos", f"{len(modelos)} modelo(s) em {segundos:.1f}s")
    else:
        r.add(FAIL, "lista de modelos", f"HTTP {status} em {segundos:.1f}s · {_resumo(corpo)}")
        return r.linhas  # sem porta aberta não adianta testar o resto

    simples = {"model": modelo, "messages": [{"role": "user", "content": "Responda apenas: ok"}],
               "max_tokens": 16}
    status, corpo, segundos = _chamar(f"{base}/chat/completions", chave, simples, timeout)
    if status == 200 and _texto(corpo):
        r.add(PASS, "resposta simples", f"{segundos:.1f}s · modelo devolvido: "
                                        f"{corpo.get('model', '?')}")
    else:
        r.add(FAIL, "resposta simples", f"HTTP {status} em {segundos:.1f}s · {_resumo(corpo)}")

    ferramentas = [{
        "type": "function",
        "function": {
            "name": "criar_canal",
            "description": "Cria um canal de texto no servidor.",
            "parameters": {"type": "object", "properties": {"nome": {"type": "string"}},
                           "required": ["nome"]},
        },
    }]
    com_tools = {"model": modelo, "max_tokens": 64, "tools": ferramentas,
                 "tool_choice": "auto",
                 "messages": [{"role": "user",
                               "content": "Crie um canal chamado teste-usando-a-ferramenta."}]}
    status, corpo, segundos = _chamar(f"{base}/chat/completions", chave, com_tools, timeout)
    chamadas = _tool_calls(corpo)
    if status == 200 and chamadas:
        r.add(PASS, "function calling", f"{segundos:.1f}s · chamou {chamadas}")
    elif status == 200:
        r.add(FAIL, "function calling",
              f"{segundos:.1f}s · o gateway respondeu sem chamar ferramenta "
              f"(o bot depende disso para agir): {_resumo(corpo)}")
    else:
        r.add(FAIL, "function calling", f"HTTP {status} em {segundos:.1f}s · {_resumo(corpo)}")

    status, corpo, segundos = _chamar(f"{base}/chat/completions", chave, simples, timeout)
    if status == 200 and _texto(corpo):
        r.add(PASS, "segunda chamada (rotação)", f"{segundos:.1f}s · "
                                                 f"modelo: {corpo.get('model', '?')}")
    else:
        r.add(WARN, "segunda chamada (rotação)",
              f"HTTP {status} em {segundos:.1f}s · {_resumo(corpo)}")

    return r.linhas


def _texto(corpo: dict) -> str:
    escolhas = corpo.get("choices") or []
    if not escolhas:
        return ""
    mensagem = escolhas[0].get("message") or {}
    return (mensagem.get("content") or "").strip()


def _tool_calls(corpo: dict) -> list[str]:
    escolhas = corpo.get("choices") or []
    if not escolhas:
        return []
    mensagem = escolhas[0].get("message") or {}
    return [c.get("function", {}).get("name", "?") for c in (mensagem.get("tool_calls") or [])]


def _resumo(corpo: dict) -> str:
    texto = json.dumps(corpo, ensure_ascii=False)
    return texto[:240]


def relatorio(linhas: list[tuple[str, str, str]], base: str, modelo: str) -> str:
    emoji = {PASS: "✅", FAIL: "❌", WARN: "⚠️"}
    total = len(linhas)
    ok = sum(1 for s, _, _ in linhas if s == PASS)
    md = [
        "# Teste do OmniRoute (ao vivo)",
        "",
        f"- Endereço: `{mascarar_host(base)}` (escondido de propósito: repositório público)",
        f"- Modelo pedido: `{modelo}`",
        f"- Resultado: ✅ {ok} · ❌ {sum(1 for s, _, _ in linhas if s == FAIL)} · "
        f"⚠️ {sum(1 for s, _, _ in linhas if s == WARN)} de {total}",
        "",
        "| | Verificação | Detalhe |",
        "| --- | --- | --- |",
    ]
    for status, nome, detalhe in linhas:
        md.append(f"| {emoji.get(status, '•')} | {nome} | {detalhe.replace('|', '/')} |")
    md.append("")
    md.append("A chave usada neste teste nunca aparece aqui: ela fica no segredo do repositório.")
    return "\n".join(md) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Testa a API do OmniRoute (sem expor a chave).")
    parser.add_argument("--base-url", default=os.environ.get("OMNIROUTE_BASE_URL", "").strip())
    parser.add_argument("--modelo", default=os.environ.get("OMNIROUTE_MODEL", MODELO_PADRAO))
    parser.add_argument("--timeout", type=float,
                        default=float(os.environ.get("OMNIROUTE_TIMEOUT", "45")))
    parser.add_argument("--outdir", default="reports")
    args = parser.parse_args(argv)

    chave = (os.environ.get("OMNIROUTE_API_KEY") or "").strip()
    if not args.base_url or not chave:
        faltando = []
        if not args.base_url:
            faltando.append("OMNIROUTE_BASE_URL (o endereço do seu OmniRoute, terminando em /v1)")
        if not chave:
            faltando.append("OMNIROUTE_API_KEY (a chave, no SEGREDO do repositório)")
        print("⚠️  Sem teste: falta configurar " + " e ".join(faltando) + ".")
        print("    No GitHub: Settings → Secrets and variables → Actions.")
        print("    A chave colada no chat está queimada: gere outra no painel do OmniRoute.")
        return 3  # código próprio: "não configurado" (o workflow trata sem marcar falha)

    print(f"Testando o OmniRoute em {mascarar_host(args.base_url)} com o modelo "
          f"{args.modelo!r} (a chave não aparece em lugar nenhum).")
    linhas = testar(args.base_url, chave, args.modelo, args.timeout)
    md = relatorio(linhas, args.base_url, args.modelo)

    destino = Path(args.outdir)
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "omniroute-latest.md").write_text(md, encoding="utf-8")
    (destino / "omniroute-latest.json").write_text(
        json.dumps({"base": mascarar_host(args.base_url), "modelo": args.modelo,
                    "linhas": [{"status": s, "nome": n, "detalhe": d} for s, n, d in linhas]},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    falhas = sum(1 for s, _, _ in linhas if s == FAIL)
    print(f"\n{md}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
