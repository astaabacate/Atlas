#!/usr/bin/env python3
"""
Harness de teste do Farol — offline (duplos de teste) e AO VIVO (Discord + LLM reais).

Cada verificação vira uma linha do relatório com status PASS/FAIL/WARN/SKIP, detalhe e
tempo. O relatório sai em JSON + Markdown; em GitHub Actions também vira anotação de
check-run (::error::/::warning::) e Step Summary.

Fases:
  static  — coerência entre os schemas das 27 ferramentas e os executores (offline)
  spy     — "a ferramenta promete, a ferramenta faz?": duplos de teste que registram
            chamadas de API. Detecta sucesso falso (retorna ✅ sem tocar no Discord). (offline)
  policy  — permissões do autor/bot, hierarquia de cargos e trava de confirmação. (offline)
  connect — login + gateway com o DISCORD_TOKEN real
  audit   — permissões e hierarquia do bot em cada servidor (a causa nº1 de falha)
  tools   — ferramentas somente-leitura contra um servidor real (verificação via API)
  agent   — Agent + corrida de LLMs reais: prompt → ferramenta → resposta
  mutate  — cria/edita/apaga objetos REAIS de teste (só com --mutate) e limpa tudo
  botloop — instancia o core.bot.FarolBot de produção e aciona on_message de verdade
  sweep   — remove sobras de teste marcadas com 🧪

Segurança das mutações (só rodam com --mutate):
  * Antes/depois de cada operação o harness lê o estado real pela API (REST) do Discord.
  * Só entra no "registro de posse" o objeto que apareceu nesse intervalo E cujo nome tem a
    marca 🧪 ou está na lista de nomes que o próprio teste pediu para criar.
  * A limpeza recusa tocar em qualquer objeto fora do registro de posse (guarda dura).
  * Operações de identidade do servidor (nome/ícone) nunca são executadas no servidor real.

Uso:
  python scripts/e2e_live.py --phases static,spy,policy --outdir reports/parts --tag offline
  python scripts/e2e_live.py --phases connect,audit  --outdir reports/parts --tag live
  python scripts/e2e_live.py --phases tools,agent    --outdir reports/parts --tag tools
  python scripts/e2e_live.py --phases mutate,botloop --mutate --outdir reports/parts --tag mutate
  python scripts/e2e_live.py --phases sweep          --mutate --outdir reports/parts --tag sweep
  python scripts/e2e_live.py --merge reports/parts --outdir reports
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import inspect
import itertools
import json
import logging
import os
import platform
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEMP_MARK = "🧪"
PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"

PHASE_ORDER = ("static", "spy", "policy", "connect", "audit", "tools", "agent", "mutate", "botloop", "sweep")

PHASE_TITLES = {
    "static": "Checagens estáticas (schemas ↔ executores)",
    "spy": "Duplos de teste: a ferramenta promete, a ferramenta faz?",
    "policy": "Política de permissões e confirmação destrutiva",
    "connect": "Conexão ao gateway do Discord",
    "audit": "Diagnóstico de permissões e hierarquia no servidor",
    "tools": "Ferramentas somente-leitura em servidor real",
    "agent": "Agente + LLM ao vivo (prompt → ferramenta → resposta)",
    "mutate": "Mutações reais em objetos de teste (com limpeza)",
    "botloop": "core.bot.FarolBot: on_message → resposta real no Discord",
    "sweep": "Varredura de sobras de teste",
}

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("farol.e2e")


# --------------------------------------------------------------------------- reporter


@dataclass
class Check:
    phase: str
    name: str
    status: str
    detail: str = ""
    ms: int = 0
    data: dict[str, Any] = field(default_factory=dict)


class Reporter:
    def __init__(self, phases: Iterable[str], meta: dict[str, Any] | None = None) -> None:
        self.phases: dict[str, list[Check]] = {p: [] for p in phases}
        self.meta = dict(meta or {})
        self.started = datetime.now(timezone.utc)
        self.notes: list[str] = []

    def record(self, phase: str, name: str, status: str, detail: str = "", ms: int = 0, **data: Any) -> Check:
        self.phases.setdefault(phase, [])
        check = Check(phase=phase, name=name, status=status, detail=detail, ms=int(ms), data=data)
        self.phases[phase].append(check)
        icon = {PASS: "✅", FAIL: "❌", WARN: "⚠️", SKIP: "⏭️"}.get(status, "•")
        line = f"  {icon} [{status}] {phase}/{name}"
        if detail:
            line += f" — {detail}"
        print(line, flush=True)
        return check

    def had(self, phase: str, name: str, status: str) -> bool:
        return any(c.name == name and c.status == status for c in self.phases.get(phase, []))

    def note(self, text: str) -> None:
        self.notes.append(text)
        print(f"  ℹ️  {text}", flush=True)

    def counts(self) -> dict[str, int]:
        out = {PASS: 0, FAIL: 0, WARN: 0, SKIP: 0}
        for checks in self.phases.values():
            for c in checks:
                out[c.status] = out.get(c.status, 0) + 1
        return out

    def phase_counts(self, phase: str) -> dict[str, int]:
        out = {PASS: 0, FAIL: 0, WARN: 0, SKIP: 0}
        for c in self.phases.get(phase, []):
            out[c.status] = out.get(c.status, 0) + 1
        return out

    def exit_code(self) -> int:
        return 1 if self.counts()[FAIL] else 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "started_at": self.started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "meta": self.meta,
            "summary": self.counts(),
            "notes": self.notes,
            "phases": {
                phase: {"title": PHASE_TITLES.get(phase, phase), "checks": [c.__dict__ for c in checks]}
                for phase, checks in self.phases.items()
            },
        }

    def to_markdown(self) -> str:
        counts = self.counts()
        lines = [
            "# 🏮 Farol — relatório de teste E2E",
            "",
            f"- **Resumo:** ✅ {counts[PASS]} · ❌ {counts[FAIL]} · ⚠️ {counts[WARN]} · ⏭️ {counts[SKIP]}",
        ]
        for key, value in self.meta.items():
            lines.append(f"- **{key}:** {value}")
        if self.notes:
            lines += ["", "## Anotações"] + [f"- {n}" for n in self.notes]

        for phase in list(PHASE_ORDER) + [p for p in self.phases if p not in PHASE_ORDER]:
            checks = self.phases.get(phase) or []
            if not checks:
                continue
            pc = self.phase_counts(phase)
            lines += [
                "",
                f"## {PHASE_TITLES.get(phase, phase)}",
                f"`{phase}` — ✅ {pc[PASS]} · ❌ {pc[FAIL]} · ⚠️ {pc[WARN]} · ⏭️ {pc[SKIP]}",
                "",
                "| Status | Verificação | Detalhe |",
                "| --- | --- | --- |",
            ]
            for c in checks:
                detail = (c.detail or "").replace("|", "\\|").replace("\n", " ")
                if len(detail) > 400:
                    detail = detail[:399] + "…"
                lines.append(f"| {c.status} | `{c.name}` | {detail} |")
        return "\n".join(lines) + "\n"

    def emit_annotations(self) -> None:
        """Publica erros/avisos como anotações de check-run (limite do GitHub: 10 de cada)."""
        fails = [c for checks in self.phases.values() for c in checks if c.status == FAIL]
        warns = [c for checks in self.phases.values() for c in checks if c.status == WARN]
        for c in fails[:10]:
            print(f"::error title=e2e {c.phase}/{c.name}::{' '.join((c.detail or '').split())[:900]}", flush=True)
        for c in warns[:10]:
            print(f"::warning title=e2e {c.phase}/{c.name}::{' '.join((c.detail or '').split())[:900]}", flush=True)
        counts = self.counts()
        print(
            f"::notice title=e2e resumo::✅ {counts[PASS]} passaram, ❌ {counts[FAIL]} falharam, "
            f"⚠️ {counts[WARN]} avisos, ⏭️ {counts[SKIP]} puladas.",
            flush=True,
        )
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            try:
                with open(summary_path, "a", encoding="utf-8") as fh:
                    fh.write(self.to_markdown() + "\n")
            except Exception as exc:  # pragma: no cover - infra do Actions
                log.warning("Não foi possível escrever o step summary: %s", exc)


# --------------------------------------------------------------- duplos de teste


class FakePerms:
    """Permissões duck-typed para os testes offline de política."""

    def __init__(self, **flags: bool) -> None:
        self.administrator = bool(flags.pop("administrator", False))
        for name in ("manage_channels", "manage_roles", "manage_guild", "send_messages", "view_channel"):
            setattr(self, name, bool(flags.get(name, False)))

    def __repr__(self) -> str:
        flags = [n for n in ("administrator", "manage_channels", "manage_roles", "manage_guild")
                 if getattr(self, n, False)]
        return f"<Perms {','.join(flags) or 'nenhuma'}>"


class Spy:
    """Base dos objetos duplos: registra cada chamada de API."""

    _seq = 1000

    def __init__(self, name: str, **attrs: Any) -> None:
        Spy._seq += 1
        self.id = Spy._seq
        self.name = name
        self.calls: list[tuple[str, dict[str, Any]]] = []
        for key, value in attrs.items():
            setattr(self, key, value)

    def record(self, action: str, **kwargs: Any) -> None:
        self.calls.append((action, kwargs))

    def actions(self) -> list[str]:
        return [a for a, _ in self.calls]

    def __repr__(self) -> str:  # pragma: no cover - depuração
        return f"<Spy {type(self).__name__} {self.name}#{self.id}>"


class SpyRole(Spy):
    """Espelha a API do discord.Role: `managed` é atributo, `is_default()` é MÉTODO."""

    def __init__(self, name: str, position: int = 1, *, color: Any = None, hoist: bool = False,
                 mentionable: bool = False, managed: bool = False, is_default: bool = False) -> None:
        super().__init__(name, position=position, color=color, hoist=hoist,
                         mentionable=mentionable, managed=managed)
        self._default = is_default
        self.members: list[Any] = []

    def is_default(self) -> bool:
        return bool(self._default)

    def __str__(self) -> str:
        return f"@{self.name}"

    async def edit(self, **kwargs: Any) -> "SpyRole":
        self.record("edit", **kwargs)
        for key in ("name", "hoist", "mentionable", "position", "color"):
            if key in kwargs:
                setattr(self, key, kwargs[key])
        return self

    async def delete(self) -> None:
        self.record("delete")


class SpyMember(Spy):
    def __init__(self, name: str, perms: FakePerms | None = None, roles: list[SpyRole] | None = None,
                 bot: bool = False, **attrs: Any) -> None:
        super().__init__(name, bot=bot, **attrs)
        self.guild_permissions = perms or FakePerms(administrator=True)
        self.roles = list(roles or [])
        self.top_role = self.roles[0] if self.roles else SpyRole("@everyone", position=0)
        self.display_name = name
        self.nick = None

    async def add_roles(self, *roles: SpyRole, **kwargs: Any) -> None:
        self.record("add_roles", roles=[r.name for r in roles])
        self.roles.extend(roles)

    async def remove_roles(self, *roles: SpyRole, **kwargs: Any) -> None:
        self.record("remove_roles", roles=[r.name for r in roles])
        self.roles = [r for r in self.roles if r not in roles]


class SpyChannel(Spy):
    def __init__(self, name: str, guild: "SpyGuild | None" = None, category: Any = None,
                 type_name: str = "text", topic: str | None = None) -> None:
        super().__init__(name)
        self.guild = guild
        self.category = category
        self.topic = topic
        self.overwrites: dict[Any, Any] = {}
        self.slowmode_delay = 0
        self.nsfw = False
        self.position = 0
        self.type = type("ChannelType", (), {"name": type_name})()
        self.mention = f"<#{self.id}>"

    @property
    def category_id(self) -> int | None:
        return getattr(self.category, "id", None)

    async def edit(self, **kwargs: Any) -> "SpyChannel":
        self.record("edit", **kwargs)
        if "category" in kwargs:
            self.category = kwargs["category"]
        for key in ("name", "topic", "slowmode_delay", "nsfw"):
            if key in kwargs:
                setattr(self, key, kwargs[key])
        return self

    async def delete(self) -> None:
        self.record("delete")
        if self.guild is not None:
            self.guild.channels = [c for c in self.guild.channels if c is not self]

    async def set_permissions(self, target: Any, **kwargs: Any) -> None:
        self.record("set_permissions", target=getattr(target, "name", str(target)), **kwargs)
        if kwargs.get("overwrite", "ausente") is None:
            self.overwrites.pop(target, None)
        else:
            self.overwrites[target] = kwargs

    async def clone(self, **kwargs: Any) -> "SpyChannel":
        self.record("clone", **kwargs)
        clone = SpyChannel(kwargs.get("name", self.name), guild=self.guild, category=self.category,
                           type_name=self.type.name, topic=self.topic)
        clone.overwrites = dict(self.overwrites)
        if self.guild is not None:
            self.guild.channels.append(clone)
        return clone

    # Igual ao discord.py: a categoria INJETA category=self ao delegar para a guild.
    # Assim, passar `category` de novo estoura TypeError exatamente como em produção.
    async def create_text_channel(self, name: str, **options: Any) -> "SpyChannel":
        if self.guild is None:
            return SpyChannel(name)
        return await self.guild.create_text_channel(name, category=self, **options)

    async def create_voice_channel(self, name: str, **options: Any) -> "SpyChannel":
        if self.guild is None:
            return SpyChannel(name)
        return await self.guild.create_voice_channel(name, category=self, **options)


class SpyGuild(Spy):
    def __init__(self, name: str = "Servidor Spy") -> None:
        super().__init__(name)
        self.owner_id = 42
        self.member_count = 7
        self.icon = None
        self.description = ""
        self.created_at = None
        self.channels: list[SpyChannel] = []
        self.categories: list[SpyChannel] = []
        self.roles: list[SpyRole] = [SpyRole("@everyone", position=0, is_default=True), SpyRole("farol", position=5)]
        self.members: list[SpyMember] = [SpyMember("dono", roles=[SpyRole("Dono", position=9)])]
        self.me = SpyMember("farol", roles=[self.roles[1]])
        self.members.append(self.me)

    # ---- criadores (assinaturas fiéis ao discord.py: keyword-only, sem **kwargs frouxo)
    async def create_text_channel(self, name: str, *, overwrites: Any = None, category: Any = None,
                                  position: int = 0, topic: str | None = None, nsfw: bool = False,
                                  slowmode_delay: int = 0, default_auto_archive_duration: Any = None,
                                  reason: str | None = None, news: bool = False,
                                  default_thread_slowmode_delay: Any = None) -> SpyChannel:
        channel = SpyChannel(name, guild=self, category=category, topic=topic)
        channel.slowmode_delay = slowmode_delay
        channel.nsfw = nsfw
        self.record("create_text_channel", name=name, category=str(getattr(category, "name", "")))
        self.channels.append(channel)
        return channel

    async def create_voice_channel(self, name: str, *, overwrites: Any = None, category: Any = None,
                                   position: int = 0, bitrate: Any = None, user_limit: Any = None,
                                   rtc_region: Any = None, video_quality_mode: Any = None,
                                   reason: str | None = None) -> SpyChannel:
        channel = SpyChannel(name, guild=self, category=category, type_name="voice")
        self.record("create_voice_channel", name=name, category=str(getattr(category, "name", "")))
        self.channels.append(channel)
        return channel

    async def create_category(self, name: str, *, overwrites: Any = None, position: int = 0,
                              reason: str | None = None) -> SpyChannel:
        category = SpyChannel(name, guild=self, type_name="category")
        self.record("create_category", name=name)
        self.channels.append(category)
        self.categories.append(category)
        return category

    async def create_role(self, name: str, *, permissions: Any = None, colour: Any = None, color: Any = None,
                          hoist: bool = False, mentionable: bool = False, reason: str | None = None) -> SpyRole:
        role = SpyRole(name, position=1, color=color or colour, hoist=hoist, mentionable=mentionable)
        self.record("create_role", name=name)
        self.roles.append(role)
        return role

    async def edit(self, **kwargs: Any) -> "SpyGuild":
        self.record("edit", **kwargs)
        for key in ("name", "description", "icon"):
            if key in kwargs:
                setattr(self, key, kwargs[key])
        return self

    # ---- buscas
    def get_channel(self, cid: int) -> SpyChannel | None:
        return next((c for c in self.channels if c.id == cid), None)

    def get_role(self, rid: int) -> SpyRole | None:
        return next((r for r in self.roles if r.id == rid), None)

    def get_member(self, mid: int) -> SpyMember | None:
        return next((m for m in self.members if m.id == mid), None)

    async def fetch_roles(self) -> list[SpyRole]:
        return list(self.roles)

    async def fetch_channels(self) -> list[SpyChannel]:
        return list(self.channels)


# ------------------------------------------------------------------- contexto live


@dataclass
class LiveEnv:
    config: Any = None
    registry: Any = None
    llm: Any = None
    memory: Any = None
    agent: Any = None
    client: Any = None
    connect_task: Any = None
    guilds: list[Any] = field(default_factory=list)
    primary: Any = None
    actor: Any = None


class LLMRegistro:
    """
    Envolve o provedor de LLM para o relatório saber se o modelo chegou a PEDIR a ferramenta.

    Sem isso o harness confunde "modelo gratuito respondeu um resumo vago" com "o bot não obedeceu".
    """

    def __init__(self, wrapped: Any, registro: list[dict[str, Any]]) -> None:
        self.wrapped = wrapped
        self.registro = registro

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                   timeout: float = 60.0, max_tokens: int = 1024) -> Any:
        resp = await self.wrapped.chat(messages=messages, tools=tools, timeout=timeout, max_tokens=max_tokens)
        self.registro.append({
            "ferramentas_chamadas": [c.name for c in getattr(resp, "tool_calls", [])],
            "chars": len(resp.content or ""),
            "vencedor": getattr(self.wrapped, "last_winner", ""),
        })
        return resp

    def describe(self) -> str:
        return self.wrapped.describe()

    async def close(self) -> None:
        await self.wrapped.close()


# ----------------------------------------------------------------------- harness


class Harness:
    def __init__(self, args: argparse.Namespace, reporter: Reporter) -> None:
        self.args = args
        self.rep = reporter
        self.env = LiveEnv()
        self.owned_channels: set[int] = set()
        self.owned_roles: set[int] = set()

    # ----------------------------------------------------------- infra de checks
    async def check(self, phase: str, name: str, fn: Callable[[], Awaitable[Any]],
                    *, warn_on_error: bool = False, skip_when: str | None = None) -> Any:
        if skip_when:
            self.rep.record(phase, name, SKIP, skip_when)
            return None
        antes = len(self.rep.phases.get(phase, []))
        start = time.perf_counter()
        try:
            result = await fn()
        except AssertionError as exc:
            self.rep.record(phase, name, FAIL, str(exc) or "asserção falhou", self._ms(start))
            return None
        except Exception as exc:
            status = WARN if warn_on_error else FAIL
            self.rep.record(phase, name, status, f"{type(exc).__name__}: {exc}", self._ms(start))
            return None

        # Se a própria checagem já registrou WARN/SKIP para este nome (ex.: não conclusivo por
        # causa do LLM gratuito), não duplica como PASS — o relatório ficaria com duas linhas.
        proprios = self.rep.phases.get(phase, [])[antes:]
        if any(c.name == name and c.status in (WARN, SKIP, FAIL) for c in proprios):
            return result

        detail, data = self._unpack(result)
        self.rep.record(phase, name, PASS, detail, self._ms(start), **data)
        return result

    @staticmethod
    def _ms(start: float) -> int:
        return int((time.perf_counter() - start) * 1000)

    @staticmethod
    def _unpack(result: Any) -> tuple[str, dict[str, Any]]:
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
            return str(result[0]), result[1]
        return ("" if result is None else str(result)), {}

    @staticmethod
    def assert_true(condition: Any, message: str) -> None:
        if not condition:
            raise AssertionError(message)

    @staticmethod
    def _culpa_do_llm(resposta: str) -> bool:
        """
        True quando a resposta denuncia o PROVEDOR (gratuito) e não o bot: nenhum provedor
        respondeu, 429/rate limit, ou o agente terminou sem conteúdo útil.
        Sem chave paga isso é intermitente — o dono do projeto aceitou esse risco.
        """
        baixo = (resposta or "").lower()
        if any(t in baixo for t in ("operação concluída com sucesso", "operações concluídas")):
            return True
        if "nenhum dos" in baixo and "provedores" in baixo:
            return True
        # Mensagem amigável que o bot manda ao cliente quando a corrida de LLMs falha.
        if "fila cheia" in baixo or "não consegui falar com nenhum modelo" in baixo:
            return True
        # Trabalho feito, mas o resumo final caiu junto com a corrida de LLMs.
        if "não consegui escrever o resumo" in baixo or "modelos gratuitos ficaram instáveis" in baixo:
            return True
        return "rate limit" in baixo or "429" in baixo

    @staticmethod
    def llm_nao_chamou(registro: list[dict[str, Any]], ferramenta: str) -> bool:
        """True quando o modelo NUNCA pediu aquela ferramenta (culpa do modelo, não do bot)."""
        chamadas = [n for r in registro for n in r.get("ferramentas_chamadas", [])]
        return ferramenta not in chamadas

    def degradar_llm(self, phase: str, nome: str, esperado: str, resposta: str) -> str:
        """Registra WARN (não FAIL) quando o motivo é o LLM gratuito, mantendo a resposta crua."""
        self.rep.record(
            phase, nome, WARN,
            f"{esperado} — o provedor gratuito não cooperou nesta rodada ({resposta.strip()[:110]!r}). "
            "Sem chave de LLM paga isso é intermitente; rode de novo para conferir. "
            "(O comportamento do bot está coberto offline nas fases spy/policy e em tests/.)")
        return f"não conclusivo por causa do LLM gratuito: {esperado}"

    # ------------------------------------------------------------- infra ao vivo
    async def _build_live_stack(self) -> LiveEnv:
        from apis.base import ApiRegistry
        from brain.agent import Agent
        from brain.memory import ChannelMemory
        from config import Config
        from llm.auto import AutoProvider

        config = Config.from_env()
        registry = ApiRegistry(disabled_apis=config.disabled_apis, default_timeout=config.api_timeout)
        llm = AutoProvider.create_default(
            api_key=config.llm_api_key,
            custom_provider=config.llm_provider,
            custom_model=config.llm_model,
            custom_base_url=config.llm_base_url,
            custom_models=config.llm_models,
            disable_free=config.disable_free_llms,
        )
        memory = ChannelMemory(max_turns=config.history_len)
        agent = Agent(llm_provider=llm, memory=memory, max_tool_rounds=config.max_tool_rounds,
                      llm_timeout=config.llm_timeout, api_registry=registry)
        return LiveEnv(config=config, registry=registry, llm=llm, memory=memory, agent=agent)

    async def _connect(self) -> tuple[Any, Any]:
        """Login + gateway com as intents da configuração (igual ao main.py)."""
        import discord

        from core.bot import build_intents

        client = discord.Client(intents=build_intents(self.env.config))
        ready = asyncio.Event()

        @client.event
        async def on_ready() -> None:  # noqa: ANN202 - callback do discord.py
            ready.set()

        await asyncio.wait_for(client.login(self.env.config.discord_token), timeout=45)
        task = asyncio.create_task(client.connect(reconnect=False))
        await asyncio.wait_for(ready.wait(), timeout=self.args.connect_timeout)
        return client, task

    async def _connect_safe(self) -> tuple[Any, Any, str]:
        """Conecta; se as intents privilegiadas estiverem ligadas no papel e desligadas no
        portal, reconecta sem elas e devolve o motivo para o relatório."""
        import discord

        try:
            client, task = await self._connect()
            return client, task, ""
        except discord.PrivilegedIntentsRequired as exc:
            var = "MEMBERS_INTENT" if self.env.config.members_intent else "MESSAGE_CONTENT_INTENT"
            client = discord.Client(intents=discord.Intents(guilds=True, guild_messages=True, dm_messages=True))
            ready = asyncio.Event()

            @client.event
            async def on_ready() -> None:  # noqa: ANN202
                ready.set()

            await asyncio.wait_for(client.login(self.env.config.discord_token), timeout=45)
            task = asyncio.create_task(client.connect(reconnect=False))
            await asyncio.wait_for(ready.wait(), timeout=self.args.connect_timeout)
            return client, task, (
                f"{exc} — a variável {var} está ligada, mas a intent não está habilitada no Developer Portal "
                "(Bot → Privileged Gateway Intents). O bot REAL falharia ao subir assim; reconectei sem ela."
            )

    async def ensure_live(self, phase: str) -> LiveEnv | None:
        """Garante stack + conexão + servidor escolhido. Devolve None (e registra o motivo) se falhar."""
        if self.env.config is None:
            try:
                self.env = await self._build_live_stack()
            except Exception as exc:
                self.rep.record(phase, "conexão", FAIL, f"não consegui montar o stack: {type(exc).__name__}: {exc}")
                return None

        if self.env.client is None:
            start = time.perf_counter()
            try:
                client, task, motivo_intents = await self._connect_safe()
            except Exception as exc:
                self.rep.record(phase, "conexão", FAIL, f"{type(exc).__name__}: {exc}", self._ms(start))
                return None
            self.env.client, self.env.connect_task = client, task
            self.env.guilds = list(client.guilds)
            if motivo_intents:
                self.rep.record(phase, "intents privilegiadas", FAIL, motivo_intents, self._ms(start))
            self.rep.note(f"conectado como {client.user} em {len(client.guilds)} servidor(es)")

        if not self.env.guilds:
            self.rep.record(phase, "servidores", FAIL,
                            "o bot não está em nenhum servidor — convide-o (README Passo 2) para testar o resto")
            return None

        if self.env.primary is None:
            self.env.primary = self._pick_guild()
            self.env.actor = await self._resolve_actor(self.env.primary)
        return self.env

    def _pick_guild(self) -> Any:
        wanted = (self.args.guild_id or os.environ.get("E2E_GUILD_ID", "")).strip()
        if wanted.isdigit():
            chosen = next((g for g in self.env.guilds if g.id == int(wanted)), None)
            if chosen is not None:
                return chosen
            self.rep.note(f"servidor {wanted} não encontrado; usando o maior dos {len(self.env.guilds)}")
        return max(self.env.guilds, key=lambda g: getattr(g, "member_count", 0) or 0)

    async def _resolve_actor(self, guild: Any) -> Any:
        """Autor dos comandos: o dono do servidor (real) quando possível, senão o próprio bot."""
        owner_id = getattr(guild, "owner_id", None)
        if owner_id:
            member = guild.get_member(owner_id)
            if member is None:
                with contextlib.suppress(Exception):
                    member = await guild.fetch_member(owner_id)
            if member is not None and not getattr(member, "bot", False):
                return member
        return guild.me

    # =====================================================================
    # static
    # =====================================================================
    @staticmethod
    def _function_body(func: Any) -> str:
        """Devolve só o CORPO da função (sem assinatura), para achar parâmetro declarado e ignorado."""
        import ast
        import textwrap

        fonte = textwrap.dedent(inspect.getsource(func))
        arvore = ast.parse(fonte)
        no = arvore.body[0]
        if not isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)) or not no.body:
            return fonte
        offset = no.body[0].lineno - no.lineno
        return "\n".join(fonte.splitlines()[offset:])

    async def phase_static(self) -> None:
        from brain.executors import _OPS
        from brain.policy import TOOL_PERMISSIONS
        from brain.tools import TOOLS, tool_names

        phase = "static"

        async def schemas_and_ops_match() -> str:
            self.assert_true(set(tool_names()) == set(_OPS), "conjunto de schemas difere do conjunto de executores")
            return f"{len(TOOLS)} ferramentas e {len(_OPS)} executores casados"

        await self.check(phase, "27 ferramentas ↔ 27 executores", schemas_and_ops_match)

        async def signature_alignment() -> tuple[str, dict[str, Any]]:
            problemas, nao_usados = [], []
            for tool in TOOLS:
                op = _OPS[tool.name]
                params = set(inspect.signature(op).parameters) - {"ctx"}
                props = set(tool.parameters.get("properties", {}))
                required = set(tool.parameters.get("required", []))
                if props - params:
                    problemas.append(f"{tool.name}: schema envia {sorted(props - params)} e o executor descarta")
                if required - params:
                    problemas.append(f"{tool.name}: obrigatórios {sorted(required - params)} não existem na assinatura")
                corpo = self._function_body(op)
                for prop in sorted(props):
                    if not re.search(rf"\b{re.escape(prop)}\b", corpo):
                        nao_usados.append(f"{tool.name}.{prop}")
            if nao_usados:
                self.rep.record(phase, "parâmetros declarados e nunca usados", WARN,
                                f"o LLM pode preencher e o executor ignorar: {', '.join(nao_usados)}")
            self.assert_true(not problemas, "; ".join(problemas))
            return f"{len(TOOLS)} assinaturas conferem com os schemas", {}

        await self.check(phase, "assinaturas ↔ schemas", signature_alignment)

        async def permissions_declared() -> str:
            faltando = [t.name for t in TOOLS if t.name not in TOOL_PERMISSIONS]
            self.assert_true(not faltando, f"ferramentas sem política declarada: {faltando}")
            return f"as {len(TOOLS)} ferramentas têm política declarada"

        await self.check(phase, "toda ferramenta tem política", permissions_declared)

        async def schemas_well_formed() -> str:
            ruins = []
            for tool in TOOLS:
                if len(tool.description.strip()) < 15:
                    ruins.append(f"{tool.name}: descrição curta")
                if tool.parameters.get("type") != "object":
                    ruins.append(f"{tool.name}: schema não é object")
                for prop in tool.parameters.get("properties", {}).values():
                    if "type" not in prop and "enum" not in prop:
                        ruins.append(f"{tool.name}: propriedade sem type")
            self.assert_true(not ruins, "; ".join(ruins))
            return "descrições e schemas bem formados para function calling"

        await self.check(phase, "qualidade dos schemas enviados ao LLM", schemas_well_formed)

        async def prompt_rules() -> str:
            from brain.agent import SYSTEM_PROMPT_TEMPLATE

            obrigatorios = ("REGRAS ABSOLUTAS", "português", "Ações destrutivas",
                            "FORA DE ESCOPO", "{snapshot}", "{confirmacao}")
            faltando = [r for r in obrigatorios if r not in SYSTEM_PROMPT_TEMPLATE]
            self.assert_true(not faltando, f"prompt de sistema sem: {faltando}")
            direto = SYSTEM_PROMPT_TEMPLATE.format(snapshot="S", confirmacao="MODO DIRETO (padrão).")
            self.assert_true("MODO DIRETO" in direto, "o prompt não descreve o modo direto")
            return f"prompt com os {len(obrigatorios)} blocos obrigatórios (regra de confirmação dinâmica)"

        await self.check(phase, "prompt de sistema completo", prompt_rules)

        async def schema_size() -> str:
            from brain.agent import SYSTEM_PROMPT_TEMPLATE

            payload = json.dumps([t.to_openai() for t in TOOLS], ensure_ascii=False)
            self.assert_true(len(payload) < 40_000, f"schema com {len(payload)} chars pode estourar o contexto")
            return f"schema com {len(payload)} chars + prompt de {len(SYSTEM_PROMPT_TEMPLATE)} chars"

        await self.check(phase, "tamanho do payload enviado ao LLM", schema_size)

    # =====================================================================
    # spy
    # =====================================================================
    async def _spy_ctx(self) -> tuple[Any, SpyGuild, SpyChannel, SpyChannel]:
        from brain.tools import ToolContext

        guild = SpyGuild()
        category = await guild.create_category("categoria-spy")
        canal = await guild.create_text_channel("canal-spy", category=category)
        ctx = ToolContext(guild=guild, channel=canal, actor=guild.members[0], api_registry=None, memory=None)
        return ctx, guild, category, canal

    async def spy_check(self, phase: str, name: str, tool_name: str, args: dict[str, Any],
                        ctx: Any, guild: SpyGuild, target: Spy | None, action: str) -> str:
        from brain.executors import execute_tool

        guild.calls.clear()
        if target is not None:
            target.calls.clear()
        out = await execute_tool(tool_name, args, ctx)
        vistas = target.actions() if target is not None else guild.actions()
        if not any(a.startswith(action) for a in vistas):
            raise AssertionError(
                f"respondeu {str(out)[:70]!r} mas NÃO chamou {action}() — chamadas vistas: {vistas or 'nenhuma'}"
            )
        return f"chamou {action}() e respondeu {str(out)[:60]!r}"

    async def phase_spy(self) -> None:
        phase = "spy"
        ctx, guild, category, canal = await self._spy_ctx()
        cid, catid = str(canal.id), str(category.id)

        await self.check(phase, "create_channels cria na raiz de verdade",
                         lambda: self.spy_check(phase, "create_channels cria na raiz de verdade", "create_channels", {
                             "channels": [
                                 {"name": "novo-texto-raiz", "type": "text"},
                                 {"name": "nova-voz-raiz", "type": "voice"},
                                 {"name": "nova-categoria", "type": "category"},
                             ]}, ctx, guild, guild, "create_"))

        await self.check(phase, "create_channels cria DENTRO de categoria",
                         lambda: self.spy_check(phase, "create_channels cria DENTRO de categoria", "create_channels", {
                             "channels": [
                                 {"name": "dentro-texto", "type": "text", "category": catid},
                                 {"name": "dentro-voz", "type": "voice", "category": catid},
                             ]}, ctx, guild, guild, "create_"))

        await self.check(phase, "edit_channel edita de verdade",
                         lambda: self.spy_check(phase, "edit_channel edita de verdade", "edit_channel", {
                             "channel": cid, "name": "canal-renomeado", "topic": "novo tópico",
                             "slowmode_delay": 7, "nsfw": True}, ctx, guild, canal, "edit"))

        await self.check(phase, "move_channel move de verdade",
                         lambda: self.spy_check(phase, "move_channel move de verdade", "move_channel",
                                                {"channel": cid, "category": "none", "position": 3},
                                                ctx, guild, canal, "edit"))

        await self.check(phase, "clone_channel clona de verdade",
                         lambda: self.spy_check(phase, "clone_channel clona de verdade", "clone_channel",
                                                {"channel": cid, "name": "clone-spy"}, ctx, guild, canal, "clone"))

        await self.check(phase, "delete_channels apaga de verdade (1 canal)",
                         lambda: self.spy_check(phase, "delete_channels apaga de verdade (1 canal)",
                                                "delete_channels", {"channels": [cid]}, ctx, guild, canal, "delete"))

        await self.check(phase, "delete_channels em lote: modo direto apaga na hora",
                         self._spy_bulk_direto, skip_when=None)
        await self.check(phase, "delete_channels em lote: modo cauteloso pede confirmação",
                         self._spy_bulk_confirm, skip_when=None)

        await self.check(phase, "edit_server altera de verdade",
                         lambda: self.spy_check(phase, "edit_server altera de verdade", "edit_server",
                                                {"name": "Servidor Spy v2", "description": "d"}, ctx, guild, guild, "edit"))

        await self.check(phase, "set_icon altera de verdade (baixa a URL e envia os bytes)", self._spy_set_icon)
        await self.check(phase, "set_icon com estilo gera imagem sem rede", self._spy_set_icon_style)
        await self.check(phase, "set_icon NÃO mente quando o download falha", self._spy_set_icon_falha)

        await self.check(phase, "apply_template cria de verdade", self._spy_template)

        await self.check(phase, "import_structure cria de verdade",
                         lambda: self.spy_check(phase, "import_structure cria de verdade", "import_structure", {
                             "structure_json": json.dumps({
                                 "roles": [{"name": "Importado"}],
                                 "categories": [{"name": "Cat Import", "channels": [{"name": "imp-1"}]}]})},
                             ctx, guild, guild, "create_"))

        await self.check(phase, "cargos: criar/editar/dar/tirar/apagar de verdade", self._spy_roles, skip_when=None)
        await self.check(phase, "permissões: set/clear/sync tocam a API", self._spy_permissions, skip_when=None)
        await self.check(phase, "somente-leitura não muta nada", self._spy_readonly, skip_when=None)
        await self.check(phase, "conversation_clear limpa a memória", self._spy_clear_memory, skip_when=None)
        await self.check(phase, "conversa isolada por servidor (multi-servidor)", self._spy_isolamento_servidores,
                         skip_when=None)
        await self.check(phase, "agente não se auto-confirma (offline)", self._spy_agente_confirmacao, skip_when=None)

    async def _spy_bulk_direto(self) -> str:
        """Padrão do bot: o pedido já autoriza — 2 canais apagam direto, com o resultado na hora."""
        from brain.executors import execute_tool
        from brain.tools import ToolContext

        guild = SpyGuild()
        a = await guild.create_text_channel("direto-a")
        b = await guild.create_text_channel("direto-b")
        ctx = ToolContext(guild=guild, channel=a, actor=guild.members[0])
        a.calls.clear()
        b.calls.clear()
        resultado = await execute_tool("delete_channels", {"channels": [str(a.id), str(b.id)]}, ctx)
        self.assert_true("delete" in a.actions() and "delete" in b.actions(),
                         "modo direto não apagou os 2 canais")
        self.assert_true("Exclusão concluída" in resultado, f"resposta sem confirmação do que fez: {resultado!r}")
        return "2 canais apagados direto, com o resultado na resposta"

    async def _spy_bulk_confirm(self) -> str:
        from brain.executors import execute_tool
        from brain.tools import ToolContext, ToolError

        guild = SpyGuild()
        a = await guild.create_text_channel("conf-a")
        b = await guild.create_text_channel("conf-b")
        ctx = ToolContext(guild=guild, channel=a, actor=guild.members[0], confirm_destructive=True)
        a.calls.clear()
        b.calls.clear()
        try:
            await execute_tool("delete_channels", {"channels": [str(a.id), str(b.id)]}, ctx)
        except ToolError as exc:
            self.assert_true("confirm" in str(exc).lower(), f"erro não pede confirmação: {exc}")
        else:
            raise AssertionError("apagar 2 canais não pediu confirmação")
        self.assert_true(not a.actions() and not b.actions(), "algo foi apagado antes da confirmação")
        await execute_tool("delete_channels", {"channels": [str(a.id), str(b.id)], "confirmed": True}, ctx)
        self.assert_true("delete" in a.actions() and "delete" in b.actions(), "confirmed=true não apagou os canais")
        return "2 canais: exige confirmação e só apaga com confirmed=true"

    async def _spy_set_icon(self) -> str:
        """set_icon precisa BAIXAR a URL e mandar os bytes em guild.edit(icon=...)."""
        from brain import ops as ops_mod
        from brain.executors import execute_tool

        ctx, guild, _, _ = await self._spy_ctx()
        png = ops_mod._solid_png((12, 34, 56), size=128)
        baixadas: list[str] = []

        async def fake_download(url: str) -> bytes:
            baixadas.append(url)
            return png

        original = ops_mod._download_image
        ops_mod._download_image = fake_download
        try:
            guild.calls.clear()
            out = await execute_tool("set_icon", {"url": "https://exemplo.invalido/icone.png"}, ctx)
        finally:
            ops_mod._download_image = original

        self.assert_true(baixadas == ["https://exemplo.invalido/icone.png"],
                         f"set_icon não baixou a URL informada (baixou {baixadas or 'nada'})")
        edits = [kw for action, kw in guild.calls if action == "edit"]
        self.assert_true(bool(edits), f"set_icon não chamou guild.edit (chamadas: {guild.actions()})")
        self.assert_true(edits[-1].get("icon") == png,
                         "guild.edit recebeu bytes diferentes dos baixados")
        self.assert_true(guild.icon == png, "o ícone do servidor não mudou de verdade")
        self.assert_true("sucesso" in out.lower(), f"mensagem final inesperada: {out!r}")

        # Caminho offline: data URI base64 não passa pela rede.
        guild.calls.clear()
        import base64 as _b64
        data_uri = "data:image/png;base64," + _b64.b64encode(png).decode()
        await execute_tool("set_icon", {"url": data_uri}, ctx)
        self.assert_true(guild.icon == png, "data URI não aplicou o ícone")
        return "baixou a URL, mandou os bytes em guild.edit(icon=...) e aceitou data URI"

    async def _spy_set_icon_style(self) -> str:
        """Sem `url`, o `style` precisa gerar um PNG válido (nada de sucesso falso)."""
        import struct

        from brain.executors import execute_tool

        ctx, guild, _, _ = await self._spy_ctx()
        guild.calls.clear()
        await execute_tool("set_icon", {"style": "gamer"}, ctx)

        icone = guild.icon
        self.assert_true(isinstance(icone, (bytes, bytearray)), f"ícone não é bytes: {type(icone).__name__}")
        self.assert_true(bytes(icone[:8]) == b"\x89PNG\r\n\x1a\n", "o estilo não gerou um PNG válido")
        largura, altura = struct.unpack(">II", bytes(icone[16:24]))
        self.assert_true(min(largura, altura) >= 128,
                         f"PNG gerado tem {largura}x{altura}; o Discord exige pelo menos 128x128")

        await execute_tool("set_icon", {"style": "minimal"}, ctx)
        self.assert_true(guild.icon != icone, "estilos diferentes geraram exatamente o mesmo ícone")
        return f"gerou um PNG {largura}x{altura} sem tocar a rede"

    async def _spy_set_icon_falha(self) -> str:
        """Se o download falhar, a resposta NÃO pode dizer que deu certo."""
        from brain import ops as ops_mod
        from brain.executors import execute_tool
        from brain.tools import ToolError

        ctx, guild, _, _ = await self._spy_ctx()

        async def download_quebrado(url: str) -> bytes:
            raise ToolError(f"Falha ao baixar a imagem: {url}")

        original = ops_mod._download_image
        ops_mod._download_image = download_quebrado
        try:
            guild.calls.clear()
            try:
                out = await execute_tool("set_icon", {"url": "https://exemplo.invalido/nao-existe.png"}, ctx)
            except ToolError as exc:
                mensagem = str(exc)
            else:
                raise AssertionError(f"set_icon devolveu sucesso falso: {out!r}")
        finally:
            ops_mod._download_image = original

        self.assert_true("sucesso" not in mensagem.lower(),
                         f"mensagem de erro ainda fala em sucesso: {mensagem!r}")
        self.assert_true(not any(a == "edit" for a in guild.actions()),
                         "chamou guild.edit mesmo sem ter baixado a imagem")
        self.assert_true(guild.icon is None, "o ícone mudou apesar do download ter falhado")
        return f"erro honesto: {mensagem[:70]!r}"

    async def _spy_template(self) -> str:
        """apply_template precisa criar canais DENTRO das categorias (bug do `category` duplicado)."""
        from brain.executors import execute_tool
        from brain.ops import TEMPLATES_DATA

        ctx, guild, _, _ = await self._spy_ctx()
        guild.calls.clear()
        out = await execute_tool("apply_template", {"template": "gamer"}, ctx)

        tpl = TEMPLATES_DATA["gamer"]
        criadas = {c.name: c for c in guild.categories}
        total_canais = 0
        for cat_data in tpl["categories"]:
            cat = criadas.get(cat_data["name"])
            self.assert_true(cat is not None, f"categoria {cat_data['name']!r} não foi criada")
            for ch in cat_data["channels"]:
                alvo = next((c for c in guild.channels if c.name == ch["name"]), None)
                self.assert_true(alvo is not None, f"canal {ch['name']!r} não foi criado")
                self.assert_true(getattr(alvo, "category", None) is cat,
                                 f"canal {ch['name']!r} ficou fora da categoria {cat_data['name']!r}")
                total_canais += 1

        for role in tpl["roles"]:
            self.assert_true(any(r.name == role["name"] for r in guild.roles),
                             f"cargo {role['name']!r} não foi criado")
        self.assert_true("sucesso" in out.lower(), f"mensagem final inesperada: {out!r}")
        return f"{len(tpl['roles'])} cargos, {len(tpl['categories'])} categorias e {total_canais} canais dentro delas"

    async def _spy_agente_confirmacao(self) -> str:
        """
        O agente não pode se auto-confirmar: mesmo que o modelo mande `confirmed=true`,
        só executa depois que a pessoa confirmar. (Bug pego no teste ao vivo: ele apagou
        2 canais de uma vez sem perguntar.)
        """
        from brain.agent import Agent
        from brain.memory import ChannelMemory
        from llm.base import ChatProvider, LLMResponse, ToolCall

        class LLMRoteirizado(ChatProvider):
            def __init__(self, roteiro: list[LLMResponse]) -> None:
                self.roteiro = roteiro

            async def chat(self, messages: list[dict[str, Any]], tools: Any = None,
                           timeout: float = 60.0, max_tokens: int = 1024) -> LLMResponse:
                return self.roteiro.pop(0)

        ctx, guild, _, canal = await self._spy_ctx()
        lote = [await guild.create_text_channel(f"lote-{i}") for i in (1, 2)]
        for ch in lote:
            ch.calls.clear()

        def chamada_deletar() -> LLMResponse:
            return LLMResponse(content="", tool_calls=[ToolCall(
                id="conf_1", name="delete_channels",
                args={"channels": [str(ch.id) for ch in lote], "confirmed": True})])

        llm = LLMRoteirizado([chamada_deletar(),
                              LLMResponse(content="Posso apagar os 2 canais? Confirme, por favor.", tool_calls=[])])
        agent = Agent(llm_provider=llm, memory=ChannelMemory(), confirm_destructive=True)

        resposta = await agent.process_turn(guild=guild, channel=canal, actor=guild.members[0],
                                            prompt="Apague os canais lote-1 e lote-2 de uma vez.")
        self.assert_true(not any("delete" in ch.actions() for ch in lote),
                         "o agente apagou 2 canais sem a confirmação do usuário")
        self.assert_true("confirm" in resposta.lower() or "posso" in resposta.lower(),
                         f"o agente não pediu confirmação: {resposta[:80]!r}")

        # Modelo teimoso + resumo ruim: mesmo assim o usuário precisa VER a pergunta.
        teimoso = Agent(llm_provider=LLMRoteirizado([
            chamada_deletar(), chamada_deletar(),
            LLMResponse(content="**Resumo:** tentei excluir os canais e a tentativa falhou.", tool_calls=[]),
        ]), memory=ChannelMemory(), max_tool_rounds=2, confirm_destructive=True)
        resposta_ruim = await teimoso.process_turn(guild=guild, channel=canal, actor=guild.members[0],
                                                   prompt="Apague os canais lote-1 e lote-2 de uma vez.")
        self.assert_true(not any("delete" in ch.actions() for ch in lote), "apagou sem confirmação do usuário")
        self.assert_true("confirm" in resposta_ruim.lower() or "posso" in resposta_ruim.lower(),
                         f"o usuário ficou sem a pergunta de confirmação: {resposta_ruim[:90]!r}")

        # Modo direto (padrão do bot): o mesmo pedido executou sem perguntar nada.
        direto = [await guild.create_text_channel(f"direto-{i}") for i in (1, 2)]
        for ch in direto:
            ch.calls.clear()
        agente_direto = Agent(llm_provider=LLMRoteirizado([
            LLMResponse(content="", tool_calls=[ToolCall(
                id="direto_1", name="delete_channels",
                args={"channels": [str(ch.id) for ch in direto], "confirmed": True})]),
            LLMResponse(content="Apaguei os 2 canais. 🗑️", tool_calls=[]),
        ]), memory=ChannelMemory())
        resposta_direta = await agente_direto.process_turn(
            guild=guild, channel=canal, actor=guild.members[0],
            prompt="Apague os canais e deixe só esse.")
        self.assert_true(all("delete" in ch.actions() for ch in direto),
                         "modo direto não apagou o lote")
        self.assert_true("confirm" not in resposta_direta.lower() and "posso" not in resposta_direta.lower(),
                         f"modo direto não pode pedir confirmação: {resposta_direta[:90]!r}")

        llm.roteiro = [chamada_deletar(), LLMResponse(content="Pronto, canais apagados.", tool_calls=[])]
        await agent.process_turn(guild=guild, channel=canal, actor=guild.members[0], prompt="sim, pode apagar")
        self.assert_true(all("delete" in ch.actions() for ch in lote),
                         "depois do 'sim' o agente não apagou os canais")
        return "sem confirmação do usuário nada é apagado; a pergunta sempre aparece; com o 'sim', apaga"

    async def _spy_roles(self) -> str:
        from brain.executors import execute_tool

        ctx, guild, _, _ = await self._spy_ctx()
        dono = guild.members[0]
        guild.calls.clear()
        await execute_tool("create_roles", {"roles": [{"name": "cargo-spy", "color": "#5865F2",
                                                       "mentionable": True, "hoist": True}]}, ctx)
        self.assert_true("create_role" in guild.actions(), f"create_roles não chamou create_role ({guild.actions()})")
        papel = next((r for r in guild.roles if r.name == "cargo-spy"), None)
        self.assert_true(papel is not None, "cargo não apareceu no servidor")
        self.assert_true(papel.mentionable and papel.hoist, "mentionable/hoist não foram aplicados")

        papel.calls.clear()
        await execute_tool("edit_role", {"role": str(papel.id), "name": "cargo-spy-2", "color": "#00FF00"}, ctx)
        self.assert_true("edit" in papel.actions(), "edit_role não chamou role.edit")
        self.assert_true(papel.name == "cargo-spy-2", f"nome do cargo não mudou no objeto: {papel.name}")

        dono.calls.clear()
        await execute_tool("give_role", {"member": str(dono.id), "role": str(papel.id)}, ctx)
        self.assert_true("add_roles" in dono.actions(), "give_role não chamou member.add_roles")

        dono.calls.clear()
        await execute_tool("take_role", {"member": str(dono.id), "role": str(papel.id)}, ctx)
        self.assert_true("remove_roles" in dono.actions(), "take_role não chamou member.remove_roles")

        papel.calls.clear()
        await execute_tool("delete_role", {"role": str(papel.id), "confirmed": True}, ctx)
        self.assert_true("delete" in papel.actions(), "delete_role não chamou role.delete")
        return "criou/editou/deu/tirou/apagou: todas as chamadas de API aconteceram"

    async def _spy_permissions(self) -> str:
        from brain.executors import execute_tool

        ctx, guild, category, canal = await self._spy_ctx()
        await execute_tool("create_roles", {"roles": [{"name": "cargo-perm"}]}, ctx)

        canal.calls.clear()
        await execute_tool("set_permissions", {"channel": str(canal.id), "target": "cargo-perm",
                                               "deny": ["send_messages"]}, ctx)
        self.assert_true("set_permissions" in canal.actions(), "set_permissions não tocou a API")

        out = await execute_tool("show_permissions", {"channel": str(canal.id)}, ctx)
        self.assert_true("Permissões" in out, f"show_permissions devolveu {out[:80]!r}")

        # `target` precisa ser respeitado: filtra o cargo/membro pedido (bug: parâmetro ignorado).
        await execute_tool("create_roles", {"roles": [{"name": "cargo-beta"}]}, ctx)
        await execute_tool("set_permissions", {"channel": str(canal.id), "target": "cargo-beta",
                                               "deny": ["manage_messages"]}, ctx)
        filtrado = await execute_tool("show_permissions", {"channel": str(canal.id), "target": "cargo-perm"}, ctx)
        self.assert_true("cargo-perm" in filtrado, f"show_permissions(target) não citou o alvo: {filtrado[:90]!r}")
        self.assert_true("cargo-beta" not in filtrado,
                         f"show_permissions(target) mostrou OUTRO alvo também: {filtrado[:90]!r}")

        dono = guild.members[0]
        sem_perm = await execute_tool("show_permissions", {"channel": str(canal.id), "target": str(dono.id)}, ctx)
        self.assert_true("não tem permissões personalizadas" in sem_perm.lower().replace("nao", "não"),
                         f"membro sem overwrite devolveu {sem_perm[:90]!r}")
        await execute_tool("set_permissions", {"channel": str(canal.id), "target": str(dono.id),
                                               "allow": ["view_channel"]}, ctx)
        com_perm = await execute_tool("show_permissions", {"channel": str(canal.id), "target": str(dono.id)}, ctx)
        self.assert_true(dono.name in com_perm, f"show_permissions do membro não citou {dono.name}: {com_perm[:90]!r}")

        canal.calls.clear()
        await execute_tool("clear_permissions", {"channel": str(canal.id), "target": "cargo-perm"}, ctx)
        self.assert_true("set_permissions" in canal.actions(), "clear_permissions não tocou a API")

        canal.calls.clear()
        await execute_tool("sync_permissions", {"channel": str(canal.id)}, ctx)
        self.assert_true("edit" in canal.actions(), "sync_permissions não chamou channel.edit")
        return "set/clear/sync chamaram a API e show leu as permissões"

    async def _spy_readonly(self) -> str:
        from brain.executors import execute_tool

        ctx, guild, _, canal = await self._spy_ctx()
        guild.calls.clear()
        canal.calls.clear()
        for tool, args in (
            ("list_roles", {}),
            ("server_info", {}),
            ("export_structure", {}),
            ("color_palette", {"query": "gamer"}),
            ("color_name", {"hex_code": "#5865F2"}),
            ("emoji_search", {"query": "voz"}),
            ("topic_suggest", {"category": "gamer"}),
            ("translate_text", {"text": "hello"}),
        ):
            try:
                await execute_tool(tool, args, ctx)
            except Exception as exc:
                raise AssertionError(f"{tool} falhou: {type(exc).__name__}: {exc}") from exc
        self.assert_true(not guild.actions() and not canal.actions(),
                         f"ferramenta de leitura mutou algo: {guild.actions()} {canal.actions()}")
        return "8 ferramentas de leitura rodaram sem mutar nada"

    async def _spy_clear_memory(self) -> str:
        from brain.executors import execute_tool
        from brain.memory import ChannelMemory, memory_key

        ctx, guild, _, canal = await self._spy_ctx()
        memory = ChannelMemory()
        chave = memory_key(guild.id, canal.id)
        memory.add_message(chave, {"role": "user", "content": "oi"})
        ctx.memory = memory
        await execute_tool("conversation_clear", {}, ctx)
        self.assert_true(not memory.get_history(chave), "memória do canal não foi limpa")
        return "histórico do canal apagado de verdade"

    @staticmethod
    def silenciar_mensagens_reais(bot: Any) -> Any:
        """
        Impede o FarolBot DESTE teste de responder mensagens que chegarem pelo gateway.

        O bot de produção (workflow 24/7) usa o MESMO token e está online enquanto o teste
        roda: sem isso, dois processos responderiam a mesma mensagem de um cliente real.
        O teste chama `bot.on_message(...)` na mão com mensagens falsas, que continuam valendo.

        Devolve o dispatch original (para restaurar depois).
        """
        original = bot.dispatch

        def dispatch_filtrado(event: str, *args: Any, **kwargs: Any) -> Any:
            if event == "message":
                return None  # só as FakeMessage do teste são processadas
            return original(event, *args, **kwargs)

        bot.dispatch = dispatch_filtrado
        return original

    async def _spy_isolamento_servidores(self) -> str:
        """
        Bot vendido para vários servidores: o mesmo processo atende todos, então a conversa de
        um NÃO pode aparecer no outro — nem no histórico, nem na pendência de confirmação.
        """
        from brain.agent import Agent
        from brain.memory import ChannelMemory, memory_key
        from llm.base import ChatProvider, LLMResponse, ToolCall

        class LLMRoteiro(ChatProvider):
            def __init__(self, respostas: list[LLMResponse]) -> None:
                self.respostas = list(respostas)

            async def chat(self, messages: list[dict[str, Any]], tools: Any = None,
                           timeout: float = 60.0, max_tokens: int = 1024) -> LLMResponse:
                return self.respostas.pop(0) if self.respostas else LLMResponse(content="sem roteiro")

        def servidor(nome: str, cid: int) -> tuple[SpyGuild, SpyChannel]:
            guild = SpyGuild(f"Servidor {nome}")
            guild.members[0].guild_permissions = FakePerms(administrator=True)
            canal = SpyChannel("geral", guild=guild)
            canal.id = cid
            guild.channels.append(canal)
            return guild, canal

        # MESMO id de canal nos dois servidores: se a chave fosse só o canal, vazaria
        guild_a, canal_a = servidor("A", 950_001)
        guild_b, canal_b = servidor("B", 950_001)

        memoria = ChannelMemory()
        agente = Agent(llm_provider=LLMRoteiro([
            LLMResponse(content="Anotado no servidor A: Pinguim.", tool_calls=[]),
            LLMResponse(content="Aqui no B eu não sei de nada.", tool_calls=[]),
        ]), memory=memoria)
        ator = guild_a.members[0]

        await agente.process_turn(guild=guild_a, channel=canal_a, actor=ator, prompt="Guarde: Pinguim")
        hist_b = memoria.get_history(memory_key(guild_b.id, canal_b.id))
        self.assert_true(not hist_b, f"o histórico do servidor B recebeu conversa do A: {hist_b}")
        await agente.process_turn(guild=guild_b, channel=canal_b, actor=ator, prompt="Qual o apelido?")
        hist_b = memoria.get_history(memory_key(guild_b.id, canal_b.id))
        texto_b = " ".join(m.get("content", "") for m in hist_b)
        self.assert_true("Pinguim" not in texto_b, f"o apelido do servidor A vazou para o B: {texto_b!r}")

        # pendência de confirmação também é por conversa
        canal_a.overwrites = {}
        agente.llm = LLMRoteiro([
            LLMResponse(content="", tool_calls=[ToolCall(id="iso_1", name="delete_channels",
                                                         args={"channels": [str(canal_a.id)], "confirmed": True})]),
            LLMResponse(content="Confirma que posso apagar?", tool_calls=[]),
        ])
        await agente.process_turn(guild=guild_a, channel=canal_a, actor=ator, prompt="apague um canal do A")
        self.assert_true(not agente.pending_confirmation(memory_key(guild_b.id, canal_b.id)),
                         "a pendência do servidor A apareceu no servidor B")
        return "conversa, contexto e pendência de confirmação separados por servidor (mesmo id de canal)"

    # =====================================================================
    # policy
    # =====================================================================
    async def phase_policy(self) -> None:
        from brain.executors import execute_tool
        from brain.policy import require
        from brain.tools import ToolContext, ToolError

        phase = "policy"
        guild = SpyGuild()
        canal = await guild.create_text_channel("canal-policy")
        dono = guild.members[0]
        ctx = ToolContext(guild=guild, channel=canal, actor=dono)

        async def membro_comum() -> str:
            fraco = SpyMember("membro-comum", perms=FakePerms())
            try:
                require("create_channels", fraco.guild_permissions, guild.me.guild_permissions,
                        actor=fraco, bot_member=guild.me, guild=guild)
            except ToolError as exc:
                return f"membro comum bloqueado: {exc}"
            raise AssertionError("membro comum passou pela política")

        await self.check(phase, "membro comum é bloqueado", membro_comum)

        async def bot_sem_permissao() -> str:
            original = guild.me.guild_permissions
            guild.me.guild_permissions = FakePerms()
            try:
                require("create_channels", dono.guild_permissions, guild.me.guild_permissions,
                        actor=dono, bot_member=guild.me, guild=guild)
            except ToolError as exc:
                return f"bot sem permissão bloqueado: {exc}"
            finally:
                guild.me.guild_permissions = original
            raise AssertionError("bot sem permissão passou pela política")

        await self.check(phase, "bot sem permissão é bloqueado", bot_sem_permissao)

        async def everyone_intocavel() -> str:
            everyone = next(r for r in guild.roles if r.name == "@everyone")
            try:
                require("delete_role", dono.guild_permissions, guild.me.guild_permissions, actor=dono,
                        bot_member=guild.me, guild=guild, target_role=everyone)
            except ToolError as exc:
                return f"@everyone protegido: {exc}"
            raise AssertionError("@everyone pôde ser gerenciado")

        await self.check(phase, "@everyone é intocável", everyone_intocavel)

        async def cargo_gerenciado() -> str:
            gerenciado = SpyRole("CargoDeBot", position=1, managed=True)
            try:
                require("delete_role", dono.guild_permissions, guild.me.guild_permissions, actor=dono,
                        bot_member=guild.me, guild=guild, target_role=gerenciado)
            except ToolError as exc:
                return f"cargo de integração protegido: {exc}"
            raise AssertionError("cargo gerenciado pôde ser apagado")

        await self.check(phase, "cargo de integração é intocável", cargo_gerenciado)

        async def cargo_acima_do_bot() -> str:
            acima = SpyRole("CargoDoDono", position=guild.me.top_role.position + 1)
            try:
                require("edit_role", dono.guild_permissions, guild.me.guild_permissions, actor=dono,
                        bot_member=guild.me, guild=guild, target_role=acima)
            except ToolError as exc:
                return f"cargo acima do bot protegido: {exc}"
            raise AssertionError("cargo acima do bot pôde ser editado")

        await self.check(phase, "cargo acima do bot é protegido", cargo_acima_do_bot)

        async def cargo_do_autor() -> str:
            do_autor = SpyRole("CargoDoAutor", position=guild.members[0].top_role.position)
            try:
                require("edit_role", dono.guild_permissions, guild.me.guild_permissions, actor=dono,
                        bot_member=guild.me, guild=guild, target_role=do_autor)
            except ToolError as exc:
                return f"cargo no nível do autor protegido: {exc}"
            raise AssertionError("autor pôde editar cargo no mesmo nível do cargo dele")

        await self.check(phase, "autor não edita cargo no próprio nível", cargo_do_autor)

        from dataclasses import replace as _replace

        ctx_cauteloso = _replace(ctx, confirm_destructive=True)

        async def lote_exige_confirmacao() -> str:
            a = await guild.create_text_channel("lote-a")
            b = await guild.create_text_channel("lote-b")
            a.calls.clear()
            b.calls.clear()
            try:
                await execute_tool("delete_channels", {"channels": [str(a.id), str(b.id)]}, ctx_cauteloso)
            except ToolError as exc:
                self.assert_true("confirm" in str(exc).lower(), f"erro não pede confirmação: {exc}")
            else:
                raise AssertionError("apagar 2 canais não pediu confirmação")
            self.assert_true(not a.actions() and not b.actions(), "algo foi apagado antes da confirmação")
            return "2 canais: pede confirmação e não apaga nada antes"

        await self.check(phase, "exclusão em lote exige confirmação (modo cauteloso)", lote_exige_confirmacao)

        async def lote_no_modo_direto() -> str:
            a = await guild.create_text_channel("direto-a")
            b = await guild.create_text_channel("direto-b")
            a.calls.clear()
            b.calls.clear()
            await execute_tool("delete_channels", {"channels": [str(a.id), str(b.id)]}, ctx)
            self.assert_true("delete" in a.actions() and "delete" in b.actions(),
                             "modo direto (padrão) não apagou o lote")
            return "2 canais: modo direto apaga e informa, sem perguntar"

        await self.check(phase, "exclusão em lote executa direto no padrão", lote_no_modo_direto)

        async def canal_unico_executa() -> str:
            unico = await guild.create_text_channel("canal-unico")
            unico.calls.clear()
            await execute_tool("delete_channels", {"channels": [str(unico.id)]}, ctx)
            self.assert_true("delete" in unico.actions(), "canal único nominal não foi excluído direto")
            return "canal único nominal executa sem travar o fluxo"

        await self.check(phase, "canal único apaga sem confirmação", canal_unico_executa)

        async def cargo_exige_confirmacao() -> str:
            papel = await guild.create_role("cargo-temp")
            papel.calls.clear()
            try:
                await execute_tool("delete_role", {"role": str(papel.id)}, ctx_cauteloso)
            except ToolError:
                pass
            else:
                raise AssertionError("delete_role apagou sem confirmação no modo cauteloso")
            self.assert_true(not papel.actions(), "cargo apagado antes da confirmação")
            await execute_tool("delete_role", {"role": str(papel.id), "confirmed": True}, ctx_cauteloso)
            self.assert_true("delete" in papel.actions(), "não apagou com confirmed=true")
            return "cargo: exige confirmação e apaga com confirmed=true"

        await self.check(phase, "exclusão de cargo exige confirmação (modo cauteloso)", cargo_exige_confirmacao)

        async def cargo_no_modo_direto() -> str:
            papel = await guild.create_role("cargo-direto")
            papel.calls.clear()
            await execute_tool("delete_role", {"role": str(papel.id)}, ctx)
            self.assert_true("delete" in papel.actions(),
                             "modo direto (padrão) não apagou o cargo pedido")
            return "cargo: modo direto apaga o que foi pedido, sem perguntar"

        await self.check(phase, "exclusão de cargo executa direto no padrão", cargo_no_modo_direto)

        async def ferramenta_inexistente() -> str:
            try:
                await execute_tool("ferramenta_inexistente", {}, ctx)
            except ToolError as exc:
                return f"ferramenta desconhecida rejeitada: {exc}"
            raise AssertionError("ferramenta inexistente foi aceita")

        await self.check(phase, "ferramenta inexistente é rejeitada", ferramenta_inexistente)

        async def erro_de_tool_vira_texto() -> str:
            from brain.tools import ToolError as TE
            try:
                await execute_tool("delete_channels", {"channels": []}, ctx)
            except TE as exc:
                return f"lista vazia rejeitada com ToolError: {exc}"
            raise AssertionError("lista vazia foi aceita")

        await self.check(phase, "argumentos inválidos são rejeitados", erro_de_tool_vira_texto)

    # =====================================================================
    # connect
    # =====================================================================
    async def phase_connect(self) -> None:
        phase = "connect"

        async def config_ok() -> str:
            self.env = await self._build_live_stack()
            cfg = self.env.config
            self.rep.record(phase, "corredores de LLM na corrida", PASS, self.env.llm.describe())
            return (f"token no formato correto ({len(cfg.discord_token)} chars) · provider={cfg.llm_provider} · "
                    f"intents: members={cfg.members_intent}, message_content={cfg.message_content_intent}")

        await self.check(phase, "configuração carregada", config_ok)
        if self.env.config is None:
            return

        async def corrida_llm() -> tuple[str, dict[str, Any]]:
            resp = await self.env.llm.chat(messages=[{"role": "user", "content": "Responda apenas: pong"}],
                                           tools=None, timeout=self.args.llm_timeout)
            texto = (resp.content or "").strip()
            self.assert_true(bool(texto), "a corrida de LLMs devolveu resposta vazia")
            return (f"vencedor {self.env.llm.last_winner} (tools nativas: {self.env.llm.last_winner_native_tools}) "
                    f"→ {texto[:50]!r}", {"vencedor": self.env.llm.last_winner})

        await self.check(phase, "corrida de LLMs responde", corrida_llm)

        async def gateway() -> tuple[str, dict[str, Any]]:
            client, task, motivo = await self._connect_safe()
            self.env.client, self.env.connect_task = client, task
            self.env.guilds = list(client.guilds)
            if motivo:
                self.rep.record(phase, "intents privilegiadas", FAIL, motivo)
            latencia = round(client.latency * 1000)
            nomes = ", ".join(f"{g.name} ({g.id})" for g in client.guilds) or "nenhum"
            self.rep.record(phase, "servidores do bot", PASS if client.guilds else FAIL,
                            f"{len(client.guilds)}: {nomes}" if client.guilds else
                            "o bot não está em nenhum servidor — convide-o (README Passo 2) para testar o resto")
            self.env.primary = self._pick_guild() if client.guilds else None
            data = {"usuario": str(client.user), "latencia_ms": latencia,
                    "servidores": [{"nome": g.name, "id": g.id, "membros": getattr(g, "member_count", None)}
                                   for g in client.guilds]}
            return f"conectado como {client.user} · gateway em {latencia}ms", data

        await self.check(phase, "login e gateway", gateway)

        async def autor() -> str:
            if self.env.primary is None:
                raise AssertionError("sem servidor para escolher autor")
            self.env.actor = await self._resolve_actor(self.env.primary)
            admin = getattr(self.env.actor.guild_permissions, "administrator", False)
            return (f"servidor de teste: {self.env.primary.name} ({self.env.primary.id}) · "
                    f"autor: {self.env.actor} ({'administrador' if admin else 'permissões parciais'})")

        await self.check(phase, "servidor e autor do teste", autor)

    # =====================================================================
    # audit
    # =====================================================================
    async def phase_audit(self) -> None:
        phase = "audit"
        live = await self.ensure_live(phase)
        if live is None:
            self.rep.record(phase, "diagnóstico", SKIP, "sem conexão ao Discord")
            return

        guild = live.primary
        perms = guild.me.guild_permissions

        async def permissoes() -> tuple[str, dict[str, Any]]:
            estado = {
                "manage_channels": bool(getattr(perms, "manage_channels", False)),
                "manage_roles": bool(getattr(perms, "manage_roles", False)),
                "manage_guild": bool(getattr(perms, "manage_guild", False)),
                "administrator": bool(getattr(perms, "administrator", False)),
                "send_messages": bool(getattr(perms, "send_messages", False)),
            }
            faltando = [k for k in ("manage_channels", "manage_roles", "send_messages") if not estado[k]]
            self.assert_true(not faltando, f"faltam permissões {faltando} para o bot — veja o README Passo 2. "
                                           f"Estado: {estado}")
            return f"OK: {[k for k, v in estado.items() if v]}", estado

        await self.check(phase, "permissões do bot no servidor", permissoes)

        async def hierarquia() -> tuple[str, dict[str, Any]]:
            pos = guild.me.top_role.position
            acima = [r for r in guild.roles if r.position >= pos and not r.is_default()]
            data = {"posicao_cargo_bot": pos, "cargos_acima_ou_igual": [r.name for r in acima]}
            if acima:
                self.rep.record(phase, "cargos que o bot não consegue gerenciar", WARN,
                                f"{len(acima)} cargo(s) no nível ou acima do bot ({', '.join(r.name for r in acima[:5])}): "
                                "ele não conseguirá editar/apagar esses cargos. Suba o cargo do farol (README Passo 3).")
                return f"cargo do bot na posição {pos}", data
            return f"cargo do bot no topo (posição {pos}) — pode gerenciar todos os cargos", data

        await self.check(phase, "hierarquia de cargos", hierarquia)

        async def estrutura() -> tuple[str, dict[str, Any]]:
            data = {"categorias": len(guild.categories), "texto": len(guild.text_channels),
                    "voz": len(guild.voice_channels), "cargos": len(guild.roles),
                    "membros": getattr(guild, "member_count", None)}
            return (f"{data['categorias']} categorias · {data['texto']} texto · {data['voz']} voz · "
                    f"{data['cargos']} cargos · {data['membros']} membros"), data

        await self.check(phase, "estrutura do servidor", estrutura)

        async def snapshot() -> str:
            from brain.snapshot import build_server_snapshot

            snap = build_server_snapshot(guild)
            self.assert_true(guild.name in snap, "snapshot sem o nome do servidor")
            if guild.channels:
                self.assert_true(any(c.name in snap for c in guild.channels), "snapshot não lista canais reais")
            if guild.roles:
                self.assert_true(any(r.name in snap for r in guild.roles), "snapshot não lista cargos reais")
            return f"snapshot com {len(snap.splitlines())} linhas alimenta o prompt"

        await self.check(phase, "snapshot do servidor", snapshot)

        async def rest_api() -> str:
            canais = await guild.fetch_channels()
            cargos = await guild.fetch_roles()
            self.assert_true(len(canais) == len(guild.channels),
                             f"cache local ({len(guild.channels)}) difere da API ({len(canais)})")
            self.assert_true(len(cargos) == len(guild.roles), "cache de cargos difere da API")
            return f"cache local bate com a API REST ({len(canais)} canais, {len(cargos)} cargos)"

        await self.check(phase, "estado local bate com a API", rest_api)

    # =====================================================================
    # tools
    # =====================================================================
    async def phase_tools(self) -> None:
        from brain.executors import execute_tool
        from brain.resolve import resolve_channel, resolve_role
        from brain.tools import ToolContext

        phase = "tools"
        live = await self.ensure_live(phase)
        if live is None:
            self.rep.record(phase, "ferramentas de leitura", SKIP, "sem conexão ao Discord")
            return

        guild = live.primary
        canal = next(iter(guild.text_channels), None) or next(iter(guild.channels), None)
        ctx = ToolContext(guild=guild, channel=canal, actor=live.actor, api_registry=live.registry,
                          memory=live.memory)

        async def server_info() -> str:
            out = await execute_tool("server_info", {}, ctx)
            self.assert_true(guild.name in out, f"server_info não trouxe o nome do servidor: {out[:90]}")
            self.assert_true(str(len(guild.roles)) in out, "server_info não trouxe a contagem de cargos")
            return out.replace("\n", " · ")[:200]

        await self.check(phase, "server_info", server_info)

        async def list_roles() -> str:
            out = await execute_tool("list_roles", {}, ctx)
            faltando = [r.name for r in guild.roles if f"<@&{r.id}>" not in out]
            self.assert_true(not faltando, f"não listou todos os cargos reais (menções): faltou {faltando[:4]}")
            return f"listou os {len(guild.roles)} cargos reais com menção e posição"

        await self.check(phase, "list_roles", list_roles)

        async def export_structure() -> tuple[str, dict[str, Any]]:
            out = await execute_tool("export_structure", {}, ctx)
            bruto = out[out.find("{"): out.rfind("}") + 1] if "{" in out else out
            data = json.loads(bruto)
            self.assert_true("categories" in data and "roles" in data, "JSON sem categories/roles")
            # @everyone é intocável por projeto: não entra no backup
            esperados = [r.name for r in guild.roles if not r.is_default()]
            self.assert_true(len(data["roles"]) == len(esperados),
                             f"exportou {len(data['roles'])} cargos, esperado {len(esperados)} (sem @everyone)")
            self.assert_true(len(data["categories"]) == len(guild.categories),
                             f"exportou {len(data['categories'])} categorias, o servidor tem {len(guild.categories)}")
            canais = sum(len(c.get("channels", [])) for c in data["categories"]) + len(
                data.get("uncategorized_channels", []))
            return (f"{len(data['categories'])} categorias, {canais} canais e {len(data['roles'])} cargos "
                    "exportados em JSON válido"), {"categorias": len(data["categories"])}

        await self.check(phase, "export_structure (JSON válido e completo)", export_structure)

        async def show_permissions() -> str:
            if canal is None:
                raise AssertionError("servidor sem canais para testar")
            out = await execute_tool("show_permissions", {"channel": str(canal.id)}, ctx)
            self.assert_true("Permissões" in out or "não possui permissões" in out, f"resposta inesperada: {out[:120]}")
            return out.replace("\n", " · ")[:180]

        await self.check(phase, "show_permissions", show_permissions)

        async def resolucao() -> str:
            canais = [c for c in guild.channels[:6]]
            for ch in canais:
                self.assert_true(resolve_channel(guild, str(ch.id)).id == ch.id, f"ID de canal falhou: {ch.name}")
                self.assert_true(resolve_channel(guild, f"<#{ch.id}>").id == ch.id, f"menção de canal falhou: {ch.name}")
            cargos = guild.roles[:6]
            for role in cargos:
                self.assert_true(resolve_role(guild, str(role.id)).id == role.id, f"ID de cargo falhou: {role.name}")
                self.assert_true(resolve_role(guild, f"<@&{role.id}>").id == role.id, f"menção de cargo falhou: {role.name}")
            return f"{len(canais)} canais e {len(cargos)} cargos resolvidos por ID e por menção"

        await self.check(phase, "resolve por ID e por menção", resolucao)

        async def utilitarias() -> tuple[str, dict[str, Any]]:
            ok, falhas = [], []
            for nome, args in (
                ("color_palette", {"query": "gamer"}),
                ("color_name", {"hex_code": "#5865F2"}),
                ("emoji_search", {"query": "voz"}),
                ("topic_suggest", {"category": "gamer"}),
                ("translate_text", {"text": "hello world", "target_lang": "pt"}),
            ):
                try:
                    out = await execute_tool(nome, args, ctx)
                    self.assert_true(bool(out.strip()), f"{nome} devolveu vazio")
                    ok.append(nome)
                except Exception as exc:
                    falhas.append(f"{nome}: {type(exc).__name__}: {str(exc)[:70]}")
            if falhas:
                self.rep.record(phase, "APIs externas (parcial)", WARN if ok else FAIL,
                                f"ok: {ok} · falhas: {falhas}")
            return f"{len(ok)} APIs externas responderam", {"falhas": falhas}

        await self.check(phase, "APIs externas (cores/emojis/tópicos/tradução)", utilitarias)

    # =====================================================================
    # agent
    # =====================================================================
    async def phase_agent(self) -> None:
        phase = "agent"
        live = await self.ensure_live(phase)
        if live is None:
            self.rep.record(phase, "agente", SKIP, "sem conexão ao Discord")
            return

        guild = live.primary
        canal = next(iter(guild.text_channels), None) or next(iter(guild.channels), None)
        chamadas: list[dict[str, Any]] = []
        inner = live.llm
        contador = itertools.count(1)

        class CanalIsolado:
            """Proxy do canal real com id próprio: cada verificação tem a sua memória."""

            def __init__(self, real: Any, cid: int) -> None:
                self._real = real
                self.id = cid

            def __getattr__(self, item: str) -> Any:
                return getattr(self._real, item)

        def canal_novo() -> CanalIsolado:
            # ids fora da faixa do Discord só existem aqui: a memória não vaza entre checagens
            return CanalIsolado(canal, 900_000 + next(contador))

        class RecordingLLM:
            name = "recording"

            def __init__(self, wrapped: Any) -> None:
                self.wrapped = wrapped

            async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                           timeout: float = 60.0, max_tokens: int = 1024) -> Any:
                resp = await self.wrapped.chat(messages=messages, tools=tools, timeout=timeout, max_tokens=max_tokens)
                chamadas.append({
                    "ferramentas_oferecidas": len(tools or []),
                    "ferramentas_chamadas": [c.name for c in getattr(resp, "tool_calls", [])],
                    "chars": len(resp.content or ""),
                    "vencedor": getattr(self.wrapped, "last_winner", ""),
                })
                return resp

            def describe(self) -> str:
                return self.wrapped.describe()

            async def close(self) -> None:
                await self.wrapped.close()

        live.agent.llm = RecordingLLM(inner)

        async def perguntar(prompt: str, canal_ctx: Any = None) -> str:
            chamadas.clear()
            return await live.agent.process_turn(guild=guild, channel=canal_ctx or canal, actor=live.actor,
                                                 prompt=prompt)

        async def lista_cargos() -> tuple[str, dict[str, Any]]:
            resposta = await perguntar("Liste os nomes dos cargos que existem neste servidor.", canal_novo())
            self.assert_true(bool(resposta.strip()), "agente devolveu resposta vazia")
            chamadas_feitas = [n for c in chamadas for n in c["ferramentas_chamadas"]]
            if not chamadas_feitas:
                # as 27 ferramentas foram oferecidas e o bot repassou tudo; quem não chamou foi o modelo
                return (self.degradar_llm(phase, "prompt → ferramenta → resposta coerente",
                                          f"o LLM não chamou nenhuma ferramenta (rodadas: {chamadas})", resposta),
                        {"ferramentas": []})
            reais = [r.name for r in guild.roles if r.name in resposta or f"<@&{r.id}>" in resposta]
            if not reais:
                # as ferramentas rodaram (o pipeline do bot está ok); o texto veio vago do provedor
                return (self.degradar_llm(phase, "prompt → ferramenta → resposta coerente",
                                          "a resposta não citou nenhum cargo real "
                                          f"(ferramentas chamadas: {chamadas_feitas})", resposta),
                        {"ferramentas": chamadas_feitas})
            vencedor = chamadas[0]["vencedor"] if chamadas else "?"
            return (f"ferramentas {chamadas_feitas} · vencedor {vencedor} · citou {reais[:3]}"), {
                "ferramentas": chamadas_feitas, "vencedor": vencedor}

        await self.check(phase, "prompt → ferramenta → resposta coerente", lista_cargos)

        async def fora_de_escopo() -> tuple[str, dict[str, Any]]:
            resposta = await perguntar("Bane o usuário @fulano do servidor agora, por favor.", canal_novo())
            chamadas_feitas = [n for c in chamadas for n in c["ferramentas_chamadas"]]
            self.assert_true(bool(resposta.strip()), "respondeu vazio ao recusar")
            self.assert_true(not chamadas_feitas, f"tentou executar ferramenta fora de escopo: {chamadas_feitas}")
            baixo = resposta.lower()
            if not any(t in baixo for t in ("estrutur", "organiz", "canal", "cargo", "foco")):
                self.rep.record(phase, "recusa fora-de-escopo (redação)", WARN,
                                f"recusou sem explicar o escopo: {resposta[:140]!r}")
            return f"recusou moderação sem chamar ferramentas: {resposta[:90]!r}", {"tool_calls": chamadas_feitas}

        await self.check(phase, "fora de escopo é recusado sem executar", fora_de_escopo)

        async def conhece_estrutura() -> str:
            # o bot responde com nomes OU com menções (<#id>), então os dois valem
            marcadores: list[tuple[str, str]] = []
            for ch in list(guild.categories) + list(guild.channels):
                marcadores.append((ch.name, f"<#{ch.id}>"))
            if not marcadores:
                raise AssertionError("servidor sem categorias/canais para checar")
            resposta = await perguntar("Liste as categorias e os canais deste servidor.", canal_novo())
            citados = [nome for nome, mencao in marcadores if nome in resposta or mencao in resposta]
            self.assert_true(bool(citados), f"não citou nada real do servidor (nem nome nem menção): {resposta[:160]!r}")
            return f"citou itens reais do servidor ({', '.join(citados[:3])})"

        await self.check(phase, "agente conhece a estrutura real", conhece_estrutura)

        async def memoria() -> str:
            mesmo_canal = canal_novo()
            try:
                await perguntar("Guarde este apelido: o servidor se chama Pinguim.", mesmo_canal)
                resposta = await perguntar("Qual apelido eu pedi para você guardar?", mesmo_canal)
            except Exception as exc:
                if self._culpa_do_llm(str(exc)):
                    return self.degradar_llm(phase, "memória do canal entre turnos",
                                             "não deu para conversar: o LLM não respondeu", str(exc))
                raise
            if "pinguim" not in resposta.lower() and self._culpa_do_llm(resposta):
                return self.degradar_llm(phase, "memória do canal entre turnos",
                                         "a resposta não citou o apelido guardado", resposta)
            self.assert_true("pinguim" in resposta.lower(), f"memória do canal falhou: {resposta[:160]!r}")
            return "histórico do canal lembrado entre turnos"

        await self.check(phase, "memória do canal entre turnos", memoria)

    # =====================================================================
    # mutate
    # =====================================================================
    def _is_ours(self, nome: str, conhecidos: Iterable[str] = ()) -> bool:
        if TEMP_MARK in nome:
            return True
        return any(nome == k or nome.lower() == k.lower() for k in conhecidos)

    async def _api_state(self, guild: Any) -> tuple[dict[int, Any], dict[int, Any]]:
        canais = {c.id: c for c in await guild.fetch_channels()}
        cargos = {r.id: r for r in await guild.fetch_roles()}
        return canais, cargos

    async def _capture_new(self, guild: Any,
                           before: tuple[dict[int, Any], dict[int, Any]],
                           conhecidos: Iterable[str] = ()) -> list[Any]:
        """Registra como nossos os objetos novos; ignora (com aviso) o que não bate com a marca."""
        canais, cargos = await self._api_state(guild)
        novos_canais = [c for cid, c in canais.items() if cid not in before[0]]
        novos_cargos = [r for rid, r in cargos.items() if rid not in before[1]]
        for c in novos_canais:
            if self._is_ours(c.name, conhecidos):
                self.owned_channels.add(c.id)
            else:
                self.rep.note(f"canal novo NÃO é do teste (não vou mexer): #{c.name} ({c.id})")
        for r in novos_cargos:
            if self._is_ours(r.name, conhecidos):
                self.owned_roles.add(r.id)
            else:
                self.rep.note(f"cargo novo NÃO é do teste (não vou mexer): @{r.name} ({r.id})")
        return novos_canais

    async def _cleanup(self, guild: Any, phase: str) -> None:
        sobras: list[str] = []
        for cid in list(self.owned_channels):
            try:
                canal = guild.get_channel(cid) or await guild.fetch_channel(cid)
            except Exception:
                canal = None
            if canal is None:
                self.owned_channels.discard(cid)
                continue
            if cid not in self.owned_channels:
                continue
            try:
                await canal.delete()
                self.owned_channels.discard(cid)
            except Exception as exc:
                sobras.append(f"#{canal.name}({cid}): {exc}")
        for rid in list(self.owned_roles):
            try:
                papel = guild.get_role(rid) or next((r for r in await guild.fetch_roles() if r.id == rid), None)
            except Exception:
                papel = None
            if papel is None:
                self.owned_roles.discard(rid)
                continue
            try:
                await papel.delete()
                self.owned_roles.discard(rid)
            except Exception as exc:
                sobras.append(f"@{papel.name}({rid}): {exc}")
        if sobras:
            self.rep.record(phase, "limpeza", FAIL,
                            f"sobraram objetos de teste: {'; '.join(sobras)} — remova manualmente")
        else:
            self.rep.record(phase, "limpeza", PASS, "todos os objetos de teste foram removidos")

    async def phase_mutate(self) -> None:
        from brain.executors import execute_tool
        from brain.tools import ToolContext, ToolError

        phase = "mutate"
        if not self.args.mutate:
            self.rep.record(phase, "mutações reais", SKIP,
                            "rode com --mutate para criar/editar/apagar objetos de teste (com limpeza garantida)")
            return
        live = await self.ensure_live(phase)
        if live is None:
            self.rep.record(phase, "mutações reais", SKIP, "sem conexão ao Discord")
            return

        guild = live.primary
        registro_llm: list[dict[str, Any]] = []
        live.agent.llm = LLMRegistro(live.agent.llm, registro_llm)
        cat_nome, txt_nome, voz_nome = f"{TEMP_MARK} teste-farol", f"{TEMP_MARK}-texto", f"{TEMP_MARK}-voz"
        holder: dict[str, Any] = {}

        async def infraestrutura() -> str:
            """Infra do teste (não é a verificação em si): cria a categoria e os canais direto pela API."""
            antes = await self._api_state(guild)
            categoria = await guild.create_category(cat_nome)
            texto = await guild.create_text_channel(txt_nome, category=categoria, topic="canal de teste e2e")
            voz = await guild.create_voice_channel(voz_nome, category=categoria)
            await self._capture_new(guild, antes)
            confirmado = await guild.fetch_channel(texto.id)
            self.assert_true(confirmado.category_id == categoria.id, "infra: canal fora da categoria")
            holder.update(categoria=categoria, texto=texto, voz=voz)
            holder["ctx"] = ToolContext(guild=guild, channel=texto, actor=live.actor,
                                        api_registry=live.registry, memory=live.memory)
            return f"categoria {categoria.name} + {txt_nome} + {voz_nome} criados (registrados para limpeza)"

        await self.check(phase, "infra: categoria e canais de teste", infraestrutura)
        if "ctx" not in holder:
            await self._cleanup(guild, phase)
            return

        ctx = holder["ctx"]
        categoria, texto = holder["categoria"], holder["texto"]

        async def ferramenta(nome: str, args: dict[str, Any]) -> str:
            return await execute_tool(nome, args, ctx)

        async def buscar(cid: int) -> Any:
            return await guild.fetch_channel(cid)

        async def ferramenta_cria_dentro() -> str:
            antes = await self._api_state(guild)
            await ferramenta("create_channels", {"channels": [
                {"name": f"{TEMP_MARK}-dentro", "type": "text", "category": str(categoria.id)},
                {"name": f"{TEMP_MARK}-dentro-voz", "type": "voice", "category": str(categoria.id)}]})
            novos = await self._capture_new(guild, antes)
            nomes = [c.name for c in novos]
            self.assert_true(len(novos) == 2, f"a ferramenta não criou os 2 canais dentro da categoria (criou {nomes})")
            self.assert_true(all(c.category_id == categoria.id for c in novos),
                             f"algo ficou fora da categoria: {[(c.name, c.category_id) for c in novos]}")
            return f"texto + voz criados dentro da categoria existente ({nomes})"

        await self.check(phase, "create_channels DENTRO de categoria (via ferramenta)", ferramenta_cria_dentro)

        async def ferramenta_cria_raiz() -> str:
            antes = await self._api_state(guild)
            await ferramenta("create_channels", {"channels": [
                {"name": f"{TEMP_MARK}-raiz-texto", "type": "text"},
                {"name": f"{TEMP_MARK}-raiz-voz", "type": "voice"},
                {"name": f"{TEMP_MARK}-raiz-categoria", "type": "category"}]})
            novos = await self._capture_new(guild, antes)
            nomes = [c.name for c in novos]
            self.assert_true(len(novos) == 3, f"a ferramenta não criou os 3 objetos na raiz (criou {nomes})")
            return f"texto + voz + categoria criados na raiz ({nomes})"

        await self.check(phase, "create_channels na RAIZ (via ferramenta)", ferramenta_cria_raiz)

        async def edit_channel() -> str:
            await ferramenta("edit_channel", {"channel": str(texto.id), "name": f"{TEMP_MARK}-renomeado",
                                              "topic": "tópico novo", "slowmode_delay": 5})
            ch = await buscar(texto.id)
            self.assert_true(ch.name == f"{TEMP_MARK}-renomeado", f"nome não mudou na API: {ch.name}")
            self.assert_true(ch.topic == "tópico novo", f"tópico não mudou na API: {ch.topic}")
            self.assert_true(ch.slowmode_delay == 5, f"slowmode não mudou na API: {ch.slowmode_delay}")
            return f"nome, tópico e slowmode confirmados na API ({ch.name})"

        await self.check(phase, "edit_channel alterou de verdade", edit_channel)

        async def clone_channel() -> tuple[str, dict[str, Any]]:
            antes_clone = await self._api_state(guild)
            await ferramenta("clone_channel", {"channel": str(texto.id), "name": f"{TEMP_MARK}-clone"})
            novos = await self._capture_new(guild, antes_clone)
            self.assert_true(bool(novos), "o clone não apareceu na API")
            clone = novos[0]
            original = await buscar(texto.id)
            self.assert_true(clone.category_id == original.category_id, "o clone não herdou a categoria")
            return f"clone {clone.name} criado com a mesma categoria", {"clone_id": clone.id}

        await self.check(phase, "clone_channel clonou de verdade", clone_channel)

        async def move_channel() -> str:
            clone = next((c for c in await guild.fetch_channels() if c.name == f"{TEMP_MARK}-clone"), None)
            self.assert_true(clone is not None, "clone não encontrado para mover")
            await ferramenta("move_channel", {"channel": str(clone.id), "category": "none"})
            self.assert_true((await buscar(clone.id)).category_id is None, "o canal não saiu da categoria")
            await ferramenta("move_channel", {"channel": str(clone.id), "category": str(categoria.id)})
            self.assert_true((await buscar(clone.id)).category_id == categoria.id, "o canal não voltou para a categoria")
            return "saiu e voltou de categoria, confirmado pela API"

        await self.check(phase, "move_channel moveu de verdade", move_channel)

        async def cargos() -> str:
            antes_cargos = await self._api_state(guild)
            await ferramenta("create_roles", {"roles": [{"name": f"{TEMP_MARK} teste-papel", "color": "#5865F2",
                                                         "mentionable": True, "hoist": True}]})
            await self._capture_new(guild, antes_cargos)
            papel = next((r for r in await guild.fetch_roles() if r.name == f"{TEMP_MARK} teste-papel"), None)
            self.assert_true(papel is not None, "o cargo não apareceu na API")
            self.assert_true(str(papel.color) == "#5865f2", f"cor errada (esperado #5865f2): {papel.color}")
            self.assert_true(papel.mentionable and papel.hoist, "mentionable/hoist não aplicados")

            # Editar/atribuir depende da POSIÇÃO do cargo do bot no servidor: se ele está no chão
            # (posição 1), o Discord não deixa mexer nem nos cargos que ele mesmo criou. Não é bug
            # do código — é configuração do servidor (README Passo 3), então vira WARN acionável.
            try:
                await ferramenta("edit_role", {"role": str(papel.id), "name": f"{TEMP_MARK} teste-papel-v2",
                                               "color": "#00c853"})
                papel2 = next((r for r in await guild.fetch_roles() if r.id == papel.id), None)
                self.assert_true(papel2.name.endswith("v2"), f"o nome do cargo não mudou: {papel2.name}")
                self.assert_true(str(papel2.color) == "#00c853", f"a cor do cargo não mudou: {papel2.color}")

                nota = ""
                try:
                    await ferramenta("give_role", {"member": str(guild.me.id), "role": str(papel.id)})
                    membro = await guild.fetch_member(guild.me.id)
                    self.assert_true(any(r.id == papel.id for r in membro.roles), "o cargo não foi dado ao bot")
                    await ferramenta("take_role", {"member": str(guild.me.id), "role": str(papel.id)})
                    membro = await guild.fetch_member(guild.me.id)
                    self.assert_true(not any(r.id == papel.id for r in membro.roles),
                                     "o cargo não foi retirado do bot")
                    nota = "cargo dado e retirado do próprio bot"
                except ToolError as exc:
                    nota = f"dar/tirar cargo não suportado neste servidor ({str(exc)[:70]})"
                    self.rep.record(phase, "give_role/take_role", WARN, nota)
                return f"cargo criado, editado e confirmado na API ({nota})"
            except ToolError as exc:
                if "mesma posição do meu cargo mais alto" not in str(exc):
                    raise
                self.rep.record(
                    phase, "cargo do farol no chão do servidor", WARN,
                    f"{exc} Ação do dono (README Passo 3): arraste o cargo do farol para cima dos outros — "
                    "sem isso ele não edita nem os cargos que ele mesmo cria.")
                return ("cargo criado e conferido na API; editar/dar/tirar ficou bloqueado pela posição do "
                        "cargo do bot no servidor")

        await self.check(phase, "cargos: criar/editar/atribuir de verdade", cargos)

        async def permissoes() -> str:
            await ferramenta("set_permissions", {"channel": str(texto.id), "target": "@everyone",
                                                 "deny": ["send_messages"]})
            ch = await buscar(texto.id)
            self.assert_true(bool(ch.overwrites), "nenhuma sobrescrita foi criada")
            self.assert_true(any(o.send_messages is False for o in ch.overwrites.values()),
                             "send_messages não foi negado")
            await ferramenta("sync_permissions", {"channel": str(texto.id)})
            sincronizado = await buscar(texto.id)
            base_cat = await buscar(categoria.id)
            self.assert_true(len(sincronizado.overwrites) == len(base_cat.overwrites),
                             f"sync não igualou a categoria ({len(sincronizado.overwrites)} vs {len(base_cat.overwrites)})")
            await ferramenta("clear_permissions", {"channel": str(texto.id), "target": "@everyone"})
            limpo = await buscar(texto.id)
            self.assert_true(not limpo.overwrites, f"as sobrescritas não foram removidas: {limpo.overwrites}")
            await ferramenta("set_permissions", {"channel": str(texto.id), "target": "@everyone",
                                                 "deny": ["send_messages"]})
            na_api = await buscar(texto.id)
            self.assert_true(bool(na_api.overwrites), "a permissão não chegou na API do Discord")
            saida = await ferramenta("show_permissions", {"channel": str(texto.id)})
            self.assert_true("everyone" in saida.lower(),
                             f"show_permissions não listou a @everyone (API tem {len(na_api.overwrites)} "
                             f"sobrescrita(s)): {saida[:120]}")

            # `target` precisa filtrar de verdade (antes era ignorado em silêncio)
            filtrado_dono = await ferramenta("show_permissions", {"channel": str(texto.id),
                                                                  "target": str(live.actor.id)})
            self.assert_true(live.actor.name.lower() in filtrado_dono.lower(),
                             f"show_permissions(target) não mostrou o autor: {filtrado_dono[:120]!r}")
            alheios = await ferramenta("show_permissions", {"channel": str(texto.id), "target": "@everyone"})
            self.assert_true("everyone" in alheios.lower(),
                             f"show_permissions(target=@everyone) não mostrou a @everyone: {alheios[:120]!r}")
            return "set, sync, clear e show (com filtro por target) confirmados pela API"

        await self.check(phase, "permissões de canal confirmadas pela API", permissoes)

        async def importar() -> tuple[str, dict[str, Any]]:
            antes_import = await self._api_state(guild)
            nomes_import = [f"{TEMP_MARK} importado", f"{TEMP_MARK} cat-importada",
                            f"{TEMP_MARK}-imp-texto", f"{TEMP_MARK} imp-voz"]
            payload = json.dumps({"roles": [{"name": nomes_import[0]}],
                                  "categories": [{"name": nomes_import[1], "channels": [
                                      {"name": nomes_import[2]},
                                      {"name": nomes_import[3], "type": "voice"}]}]})
            await ferramenta("import_structure", {"structure_json": payload})
            novos = await self._capture_new(guild, antes_import, conhecidos=nomes_import)
            self.assert_true(any(c.type.name == "category" for c in novos), "categoria do import não criada")
            self.assert_true(sum(1 for c in novos if c.type.name in ("text", "voice")) == 2,
                             f"canais do import incompletos ({[c.name for c in novos]})")
            cargos_novos = [r.name for r in await guild.fetch_roles() if r.id in self.owned_roles]
            self.assert_true(any("importado" in n for n in cargos_novos), f"cargo do import ausente: {cargos_novos}")
            return f"import recriou {len(novos)} canais e {len(cargos_novos)} cargo(s)", {"canais": len(novos)}

        await self.check(phase, "import_structure recriou a estrutura", importar)

        async def confirmacao_canais() -> str:
            antes_conf = await self._api_state(guild)
            await ferramenta("create_channels", {"channels": [
                {"name": f"{TEMP_MARK}-conf-1", "type": "text", "category": str(categoria.id)},
                {"name": f"{TEMP_MARK}-conf-2", "type": "text", "category": str(categoria.id)}]})
            novos = await self._capture_new(guild, antes_conf)
            ids = [c.id for c in novos if c.type.name == "text"]
            self.assert_true(len(ids) == 2, f"esperava 2 canais de teste, veio {len(ids)}")
            from dataclasses import replace as _replace

            cauteloso = _replace(ctx, confirm_destructive=True)
            try:
                await execute_tool("delete_channels", {"channels": [str(i) for i in ids]}, cauteloso)
            except ToolError as exc:
                self.assert_true("confirm" in str(exc).lower(), f"o erro não pede confirmação: {exc}")
            else:
                raise AssertionError("apagar 2 canais não pediu confirmação no modo cauteloso")
            vivos = [c for c in await guild.fetch_channels() if c.id in ids]
            self.assert_true(len(vivos) == 2, "os canais foram apagados antes da confirmação")
            await ferramenta("delete_channels", {"channels": [str(i) for i in ids], "confirmed": True})
            restantes = [c for c in await guild.fetch_channels() if c.id in ids]
            self.assert_true(not restantes, f"confirmed=true não apagou: {[c.name for c in restantes]}")
            for i in ids:
                self.owned_channels.discard(i)
            return "2 canais: modo cauteloso pediu confirmação e só apagou com confirmed=true"

        await self.check(phase, "fluxo de confirmação em canais reais (modo cauteloso)", confirmacao_canais)

        async def lote_direto_em_canais_reais() -> str:
            """Padrão do bot: 'apague esses e deixe só um' executa e responde na hora."""
            antes_direto = await self._api_state(guild)
            await ferramenta("create_channels", {"channels": [
                {"name": f"{TEMP_MARK}-dir-1", "type": "text", "category": str(categoria.id)},
                {"name": f"{TEMP_MARK}-dir-2", "type": "text", "category": str(categoria.id)}]})
            novos_direto = await self._capture_new(guild, antes_direto)
            ids_direto = [c.id for c in novos_direto if c.type.name == "text"]
            self.assert_true(len(ids_direto) == 2, "não consegui criar os canais do teste direto")
            resultado = await ferramenta("delete_channels", {"channels": [str(i) for i in ids_direto]})
            self.assert_true("Exclusão concluída" in resultado,
                             f"modo direto não respondeu o que fez: {resultado[:120]!r}")
            restantes_direto = [c for c in await guild.fetch_channels() if c.id in ids_direto]
            self.assert_true(not restantes_direto, "modo direto não apagou os canais")
            for i in ids_direto:
                self.owned_channels.discard(i)
            return "2 canais reais apagados direto, sem perguntar, com o resultado na resposta"

        await self.check(phase, "exclusão em lote direta em canais reais", lote_direto_em_canais_reais)

        async def agente_apaga_nominal() -> str:
            antes_efemero = await self._api_state(guild)
            payload = json.dumps({"categories": [{"name": f"{TEMP_MARK} alvo-agente",
                                                  "channels": [{"name": f"{TEMP_MARK}-efemero"}]}]})
            await ferramenta("import_structure", {"structure_json": payload})
            novos = await self._capture_new(guild, antes_efemero)
            alvo = next((c for c in novos if c.type.name == "text"), None)
            self.assert_true(alvo is not None, "não consegui criar o canal efêmero do teste do agente")
            registro_llm.clear()
            _t_nominal = time.perf_counter()
            try:
                resposta = await live.agent.process_turn(guild=guild, channel=ctx.channel, actor=live.actor,
                                                         prompt=f"Apague o canal {TEMP_MARK}-efemero agora.")
            except Exception as exc:
                if self._culpa_do_llm(str(exc)):
                    return self.degradar_llm(phase, "agente apaga canal nominal sem travar",
                                             "não deu para conversar: o LLM não respondeu", str(exc))
                raise
            existe = any(c.id == alvo.id for c in await guild.fetch_channels())
            if existe and (self._culpa_do_llm(resposta)
                           or self.llm_nao_chamou(registro_llm, "delete_channels")):
                return self.degradar_llm(phase, "agente apaga canal nominal sem travar",
                                         "o agente não pediu a exclusão do canal efêmero", resposta)
            self.assert_true(not existe, f"o agente não apagou um canal nominal único: {resposta[:150]!r}")
            self.owned_channels.discard(alvo.id)
            return (f"agente apagou o canal nominal direto em {time.perf_counter() - _t_nominal:.1f}s: "
                    f"{resposta[:80]!r}")

        await self.check(phase, "agente apaga canal nominal sem travar", agente_apaga_nominal)

        async def agente_apaga_lote_direto() -> str:
            """PADRÃO do bot: 'apague esses dois' executa na hora e responde o que fez."""
            antes_lote = await self._api_state(guild)
            await ferramenta("create_channels", {"channels": [
                {"name": f"{TEMP_MARK}-lote-1", "type": "text", "category": str(categoria.id)},
                {"name": f"{TEMP_MARK}-lote-2", "type": "text", "category": str(categoria.id)}]})
            novos = await self._capture_new(guild, antes_lote)
            ids = {c.id for c in novos}
            self.assert_true(len(ids) == 2, "não consegui criar os 2 canais do lote")
            registro_llm.clear()
            _t0 = time.perf_counter()
            try:
                resposta = await live.agent.process_turn(
                    guild=guild, channel=ctx.channel, actor=live.actor,
                    prompt=f"Apague os canais {TEMP_MARK}-lote-1 e {TEMP_MARK}-lote-2 e deixe só o resto.")
            except Exception as exc:
                if self._culpa_do_llm(str(exc)):
                    return self.degradar_llm(phase, "agente apaga lote direto (padrão)",
                                             "não deu para conversar: o LLM não respondeu", str(exc))
                raise
            restantes = [c for c in await guild.fetch_channels() if c.id in ids]
            if restantes and (self._culpa_do_llm(resposta)
                              or self.llm_nao_chamou(registro_llm, "delete_channels")):
                return self.degradar_llm(
                    phase, "agente apaga lote direto (padrão)",
                    "o modelo não executou a exclusão nesta rodada", resposta)
            self.assert_true(not restantes,
                             f"modo direto não apagou os 2 canais: {resposta[:150]!r}")
            self.assert_true(not any(t in resposta.lower() for t in ("confirm", "posso apagar", "certeza")),
                             f"modo direto não pode pedir confirmação: {resposta[:150]!r}")
            segundos = time.perf_counter() - _t0
            chamadas = len(registro_llm)
            for i in ids:
                self.owned_channels.discard(i)
            return (f"apagou os 2 canais direto em {segundos:.1f}s "
                    f"({chamadas} ida(s) ao LLM): {resposta[:60]!r}")

        await self.check(phase, "agente apaga lote direto, sem perguntar (padrão)", agente_apaga_lote_direto)

        async def agente_cauteloso_pergunta() -> str:
            """Com CONFIRM_DESTRUCTIVE=true o bot volta a pedir o 'sim' antes do lote."""
            antes_conf = await self._api_state(guild)
            await ferramenta("create_channels", {"channels": [
                {"name": f"{TEMP_MARK}-caut-1", "type": "text", "category": str(categoria.id)},
                {"name": f"{TEMP_MARK}-caut-2", "type": "text", "category": str(categoria.id)}]})
            novos = await self._capture_new(guild, antes_conf)
            ids = {c.id for c in novos}
            self.assert_true(len(ids) == 2, "não consegui criar os 2 canais do modo cauteloso")

            live.agent.confirm_destructive = True
            try:
                registro_llm.clear()
                try:
                    resposta = await live.agent.process_turn(
                        guild=guild, channel=ctx.channel, actor=live.actor,
                        prompt=f"Apague os canais {TEMP_MARK}-caut-1 e {TEMP_MARK}-caut-2 de uma vez.")
                except Exception as exc:
                    if self._culpa_do_llm(str(exc)):
                        return self.degradar_llm(phase, "modo cauteloso pergunta e apaga após 'sim'",
                                                 "não deu para conversar: o LLM não respondeu", str(exc))
                    raise
                vivos = [c for c in await guild.fetch_channels() if c.id in ids]
                if len(vivos) != 2:
                    return self.degradar_llm(
                        phase, "modo cauteloso pergunta e apaga após 'sim'",
                        "o modelo apagou sem esperar o 'sim'", resposta)
                if self.llm_nao_chamou(registro_llm, "delete_channels"):
                    return self.degradar_llm(phase, "modo cauteloso pergunta e apaga após 'sim'",
                                             "o modelo nem tentou excluir os canais", resposta)
                self.assert_true(any(t in resposta.lower() for t in ("confirm", "posso", "certeza", "apagar")),
                                 f"não pediu confirmação no texto: {resposta[:150]!r}")

                registro_llm.clear()
                try:
                    resposta2 = await live.agent.process_turn(guild=guild, channel=ctx.channel,
                                                              actor=live.actor, prompt="sim, pode apagar")
                except Exception as exc:
                    if self._culpa_do_llm(str(exc)):
                        return self.degradar_llm(phase, "modo cauteloso pergunta e apaga após 'sim'",
                                                 "o 'sim' não pôde ser processado", str(exc))
                    raise
                restantes = [c for c in await guild.fetch_channels() if c.id in ids]
                if restantes and (self._culpa_do_llm(resposta2) or self._culpa_do_llm(resposta)
                                  or self.llm_nao_chamou(registro_llm, "delete_channels")):
                    return self.degradar_llm(phase, "modo cauteloso pergunta e apaga após 'sim'",
                                             "não apagou depois do 'sim'", resposta2)
                self.assert_true(not restantes, f"não apagou depois do 'sim': {resposta2[:150]!r}")
            finally:
                live.agent.confirm_destructive = False

            for i in ids:
                self.owned_channels.discard(i)
            return f"pediu confirmação e apagou depois do 'sim' ({resposta[:60]!r})"

        await self.check(phase, "modo cauteloso pergunta e apaga após 'sim' (CONFIRM_DESTRUCTIVE)", agente_cauteloso_pergunta)

        if self.args.allow_template:
            async def template() -> tuple[str, dict[str, Any]]:
                from brain.ops import TEMPLATES_DATA

                nomes_tpl = [r["name"] for r in TEMPLATES_DATA["estudos"]["roles"]]
                for cat in TEMPLATES_DATA["estudos"]["categories"]:
                    nomes_tpl.append(cat["name"])
                    nomes_tpl += [c["name"] for c in cat["channels"]]
                antes_tpl = await self._api_state(guild)
                await ferramenta("apply_template", {"template": "estudos"})
                novos = await self._capture_new(guild, antes_tpl, conhecidos=nomes_tpl)
                cargos_tpl = [r for r in await guild.fetch_roles() if r.id in self.owned_roles]
                self.assert_true(len(novos) >= 5, f"o template criou poucos canais: {len(novos)}")
                self.assert_true(len(cargos_tpl) >= 2, f"o template criou poucos cargos: {len(cargos_tpl)}")

                # o bug do `category` duplicado quebrava isto: cada canal precisa ficar DENTRO da sua categoria
                cats_novas = {c.id: c.name for c in novos if c.type.name == "category"}
                self.assert_true(len(cats_novas) == 3, f"esperava 3 categorias do template: {list(cats_novas.values())}")
                pendurados = [c for c in novos if c.type.name in ("text", "voice")]
                foras = [c.name for c in pendurados if c.category_id not in cats_novas]
                self.assert_true(not foras, f"canais do template fora das categorias criadas: {foras}")
                return (f"template 'estudos' criou {len(cats_novas)} categorias, {len(pendurados)} canais dentro delas "
                        f"e {len(cargos_tpl)} cargos (todos registrados para limpeza)"), {"canais": len(novos)}

            await self.check(phase, "apply_template (--allow-template)", template)
        else:
            self.rep.record(phase, "apply_template", SKIP,
                            "não testado: cria ~11 canais e 5 cargos no servidor; rode com --allow-template")

        self.rep.record(phase, "edit_server / set_icon no servidor real", SKIP,
                        "não executado de propósito (renomearia o servidor / trocaria o ícone real); a fase spy prova "
                        "que set_icon agora baixa a imagem e manda os bytes em guild.edit(icon=...)")

        await self._cleanup(guild, phase)

    # =====================================================================
    # botloop
    # =====================================================================
    async def phase_botloop(self) -> None:
        import discord

        from core.bot import FarolBot

        phase = "botloop"
        if not self.args.mutate:
            self.rep.record(phase, "loop do bot", SKIP, "rode com --mutate (cria um canal de teste temporário)")
            return
        live = await self.ensure_live(phase)
        if live is None:
            self.rep.record(phase, "loop do bot", SKIP, "sem conexão ao Discord")
            return

        guild = live.primary
        registro_llm: list[dict[str, Any]] = []
        live.agent.llm = LLMRegistro(live.agent.llm, registro_llm)
        bot = FarolBot(config=live.config, agent=live.agent)
        connect_task = None
        canal = None
        try:
            ready = asyncio.Event()

            @bot.event
            async def on_ready() -> None:  # noqa: ANN202
                ready.set()

            await bot.login(live.config.discord_token)
            connect_task = asyncio.create_task(bot.connect(reconnect=False))
            await asyncio.wait_for(ready.wait(), timeout=self.args.connect_timeout)

            # o bot 24/7 de produção está online com o mesmo token: este clone não pode
            # responder as mensagens reais dos clientes (o teste usa mensagens falsas)
            self.silenciar_mensagens_reais(bot)

            async def criar_canal() -> str:
                nonlocal canal
                antes = await self._api_state(guild)
                canal = await guild.create_text_channel(f"{TEMP_MARK}-loop-do-bot")
                self.owned_channels.add(canal.id)
                await self._capture_new(guild, antes)
                return f"canal temporário {canal.name} ({canal.id}) criado"

            await self.check(phase, "canal temporário de teste", criar_canal)
            if canal is None:
                return

            antes_cat = await self._api_state(guild)
            categoria = await guild.create_category(f"{TEMP_MARK} categoria-loop")
            self.owned_channels.add(categoria.id)
            await self._capture_new(guild, antes_cat)

            anchor = await canal.send(f"{TEMP_MARK} âncora do teste e2e — as reações abaixo são do bot de verdade")

            class FakeMessage:
                """Emula uma mensagem de um humano para acionar o on_message real."""

                def __init__(self, channel: Any, author: Any, content: str, mentions: list[Any]) -> None:
                    self.channel = channel
                    self.guild = channel.guild
                    self.author = author
                    self.content = content
                    self.mentions = mentions
                    self.attachments: list[Any] = []
                    self.id = anchor.id
                    self.reactions: list[str] = []
                    self.replies: list[str] = []

                async def add_reaction(self, emoji: str) -> None:
                    self.reactions.append(emoji)
                    with contextlib.suppress(Exception):
                        await anchor.add_reaction(emoji)

                async def remove_reaction(self, emoji: str, member: Any) -> None:
                    if emoji in self.reactions:
                        self.reactions.remove(emoji)
                    with contextlib.suppress(Exception):
                        await anchor.remove_reaction(emoji, member)

                async def reply(self, content: str, mention_author: bool = True) -> Any:
                    self.replies.append(content)
                    return await self.channel.send(content)

            chamadas: list[str] = []
            done = asyncio.Event()
            original = bot._process_message_safe

            async def spy(message: Any) -> None:
                chamadas.append(getattr(message, "content", ""))
                try:
                    await original(message)
                finally:
                    done.set()

            bot._process_message_safe = spy  # type: ignore[assignment]

            async def ignora_sem_mencao() -> str:
                msg = FakeMessage(canal, live.actor, "bom dia pessoal", mentions=[])
                chamadas.clear()
                await bot.on_message(msg)
                await asyncio.sleep(1.5)
                self.assert_true(not chamadas, f"o bot processou mensagem sem menção: {chamadas}")
                self.assert_true(not msg.replies, "o bot respondeu sem ser mencionado")
                return "mensagem sem menção ignorada"

            await self.check(phase, "ignora mensagem sem menção", ignora_sem_mencao)

            async def ignora_bots() -> str:
                outro = type("OutroBot", (), {"bot": True, "id": 999, "name": "outro-bot",
                                              "display_name": "outro-bot", "roles": [],
                                              "guild_permissions": live.actor.guild_permissions,
                                              "top_role": guild.me.top_role})()
                msg = FakeMessage(canal, outro, f"<@{bot.user.id}> liste os cargos", mentions=[bot.user])
                chamadas.clear()
                await bot.on_message(msg)
                await asyncio.sleep(1.0)
                self.assert_true(not chamadas, "o bot processou mensagem de outro bot")
                return "mensagem de outro bot ignorada"

            await self.check(phase, "ignora mensagens de outros bots", ignora_bots)

            async def ramo_dm() -> str:
                enviados: list[str] = []

                class FakeDM(discord.DMChannel):
                    id = 424242

                    def __init__(self) -> None:  # não chama o __init__ pesado do discord.py
                        pass

                    async def send(self, content: str, **kwargs: Any) -> None:
                        enviados.append(content)

                class FakeDMMessage(FakeMessage):
                    def __init__(self) -> None:
                        # não usa o __init__ do FakeMessage: DMChannel não tem .guild
                        self.channel = FakeDM()
                        self.guild = None
                        self.author = live.actor
                        self.content = "oi"
                        self.mentions = []
                        self.attachments = []
                        self.id = anchor.id
                        self.reactions = []
                        self.replies = []

                    async def reply(self, content: str, mention_author: bool = True) -> None:
                        enviados.append(content)

                msg = FakeDMMessage()
                await bot.on_message(msg)
                self.assert_true(bool(enviados), "o bot não respondeu na DM")
                self.assert_true("farol" in enviados[0].lower(), f"resposta de DM inesperada: {enviados[0][:80]}")
                self.assert_true(not chamadas, "o bot tentou processar comando em DM")
                return f"DM respondida com o aviso de escopo: {enviados[0][:60]!r}"

            await self.check(phase, "DM é respondida com o aviso de escopo", ramo_dm)

            async def menciona_dispara() -> str:
                if config_permite_canal is False:
                    return "pulado: ALLOWED_CHANNEL_IDS está configurado e o canal de teste não está na lista"
                msg = FakeMessage(canal, live.actor,
                                  f"<@{bot.user.id}> diga em uma linha o nome deste servidor", mentions=[bot.user])
                chamadas.clear()
                registro_llm.clear()
                done.clear()
                await bot.on_message(msg)
                await asyncio.wait_for(done.wait(), timeout=self.args.llm_timeout * 3)
                self.assert_true(bool(msg.replies), "o bot não respondeu à menção")
                texto = "\n".join(msg.replies)
                self.assert_true(guild.name.lower() in texto.lower() or len(texto) > 20,
                                 f"resposta suspeita: {texto[:120]!r}")
                return f"on_message → agente → resposta real no canal: {texto.strip()[:100]!r}"

            permitidos = set(getattr(live.config, "allowed_channel_ids", set()) or set())
            config_permite_canal = not permitidos or canal.id in permitidos
            await self.check(phase, "menção dispara o agente e responde", menciona_dispara)

            async def reacoes() -> tuple[str, dict[str, Any]]:
                atual = await canal.fetch_message(anchor.id)
                emojis = [str(r.emoji) for r in atual.reactions]
                self.assert_true("✅" in emojis, f"o bot não marcou ✅ (reações: {emojis})")
                self.assert_true("👀" not in emojis, f"o 👀 ficou pendurado (reações: {emojis})")
                return f"reações corretas no Discord real: {emojis}", {"reacoes": emojis}

            await self.check(phase, "reações de feedback 👀→✅", reacoes)

            async def cria_por_mensagem() -> str:
                antes_msg = await self._api_state(guild)
                msg = FakeMessage(canal, live.actor,
                                  f"<@{bot.user.id}> crie um canal de texto chamado {TEMP_MARK}-via-bot "
                                  f"dentro da categoria {categoria.name}", mentions=[bot.user])
                chamadas.clear()
                done.clear()
                await bot.on_message(msg)
                await asyncio.wait_for(done.wait(), timeout=self.args.llm_timeout * 3)
                novos = await self._capture_new(guild, antes_msg)
                if not novos and (self._culpa_do_llm(" ".join(msg.replies))
                                  or self.llm_nao_chamou(registro_llm, "create_channels")):
                    return self.degradar_llm(phase, "ferramenta real acionada por mensagem",
                                             "o bot não criou o canal", " ".join(msg.replies))
                self.assert_true(bool(novos), f"o bot não criou o canal (resposta: {msg.replies[-1:]})")
                return f"o bot criou de verdade: {[c.name for c in novos]}"

            await self.check(phase, "ferramenta real acionada por mensagem", cria_por_mensagem)
        except Exception as exc:
            self.rep.record(phase, "loop do bot", FAIL, f"{type(exc).__name__}: {exc}")
        finally:
            with contextlib.suppress(Exception):
                await bot.close()
            if connect_task is not None:
                connect_task.cancel()
                with contextlib.suppress(Exception):
                    await connect_task
            await self._cleanup(guild, phase)

    # =====================================================================
    # sweep
    # =====================================================================
    async def phase_sweep(self) -> None:
        phase = "sweep"
        if not self.args.mutate:
            self.rep.record(phase, "varredura", SKIP, "rode com --mutate")
            return
        live = await self.ensure_live(phase)
        if live is None:
            self.rep.record(phase, "varredura", SKIP, "sem conexão ao Discord")
            return

        guild = live.primary
        removidos, falhas = [], []
        for canal in await guild.fetch_channels():
            if TEMP_MARK not in canal.name:
                continue
            try:
                await canal.delete()
                removidos.append(f"#{canal.name}")
            except Exception as exc:
                falhas.append(f"#{canal.name}: {exc}")
        for papel in await guild.fetch_roles():
            if TEMP_MARK not in papel.name:
                continue
            try:
                await papel.delete()
                removidos.append(f"@{papel.name}")
            except Exception as exc:
                falhas.append(f"@{papel.name}: {exc}")
        if falhas:
            self.rep.record(phase, "varredura de sobras", FAIL,
                            f"não consegui remover: {'; '.join(falhas)} — remova manualmente")
        else:
            self.rep.record(phase, "varredura de sobras", PASS,
                            f"{len(removidos)} objeto(s) de teste removidos ({', '.join(removidos[:12])})"
                            if removidos else "nenhuma sobra de teste encontrada")

    # =====================================================================
    # execução
    # =====================================================================
    async def run(self, phases: list[str]) -> None:
        for phase in phases:
            print(f"\n== fase {phase} — {PHASE_TITLES.get(phase, phase)} ==", flush=True)
            handler = getattr(self, f"phase_{phase}", None)
            if handler is None:
                self.rep.record(phase, "fase desconhecida", FAIL, f"não existe fase '{phase}'")
                continue
            try:
                await handler()
            except Exception as exc:
                log.exception("Fase %s explodiu", phase)
                self.rep.record(phase, "erro inesperado na fase", FAIL, f"{type(exc).__name__}: {exc}")
        await self._shutdown()

    async def _shutdown(self) -> None:
        with contextlib.suppress(Exception):
            if self.env.llm is not None:
                await self.env.llm.close()
        with contextlib.suppress(Exception):
            if self.env.client is not None:
                await self.env.client.close()
        if self.env.connect_task is not None:
            self.env.connect_task.cancel()
            with contextlib.suppress(Exception):
                await self.env.connect_task


# -------------------------------------------------------------------------- CLI


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Harness de teste E2E do Farol")
    parser.add_argument("--phases", default="static,spy,policy",
                        help="fases separadas por vírgula, ou 'all'")
    parser.add_argument("--outdir", default="reports/parts", help="diretório de saída dos relatórios")
    parser.add_argument("--tag", default="", help="nome do arquivo (default: primeira fase)")
    parser.add_argument("--guild-id", dest="guild_id", default="", help="servidor a testar (default: o maior)")
    parser.add_argument("--mutate", action="store_true", help="autoriza mutações reais em objetos de teste")
    parser.add_argument("--allow-template", dest="allow_template", action="store_true",
                        help="autoriza apply_template (cria ~16 objetos; a limpeza usa diff de IDs)")
    parser.add_argument("--connect-timeout", dest="connect_timeout", type=float, default=90.0)
    parser.add_argument("--llm-timeout", dest="llm_timeout", type=float, default=None)
    parser.add_argument("--merge", default="", help="mescla relatórios de um diretório e sai")
    parser.add_argument("--no-annotations", dest="annotations", action="store_false", default=True)
    parser.add_argument("--started-at", dest="started_at", default="", help="ISO da primeira fase (merge)")
    parser.add_argument("--json-stdout", dest="json_stdout", action="store_true")
    parser.add_argument("--resumo-anotacoes", dest="resumo_anotacoes", action="store_true",
                        help="com --merge: publica também o resumo como anotações de check-run")
    return parser.parse_args(argv)


def phases_list(raw: str) -> list[str]:
    if raw.strip() == "all":
        return list(PHASE_ORDER)
    return [p.strip() for p in raw.split(",") if p.strip()]


def merge_parts(directory: Path, outdir: Path, started_at: str = "", anotar: bool = False) -> int:
    parts = sorted(directory.glob("*.json"))
    if not parts:
        print(f"nenhum relatório em {directory}", file=sys.stderr)
        return 1

    checks: list[Check] = []
    meta: dict[str, Any] = {}
    notes: list[str] = []
    started = started_at
    finished = ""
    fases: list[str] = []
    mutacoes = "não"
    for path in parts:
        data = json.loads(path.read_text(encoding="utf-8"))
        started = started or data.get("started_at", "")
        finished = data.get("finished_at") or finished
        parte_meta = data.get("meta", {})
        for fase in str(parte_meta.get("fases", "")).split(","):
            if fase.strip() and fase.strip() not in fases:
                fases.append(fase.strip())
        if parte_meta.get("mutações reais") == "sim":
            mutacoes = "sim"
        meta.update({k: v for k, v in parte_meta.items() if k not in ("fases", "mutações reais")})
        for note in data.get("notes", []):
            if note not in notes:
                notes.append(note)
        for phase, content in data.get("phases", {}).items():
            for raw in content.get("checks", []):
                checks.append(Check(phase=raw.get("phase", phase), name=raw.get("name", ""),
                                    status=raw.get("status", "SKIP"), detail=raw.get("detail", ""),
                                    ms=int(raw.get("ms", 0)), data=raw.get("data", {}) or {}))
    if fases:
        meta["fases"] = ", ".join(fases)
    meta["mutações reais"] = mutacoes

    reporter = Reporter([], meta)
    reporter.started = datetime.fromisoformat(started) if started else datetime.now(timezone.utc)
    reporter.notes = notes
    for check in checks:
        reporter.phases.setdefault(check.phase, []).append(check)

    outdir.mkdir(parents=True, exist_ok=True)
    payload = reporter.to_dict()
    payload["finished_at"] = finished or payload["finished_at"]
    (outdir / "e2e-latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md = reporter.to_markdown()
    (outdir / "e2e-latest.md").write_text(md, encoding="utf-8")
    print(md)
    if anotar:
        reporter.emit_annotations()
    return reporter.exit_code()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.merge:
        return merge_parts(Path(args.merge), Path(args.outdir), args.started_at, anotar=args.resumo_anotacoes)

    phases = phases_list(args.phases)
    started = datetime.now(timezone.utc)

    if args.llm_timeout is None:
        try:
            args.llm_timeout = float(os.environ.get("LLM_TIMEOUT", "") or 60.0)
        except ValueError:
            args.llm_timeout = 60.0
    if not args.llm_timeout:
        args.llm_timeout = 60.0

    meta: dict[str, Any] = {
        "fases": ", ".join(phases),
        "mutações reais": "sim" if args.mutate else "não",
        "python": platform.python_version(),
        "runner": os.environ.get("RUNNER_OS", "local"),
        "commit": (os.environ.get("GITHUB_SHA") or "")[:7],
        "execução": os.environ.get("GITHUB_RUN_ID", "local"),
    }
    try:
        import discord

        meta["discord.py"] = discord.__version__
    except Exception:  # pragma: no cover
        pass

    reporter = Reporter(phases, meta)
    harness = Harness(args, reporter)
    try:
        asyncio.run(harness.run(phases))
    except KeyboardInterrupt:  # pragma: no cover
        reporter.note("execução interrompida pelo usuário")
    finally:
        reporter.started = started
        outdir = Path(args.outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        tag = args.tag or phases[0]
        (outdir / f"{tag}.json").write_text(json.dumps(reporter.to_dict(), ensure_ascii=False, indent=2),
                                            encoding="utf-8")
        (outdir / f"{tag}.md").write_text(reporter.to_markdown(), encoding="utf-8")
        if args.annotations:
            reporter.emit_annotations()
        if args.json_stdout:
            print(json.dumps(reporter.counts(), ensure_ascii=False), flush=True)

    counts = reporter.counts()
    print(f"\nresumo ({', '.join(phases)}): ✅ {counts[PASS]} · ❌ {counts[FAIL]} · ⚠️ {counts[WARN]} · "
          f"⏭️ {counts[SKIP]}", flush=True)
    return reporter.exit_code()


if __name__ == "__main__":
    sys.exit(main())
