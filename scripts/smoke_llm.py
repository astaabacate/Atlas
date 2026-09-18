#!/usr/bin/env python3
"""Sonda AO VIVO dos provedores LLM usados pelo Farol.

O script é intencionalmente livre de tokens no log: as chaves entram somente por
variáveis de ambiente/secrets do GitHub Actions e qualquer trecho que coincida com
um segredo conhecido é mascarado antes de imprimir erros.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time
import aiohttp
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from llm.auto import AutoProvider
from llm.base import ProviderError, compact_error_text
from llm.free_providers import (
    KNOWN_GATEWAYS,
    OpenAICompatibleHttpProvider,
    _extract_model_ids,
    build_gateway_provider,
    descrever_pool,
    relatorio_do_pool,
)
from llm.key_providers import AnthropicProvider

# Gateways que NÃO fazem parte do pool gratuito (pagos ou de avaliação): entram na sonda
# apenas quando existe chave cadastrada, para o relatório ficar completo.
GATEWAY_ORDER = [
    "deepseek",
    "openai",
    "anthropic",
    "opencode-zen",
]

# Schema mínimo: força provedores com function calling nativo a evidenciarem tool_calls.
SMOKE_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "smoke_probe",
            "description": "Registra que o provedor recebeu e entendeu o schema de ferramenta.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean", "description": "true quando o teste funcionou"},
                    "note": {"type": "string", "description": "observação curta"},
                },
                "required": ["ok"],
            },
        },
    }
]

TEXTO_MESSAGES = [
    {
        "role": "user",
        "content": "Responda apenas com a palavra OK, em português, sem ferramentas.",
    },
]

CONSECUTIVAS_MESSAGES = [
    {"role": "user", "content": "Responda apenas OK."},
]

SMOKE_MESSAGES = [
    {
        "role": "system",
        "content": (
            "Você é uma sonda técnica. Se houver uma ferramenta disponível, chame "
            "smoke_probe com ok=true. Se a conexão não permitir ferramenta nativa, "
            "responda apenas OK."
        ),
    },
    {"role": "user", "content": "Execute uma chamada mínima de teste agora."},
]


@dataclass
class ProviderEntry:
    provider: Any
    origin: str


@dataclass
class ProbeResult:
    name: str
    origin: str
    status: str
    model: str
    latency_ms: int
    native_tool_call: bool
    error: str
    catalogo: str = "-"
    catalogo_status: str = "-"
    catalogo_qtd: int = 0
    consecutivas: str = "-"
    texto_puro: bool = False
    retry_after: str = ""

    @property
    def aprovado(self) -> bool:
        """🟢 = respondeu o chat, catálogo alcançável e nenhum 429 nas chamadas seguidas.

        Uma oscilação de rede no meio das consecutivas não reprova o corredor (o modelo já
        provou responder); 429/vazio sim, porque aí o pool não contaria com ele.
        """
        if self.status != "200" or self.error:
            return False
        if self.catalogo_status not in {"200", "vazio", "sem endpoint"}:
            return False
        if "429" in self.consecutivas:
            return False
        return "200" in self.consecutivas or self.consecutivas == "-"


def truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "sim", "on"}


def parse_models(raw: str | None) -> list[str]:
    return [part.strip() for part in re.split(r"[,\n]", raw or "") if part.strip()]


def short_cell(value: str, limit: int = 180) -> str:
    value = (value or "-").replace("\n", " ").replace("|", "/")
    value = re.sub(r"\s+", " ", value).strip() or "-"
    if len(value) > limit:
        value = value[: limit - 1].rstrip() + "…"
    return value


def known_secret_values(env: dict[str, str]) -> list[str]:
    names = {
        "LLM_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "DEEPSEEK_API_KEY",
        "CEREBRAS_API_KEY",
        "MISTRAL_API_KEY",
        "OPENCODE_API_KEY",
        "NVIDIA_API_KEY",
        "ZAI_API_KEY",
        "OLLAMA_API_KEY",
        "ZENMUX_API_KEY",
        "MODELSCOPE_API_KEY",
        "SILICONFLOW_API_KEY",
        "COHERE_API_KEY",
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
    }
    return sorted({env.get(name, "") for name in names if len(env.get(name, "")) >= 8}, key=len, reverse=True)


def redact(text: str, secrets: list[str]) -> str:
    redacted = text or ""
    for secret in secrets:
        redacted = redacted.replace(secret, "***")
    return redacted


def maybe_mask_in_actions(secrets: list[str]) -> None:
    # Defesa em profundidade: o GitHub já mascara secrets, mas também registramos máscaras
    # para qualquer chave repassada via env customizado.
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    for secret in secrets:
        print(f"::add-mask::{secret}")


def provider_model_hint(provider: Any) -> str:
    models = getattr(provider, "models", None)
    if models:
        return str(models[0])
    return str(getattr(provider, "model", ""))


def provider_identity(provider: Any) -> tuple[str, str, str]:
    endpoint = getattr(provider, "endpoint_url", "") or getattr(provider, "base_url", "")
    models = getattr(provider, "models", None)
    model_text = ",".join(models or [getattr(provider, "model", "")])
    return (str(getattr(provider, "name", "?")), str(endpoint), model_text)


def add_unique(entries: list[ProviderEntry], seen: set[tuple[str, str, str]], provider: Any, origin: str) -> None:
    ident = provider_identity(provider)
    if ident in seen:
        return
    seen.add(ident)
    entries.append(ProviderEntry(provider=provider, origin=origin))


def configured_gateway_key(provider: str, env: dict[str, str]) -> str:
    meta = KNOWN_GATEWAYS.get(provider, {})
    key_env = meta.get("key_env", f"{provider.upper().replace('-', '_')}_API_KEY")
    return (env.get(key_env, "") or "").strip()


def build_entries(env: dict[str, str]) -> tuple[list[ProviderEntry], list[str]]:
    """Monta corredores do AutoProvider + gateways com secret dedicado cadastrado."""
    entries: list[ProviderEntry] = []
    seen: set[tuple[str, str, str]] = set()
    setup_errors: list[str] = []

    try:
        auto = AutoProvider.create_default(
            api_key=env.get("LLM_API_KEY", "").strip(),
            custom_provider=env.get("LLM_PROVIDER", "auto"),
            custom_model=env.get("LLM_MODEL", ""),
            custom_base_url=env.get("LLM_BASE_URL", ""),
            custom_models=parse_models(env.get("LLM_MODELS", "")),
            disable_free=truthy(env.get("DISABLE_FREE_LLMS")),
            env=env,
        )
        for provider in auto.providers:
            add_unique(entries, seen, provider, "AutoProvider.create_default")
    except Exception as exc:  # noqa: BLE001 - sonda deve continuar e reportar configuração ruim
        setup_errors.append(f"AutoProvider.create_default: {compact_error_text(str(exc), 220)}")

    configured_provider = (env.get("LLM_PROVIDER", "") or "").strip().lower()
    llm_key = (env.get("LLM_API_KEY", "") or "").strip()
    custom_models = parse_models(env.get("LLM_MODELS", ""))

    for name in GATEWAY_ORDER:
        meta = KNOWN_GATEWAYS.get(name, {})
        dedicated_key = configured_gateway_key(name, env) if name != "anthropic" else (env.get("ANTHROPIC_API_KEY", "") or "").strip()
        uses_generic_key = bool(llm_key and configured_provider == name)
        if not dedicated_key and not uses_generic_key:
            continue

        api_key = dedicated_key or llm_key
        model = env.get("LLM_MODEL", "") if configured_provider == name else ""
        base_url = env.get("LLM_BASE_URL", "") if configured_provider == name else ""
        models = custom_models if configured_provider == name and custom_models else None

        try:
            if name == "anthropic":
                provider = AnthropicProvider(
                    api_key=api_key,
                    model=model or "claude-3-5-haiku-20241022",
                    base_url=base_url or "https://api.anthropic.com/v1",
                )
            else:
                provider = build_gateway_provider(
                    provider=name,
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                    models=models,
                    env=env,
                )
            add_unique(entries, seen, provider, f"gateway secret {name}")
        except Exception as exc:  # noqa: BLE001
            setup_errors.append(f"{name}: {compact_error_text(str(exc), 220)}")

    return entries, setup_errors


def install_openai_compatible_tracker(provider: Any) -> None:
    """Rastreia status/modelo sem alterar o contrato de produção do provider."""
    if not isinstance(provider, OpenAICompatibleHttpProvider) or getattr(provider, "_smoke_tracker", False):
        return

    original_post = provider._post
    provider._smoke_tracker = True
    provider._smoke_status = "-"
    provider._smoke_model = provider_model_hint(provider)

    async def tracked_post(session: Any, payload: dict[str, Any], headers: dict[str, str], client_timeout: Any, model: str) -> Any:
        provider._smoke_model = model
        try:
            result = await original_post(session, payload, headers, client_timeout, model)
            provider._smoke_status = "200"
            provider._smoke_model = model
            return result
        except ProviderError as exc:
            provider._smoke_status = str(exc.status or "-")
            provider._smoke_model = exc.model or model
            raise

    provider._post = tracked_post  # type: ignore[method-assign]


FICHA_POR_NOME = {spec.nome: spec for spec, _ in relatorio_do_pool({})}


def descrever_catalogo(provider: Any) -> str:  # noqa: D401 - usado no relatório
    """Mostra, na sonda, o efeito da auto-descoberta de modelos e do castigo por 429."""
    modelos = getattr(provider, "models", None)
    configurados = getattr(provider, "configured_models", None)
    partes: list[str] = []
    if isinstance(modelos, list) and modelos:
        partes.append(f"{len(modelos)} modelo(s)")
        if isinstance(configurados, list) and configurados and list(modelos) != list(configurados):
            partes.append("catálogo atualizado")
    if getattr(provider, "cooling_down", False):
        partes.append("de castigo (429)")
    return " · ".join(partes) if partes else "-"


def extract_status_from_error(text: str) -> str:
    match = re.search(r"(?:HTTP|error)\s+(\d{3})", text, flags=re.IGNORECASE)
    return match.group(1) if match else "-"


async def sondar_catalogo(provider: Any, timeout: float, secrets: list[str]) -> tuple[str, int, str]:
    """GET cru no catálogo de modelos.

    Faz a requisição aqui (e não via `refresh_models`) para o status ser REAL: o provedor
    engole erro de rede de propósito, o que esconderia um catálogo inacessível na sonda.
    """
    url = str(getattr(provider, "models_url", "") or "")
    if not url:
        return "sem endpoint", 0, ""
    headers = dict(getattr(provider, "headers", {}) or {})
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status != 200:
                    corpo = await resp.text()
                    return str(resp.status), 0, compact_error_text(redact(corpo, secrets), 120)
                data = await resp.json(content_type=None)
        ids = _extract_model_ids(data)
        refresh = getattr(provider, "refresh_models", None)
        if callable(refresh):
            try:
                await refresh(force=True)
            except Exception:  # noqa: BLE001 - a descoberta é otimização
                pass
        return "200", len(ids), ""
    except Exception as exc:  # noqa: BLE001 - vira coluna de diagnóstico
        return "-", 0, compact_error_text(redact(f"{type(exc).__name__}: {exc}", secrets), 120)


async def probe(entry: ProviderEntry, timeout: float, secrets: list[str]) -> ProbeResult:
    """Protocolo obrigatório da sonda, na ordem:

    1. GET do catálogo (`/models`) — prova que a URL e a credencial valem algo;
    2. POST `/chat/completions` em português, com ferramenta — prova o caminho real do Farol;
    3. três chamadas consecutivas — registra 429/Retry-After sem abusar de cota;
    4. chamada sem ferramentas — prova o fallback textual (quando o provedor recusa schema).
    """
    provider = entry.provider
    name = str(getattr(provider, "name", "?"))
    install_openai_compatible_tracker(provider)
    started = time.perf_counter()
    status = "-"
    model = provider_model_hint(provider) or "-"
    native = False
    error = ""
    catalogo_status = "sem endpoint"
    catalogo_qtd = 0
    consecutivas = "-"
    texto_puro = False
    retry_after = ""

    # 1) catálogo /models (GET cru, status real)
    catalogo_status, catalogo_qtd, erro_catalogo = await sondar_catalogo(provider, timeout, secrets)
    if erro_catalogo and not error:
        error = f"catálogo: {erro_catalogo}"

    # 2) POST /chat/completions em PT, com tools
    try:
        response = await provider.chat(
            messages=SMOKE_MESSAGES,
            tools=SMOKE_TOOLS,
            timeout=timeout,
            max_tokens=96,
        )
        status = str(getattr(provider, "_smoke_status", "200") or "200")
        model = str(getattr(provider, "_smoke_model", "") or model or "-")
        native = bool(getattr(response, "has_tool_calls", False))
        if not (response.content or response.has_tool_calls):
            error = "resposta vazia"
    except ProviderError as exc:
        status = str(exc.status or getattr(provider, "_smoke_status", "-") or "-")
        model = str(exc.model or getattr(provider, "_smoke_model", "") or model or "-")
        error = compact_error_text(redact(str(exc), secrets), 220)
        if exc.status == 429:
            retry_after = str(exc.retry_after or "")
    except Exception as exc:  # noqa: BLE001 - qualquer exceção vira linha de diagnóstico
        status = extract_status_from_error(str(exc))
        model = str(getattr(provider, "_smoke_model", "") or model or "-")
        error = compact_error_text(redact(f"{type(exc).__name__}: {exc}", secrets), 220)

    # 3) três chamadas consecutivas (sem abuso: 3 requisições, só se a primeira respondeu)
    if status == "200" and not error:
        marcas: list[str] = []
        for _ in range(3):
            try:
                # max_tokens generoso de propósito: com pouco token um modelo de raciocínio
                # devolve conteúdo vazio e a sonda acusaria falha do provedor sem ser.
                await provider.chat(messages=CONSECUTIVAS_MESSAGES, timeout=timeout, max_tokens=64)
                marcas.append(str(getattr(provider, "_smoke_status", "200") or "200"))
            except ProviderError as exc:
                marca = str(exc.status or "sem-status")
                if not exc.status and "vazia" in str(exc):
                    marca = "vazio"
                marcas.append(marca)
                if exc.status == 429:
                    retry_after = str(exc.retry_after or "")
                    break
            except Exception as exc:  # noqa: BLE001 - a marca diz qual falha foi
                marcas.append(f"ex:{type(exc).__name__}")
                break
        consecutivas = "/".join(marcas) if marcas else "-"

        # 4) fallback textual: mesma pergunta, sem tools
        try:
            texto = await provider.chat(messages=TEXTO_MESSAGES, timeout=timeout, max_tokens=32)
            texto_puro = bool((texto.content or "").strip())
        except Exception:  # noqa: BLE001 - o fallback textual é informativo
            texto_puro = False

    try:
        await provider.close()
    except Exception:
        pass

    latency_ms = int((time.perf_counter() - started) * 1000)
    return ProbeResult(
        name=name,
        origin=entry.origin,
        status=status,
        model=model,
        latency_ms=latency_ms,
        native_tool_call=native,
        error=error,
        catalogo=descrever_catalogo(provider),
        catalogo_status=catalogo_status,
        catalogo_qtd=catalogo_qtd,
        consecutivas=consecutivas,
        texto_puro=texto_puro,
        retry_after=retry_after,
    )


class Relatorio:
    """Coleta o que é impresso para também gravar o relatório em arquivo/CI."""

    def __init__(self) -> None:
        self.linhas: list[str] = []

    def print(self, *partes: Any, **kwargs: Any) -> None:
        texto = " ".join(str(p) for p in partes)
        self.linhas.append(texto)
        print(*partes, **kwargs)

    def salvar(self, destino: str) -> None:
        if not destino:
            return
        path = Path(destino)
        path.parent.mkdir(parents=True, exist_ok=True)
        cabecalho = [
            "# 🛰️ Sonda ao vivo dos provedores LLM",
            "",
            f"- executada em: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
            f"- python: {sys.version.split()[0]}",
            "",
        ]
        path.write_text("\n".join(cabecalho + self.linhas) + "\n", encoding="utf-8")


async def run(timeout: float, concurrency: int, out: str = "") -> int:
    relatorio = Relatorio()
    env = dict(os.environ)
    secrets = known_secret_values(env)
    maybe_mask_in_actions(secrets)

    entries, setup_errors = build_entries(env)
    if setup_errors:
        relatorio.print("Erros de montagem de provedores:")
        for err in setup_errors:
            relatorio.print(f"- {short_cell(redact(err, secrets), 260)}")
        relatorio.print()

    ativos, faltando = descrever_pool(env)
    relatorio.print(f"Pool gratuito ativo: {ativos or '(nenhum)'}")
    if faltando:
        relatorio.print("Fora do pool por falta de credencial (cadastre como secret para ativar):")
        for item in faltando:
            relatorio.print(f"- {item}")
    relatorio.print()

    if not entries:
        relatorio.print("Nenhum provedor configurado para a smoke.")
        relatorio.salvar(out)
        return 1

    relatorio.print("Corredores sondados: " + ", ".join(f"{getattr(e.provider, 'name', '?')} ({e.origin})" for e in entries))
    relatorio.print()

    sem = asyncio.Semaphore(max(1, concurrency))

    async def guarded(entry: ProviderEntry) -> ProbeResult:
        async with sem:
            return await probe(entry, timeout=timeout, secrets=secrets)

    results = await asyncio.gather(*(guarded(entry) for entry in entries))

    relatorio.print("| corredor | status HTTP | modelo que respondeu | latência | tool_call nativo? | contexto | cota | erro compactado |")
    relatorio.print("|---|---:|---|---:|:---:|---|---|---|")
    for result in results:
        relatorio.print(
            "| "
            + " | ".join(
                [
                    short_cell(result.name),
                    short_cell(result.status),
                    short_cell(result.model, 80),
                    f"{result.latency_ms} ms",
                    "sim" if result.native_tool_call else "não",
                    short_cell(getattr(FICHA_POR_NOME.get(result.name), "contexto", "") or "-", 40),
                    short_cell(getattr(FICHA_POR_NOME.get(result.name), "cota", "") or "-", 60),
                    short_cell(result.error or "-", 200),
                ]
            )
            + " |"
        )

    relatorio.print()
    relatorio.print("Protocolo obrigatório (GET /models → POST /chat/completions PT + tools → consecutivas → texto puro):")
    relatorio.print()
    relatorio.print("| corredor | GET /models | nº modelos | chat PT | tools nativo | fallback textual | 3 consecutivas | Retry-After |")
    relatorio.print("|---|---|---:|---|---|---|---|---|")
    for result in results:
        relatorio.print(
            "| "
            + " | ".join(
                [
                    short_cell(result.name),
                    short_cell(result.catalogo_status),
                    str(result.catalogo_qtd or "-"),
                    "200" if result.status == "200" and not result.error else result.status,
                    "sim" if result.native_tool_call else "não",
                    "sim" if result.texto_puro else "não",
                    short_cell(result.consecutivas),
                    short_cell(result.retry_after or "-", 40),
                ]
            )
            + " |"
        )
    relatorio.print()

    successes = [r for r in results if r.status == "200" and not r.error]
    native_successes = [r for r in successes if r.native_tool_call]
    relatorio.print()
    relatorio.print(f"Resumo: {len(successes)}/{len(results)} provedores responderam; {len(native_successes)} com tool_call nativo.")
    aprovados = [r for r in successes if r.aprovado]
    if aprovados:
        relatorio.print("🟢 TESTADOS E FUNCIONANDO AGORA (protocolo completo): "
              + ", ".join(f"{r.name} ({r.model})" for r in aprovados))
    parciais = [r for r in successes if not r.aprovado]
    if parciais:
        relatorio.print("🟡 RESPONDERAM, MAS COM RESSALVA NESTA RODADA: "
              + ", ".join(f"{r.name} (catálogo={r.catalogo_status}, consecutivas={r.consecutivas})" for r in parciais))
    falharam = [r for r in results if r not in successes]
    if falharam:
        relatorio.print("🔴 não responderam nesta rodada: " + ", ".join(f"{r.name}" for r in falharam))
    relatorio.salvar(out)
    return 0 if successes else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Sonda live dos provedores LLM do Farol")
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("SMOKE_TIMEOUT", "30")))
    parser.add_argument("--concurrency", type=int, default=int(os.environ.get("SMOKE_CONCURRENCY", "4")))
    parser.add_argument("--out", default=os.environ.get("SMOKE_OUT", ""),
                        help="grava o relatório em markdown neste caminho (usado no CI)")
    args = parser.parse_args()
    return asyncio.run(run(timeout=args.timeout, concurrency=args.concurrency, out=args.out))


if __name__ == "__main__":
    raise SystemExit(main())
