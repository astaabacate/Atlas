"""
Sonda de hierarquia de cargos — pergunta DIRETO à API do Discord, sem passar pelo produto.

Por que existe: o relato do dono é "como um bot não consegue apagar um cargo que ele
MESMO criou? essa de posição está errada". O harness ao vivo nunca perguntou isso ao
Discord: ele chamava a ferramenta do produto, o NOSSO gate de política recusava por
posição, e o relatório anotava "o Discord recusa" — o que não era verdade provada.

Esta sonda faz o experimento cru, com o token do bot, sem `brain/`, sem cache do
discord.py, sem política:

  1. lê os cargos do servidor e a posição do cargo mais alto do bot (direto da API);
  2. cria um cargo de teste marcado com 🧪;
  3. tenta RENOMEAR (PATCH) e APAGAR (DELETE) esse cargo pela API crua;
  4. se o Discord recusar, tenta MOVER o cargo para a posição 0 e apagar de novo;
  5. diz, com o corpo cru das respostas, o que o Discord aceita e o que recusa.

Não imprime conversa, mensagem ou membro nenhum: só nomes/posições de cargo e o
resultado das chamadas de API. Se o cargo de teste ficar preso (Discord recusou tudo),
ele é reportado com o ID para o dono apagar na mão.

Uso:
    DISCORD_TOKEN=... python scripts/sonda_hierarquia.py --outdir reports
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import aiohttp

API = "https://discord.com/api/v10"
MARCA = "🧪 sonda-hierarquia"


# --------------------------------------------------------------------------- HTTP

class Sondagem:
    """Cliente REST mínimo: devolve (status, corpo) sem levantar por erro de API."""

    def __init__(self, token: str) -> None:
        self._token = token
        self._sessao: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "Sondagem":
        self._sessao = aiohttp.ClientSession(
            headers={"Authorization": f"Bot {self._token}",
                     "User-Agent": "FarolSondaHierarquia/1.0",
                     "X-Audit-Log-Reason": "sonda de hierarquia do farol"},
            timeout=aiohttp.ClientTimeout(total=30),
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._sessao is not None:
            await self._sessao.close()

    async def pedir(self, metodo: str, caminho: str, **kwargs: Any) -> tuple[int, Any]:
        assert self._sessao is not None
        url = f"{API}{caminho}"
        for tentativa in range(3):
            async with self._sessao.request(metodo, url, **kwargs) as resp:
                if resp.status == 429:
                    espera = float(resp.headers.get("Retry-After", "1") or 1)
                    await asyncio.sleep(min(espera, 5.0) + 0.2)
                    continue
                if resp.status >= 500 and tentativa < 2:
                    await asyncio.sleep(1.0 + tentativa)
                    continue
                texto = await resp.text()
                try:
                    corpo: Any = json.loads(texto) if texto else None
                except json.JSONDecodeError:
                    corpo = texto
                return resp.status, corpo
        return 0, "sem resposta após 3 tentativas"


def _erro(corpo: Any) -> str:
    """Resumo do corpo de erro do Discord (code + message), sem despejar HTML."""
    if isinstance(corpo, dict):
        c = corpo.get("code")
        m = str(corpo.get("message", ""))[:200]
        return f"code={c} message={m}" if c is not None else m
    return str(corpo)[:200]


# ------------------------------------------------------------------- montagem da visão

def _topo_do_membro(membro: dict[str, Any] | None, cargos: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Cargo mais alto de um membro, calculado só com a API (id do membro + lista de cargos)."""
    if not membro:
        return None
    ids = set(membro.get("roles") or [])
    meus = [c for c in cargos if str(c.get("id")) in ids]
    if not meus:
        return None
    return max(meus, key=lambda c: int(c.get("position", 0)))


def _tem_permissao(cargos_do_bot: list[dict[str, Any]], todos: list[dict[str, Any]],
                   bit: int) -> bool:
    """Conferência manual de permissão do bot: OR dos cargos dele + @everyone."""
    valor = 0
    for c in cargos_do_bot + [c for c in todos if c.get("is_default")]:
        valor |= int(c.get("permissions", 0))
    return bool(valor & bit)


MANAGE_ROLES = 1 << 28


# --------------------------------------------------------------------------- sonda

