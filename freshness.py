"""
Guarda de obsolescência: verifica se o checkout atual ainda é a ponta do ramo remoto.
Evita que uma run enfileirada no GitHub Actions execute código antigo.
"""

from __future__ import annotations

import os
import subprocess
import sys


def check_freshness(
    current_sha: str | None = None,
    branch: str | None = None,
    repo_url: str | None = None,
    runner=subprocess.run,
) -> bool:
    """
    Compara o commit atual com a ponta do ramo remoto via git ls-remote.
    - Se for a ponta: retorna True.
    - Se o commit for obsoleto: sys.exit(1).
    - Se a rede falhar ou o ramo for desconhecido: imprime ::warning:: e retorna True.
    """
    sha = current_sha or os.environ.get("GITHUB_SHA", "")
    if not sha:
        try:
            res = runner(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                sha = res.stdout.strip()
        except Exception:
            sha = ""

    ref = branch or os.environ.get("GITHUB_REF_NAME", "")
    if not ref:
        try:
            res = runner(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                ref = res.stdout.strip()
        except Exception:
            ref = "main"

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    url = repo_url or (f"https://github.com/{repo}.git" if repo else "origin")

    try:
        res = runner(
            ["git", "ls-remote", "--heads", url, ref],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if res.returncode != 0:
            print("::warning::Falha ao verificar ponta remota (erro de rede ou git). Prosseguindo.")
            return True

        out = res.stdout.strip()
        if not out:
            print(f"::warning::Ramo '{ref}' não encontrado no repositório remoto. Prosseguindo.")
            return True

        remote_sha = out.split()[0]
        if sha and remote_sha:
            if not sha.startswith(remote_sha) and not remote_sha.startswith(sha):
                print(
                    f"::error::Checkout obsoleto! Commit local {sha[:7]} != ponta remota "
                    f"{remote_sha[:7]} no ramo {ref}. Abortando para evitar executar código antigo."
                )
                sys.exit(1)

        print(f"Checkout atualizado: {sha[:7] if sha else 'desconhecido'} é a ponta de {ref}. Prosseguindo.")
        return True

    except subprocess.TimeoutExpired:
        print("::warning::Timeout ao conectar ao repositório remoto para verificar frescor. Prosseguindo.")
        return True
    except Exception as exc:
        print(f"::warning::Erro na verificação de frescor ({exc}). Prosseguindo.")
        return True


if __name__ == "__main__":
    check_freshness()