async def sondar(guild_id: str | None, outdir: Path) -> int:
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token:
        print("::error title=sonda::DISCORD_TOKEN vazio — nada a testar")
        return 2

    linhas: list[str] = []
    dados: dict[str, Any] = {"gerado_em": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                             "guilds": []}

    async with Sondagem(token) as api:
        st, eu = await api.pedir("GET", "/users/@me")
        if st != 200:
            print(f"::error title=sonda::token recusado (HTTP {st}: {_erro(eu)})")
            return 2
        bot_id = str(eu["id"])
        linhas.append(f"# Sonda de hierarquia de cargos — {eu.get('username')} (`{bot_id}`)")
        linhas.append("")

        st, guilds = await api.pedir("GET", "/users/@me/guilds")
        if st != 200 or not isinstance(guilds, list):
            print(f"::error title=sonda::não listei servidores (HTTP {st}: {_erro(guilds)})")
            return 2

        alvos = [g for g in guilds if not guild_id or str(g["id"]) == str(guild_id)]
        if not alvos:
            print(f"::error title=sonda::servidor {guild_id} não está na lista do bot")
            return 2

        for g in alvos:
            gid = str(g["id"])
            linhas.append(f"## Servidor {g.get('name')} (`{gid}`)")
            linhas.append("")
            st, cargos = await api.pedir("GET", f"/guilds/{gid}/roles")
            if st != 200:
                linhas.append(f"- ❌ não li os cargos: HTTP {st} {_erro(cargos)}")
                continue
            st, membro = await api.pedir("GET", f"/guilds/{gid}/members/{bot_id}")
            if st != 200:
                linhas.append(f"- ❌ não li o meu membro: HTTP {st} {_erro(membro)}")
                continue
            st, dono = await api.pedir("GET", f"/guilds/{gid}")
            dono_id = str((dono or {}).get("owner_id", "")) if isinstance(dono, dict) else ""
            membro_dono = None
            if dono_id:
                st_d, membro_dono = await api.pedir("GET", f"/guilds/{gid}/members/{dono_id}")

            cargos_ordenados = sorted(cargos, key=lambda c: -int(c.get("position", 0)))
            ids_do_bot = set(membro.get("roles") or [])
            meus_cargos = [c for c in cargos if str(c["id"]) in ids_do_bot]
            topo = _topo_do_membro(membro, cargos)
            pos_bot = int(topo["position"]) if topo else 0
            pos_dono = None
            if isinstance(membro_dono, dict):
                td = _topo_do_membro(membro_dono, cargos)
                pos_dono = int(td["position"]) if td else None

            linhas.append(f"- Meu cargo mais alto: **{topo['name']}** (`{topo['id']}`) na "
                          f"**posição {pos_bot}** de {len(cargos)} cargo(s)." if topo else
                          "- ❌ não achei meu cargo na lista (bot sem cargo?)")
            if pos_dono is not None:
                linhas.append(f"- Cargo mais alto do dono: posição {pos_dono}.")
            linhas.append(f"- Tenho a permissão Gerenciar Cargos: "
                          f"**{'sim' if _tem_permissao(meus_cargos, cargos, MANAGE_ROLES) else 'NÃO'}**.")
            linhas.append("")
            linhas.append("| Posição | Cargo | ID | Gerenciado | Situação para o bot |")
            linhas.append("| --- | --- | --- | --- | --- |")
            for c in cargos_ordenados:
                pos = int(c.get("position", 0))
                if c.get("is_default"):
                    situacao = "@everyone (sempre intocável)"
                elif pos > pos_bot:
                    situacao = "ACIMA do meu cargo"
                elif pos == pos_bot:
                    situacao = "MESMA posição do meu cargo"
                else:
                    situacao = "abaixo do meu cargo"
                linhas.append(f"| {pos} | {c.get('name')} | `{c.get('id')}` | "
                              f"{'sim' if c.get('managed') else ''} | {situacao} |")
            linhas.append("")

            experimento = await _experimento(api, gid, pos_bot)
            linhas.extend(experimento["linhas"])
            dados["guilds"].append({
                "id": gid, "nome": g.get("name"), "cargos": len(cargos),
                "pos_bot": pos_bot, "cargo_do_bot": (topo or {}).get("name"),
                "pos_dono": pos_dono, "experimento": experimento["dados"],
            })

    relatorio = "\n".join(linhas) + "\n"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "sonda-hierarquia.md").write_text(relatorio, encoding="utf-8")
    (outdir / "sonda-hierarquia.json").write_text(
        json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    print(relatorio)
    return 0


async def _experimento(api: "Sondagem", gid: str, pos_bot: int) -> dict[str, Any]:
    """
    O experimento do dono: criar um cargo e tentar apagar/editar ele mesmo, pela API crua.

    É o único jeito de saber se o "não consigo apagar" vem do Discord ou do nosso gate.
    """
    linhas: list[str] = ["### Experimento cru (sem passar pelo produto)", ""]
    dados: dict[str, Any] = {}
    nome = f"{MARCA}-{int(time.time())}"

    st, criado = await api.pedir("POST", f"/guilds/{gid}/roles", json={"name": nome})
    if st not in (200, 201) or not isinstance(criado, dict):
        linhas.append(f"- ❌ não consegui criar o cargo de teste: HTTP {st} {_erro(criado)}")
        dados["criacao"] = {"status": st, "erro": _erro(criado)}
        return {"linhas": linhas, "dados": dados}
    rid = str(criado["id"])
    pos_criado = int(criado.get("position", -1))
    dados["criado"] = {"id": rid, "posicao": pos_criado}
    linhas.append(f"- Criei **{nome}** (`{rid}`) → o Discord colocou na **posição {pos_criado}** "
                  f"(meu cargo está na {pos_bot}).")

    st, corpo = await api.pedir("PATCH", f"/guilds/{gid}/roles/{rid}",
                                json={"name": nome + "-editado"})
    dados["editar"] = {"status": st, "corpo": _erro(corpo) if st >= 400 else "ok"}
    if st < 400:
        linhas.append("- ✏️ **RENOMEAR: o Discord ACEITOU** mesmo na mesma posição.")
    else:
        linhas.append(f"- ✏️ RENOMEAR: o Discord **RECUSOU** — HTTP {st} · {_erro(corpo)}")

    st, corpo = await api.pedir("DELETE", f"/guilds/{gid}/roles/{rid}")
    dados["apagar"] = {"status": st, "corpo": _erro(corpo) if st >= 400 else "ok"}
    apagado = st in (200, 204)
    if apagado:
        linhas.append("- 🗑️ **APAGAR: o Discord ACEITOU** o cargo criado por mim.")
        dados["sobra"] = None
        linhas.append("")
        return {"linhas": linhas, "dados": dados}
    linhas.append(f"- 🗑️ APAGAR: o Discord **RECUSOU** — HTTP {st} · {_erro(corpo)}")

    st, corpo = await api.pedir("PATCH", f"/guilds/{gid}/roles",
                                json=[{"id": rid, "position": 0}])
    dados["mover_para_0"] = {"status": st, "corpo": _erro(corpo) if st >= 400 else "ok"}
    if st < 400:
        linhas.append("- ⬇️ Mover para a posição 0: o Discord ACEITOU.")
        st, corpo = await api.pedir("DELETE", f"/guilds/{gid}/roles/{rid}")
        dados["apagar_apos_mover"] = {"status": st, "corpo": _erro(corpo) if st >= 400 else "ok"}
        if st in (200, 204):
            linhas.append("- 🗑️ Depois de mover para baixo, **APAGAR funcionou** — a regra é "
                          "de posição, e o cargo do bot precisa estar acima.")
            dados["sobra"] = None
            linhas.append("")
            return {"linhas": linhas, "dados": dados}
        linhas.append(f"- 🗑️ Apagar depois de mover: recusado de novo — HTTP {st} · {_erro(corpo)}")
    else:
        linhas.append(f"- ⬇️ Mover para a posição 0: recusado — HTTP {st} · {_erro(corpo)}")

    dados["sobra"] = {"id": rid, "nome": nome, "posicao": pos_criado}
    linhas.append(f"- ⚠️ **Sobrou o cargo de teste** `{rid}` ({nome}) na posição {pos_criado}: "
                  "o Discord não me deixou nem editar nem apagar o que eu mesma criei.")
    linhas.append("")
    return {"linhas": linhas, "dados": dados}


def main() -> int:
    parser = argparse.ArgumentParser(description="Sonda de hierarquia de cargos (API crua).")
    parser.add_argument("--outdir", default="reports", help="onde gravar sonda-hierarquia.*")
    parser.add_argument("--guild-id", dest="guild_id",
                        default=os.environ.get("SONDA_GUILD_ID")
                        or os.environ.get("E2E_GUILD_ID") or None)
    args = parser.parse_args()
    return asyncio.run(sondar(args.guild_id, Path(args.outdir)))


if __name__ == "__main__":
    sys.exit(main())
