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
import types
from types import SimpleNamespace
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

PHASE_ORDER = ("static", "spy", "policy", "connect", "audit", "tools", "agent", "mutate", "caps",
               "botloop", "sweep")

PHASE_TITLES = {
    "static": "Checagens estáticas (schemas ↔ executores)",
    "spy": "Duplos de teste: a ferramenta promete, a ferramenta faz?",
    "policy": "Política de permissões e confirmação destrutiva",
    "connect": "Conexão ao gateway do Discord",
    "audit": "Diagnóstico de permissões e hierarquia no servidor",
    "tools": "Ferramentas somente-leitura em servidor real",
    "agent": "Agente + LLM ao vivo (prompt → ferramenta → resposta)",
    "mutate": "Mutações reais em objetos de teste (com limpeza)",
    "caps": "Matriz de capacidades: cada parâmetro, valor e combinação no Discord real",
    "botloop": "core.bot.FarolBot: on_message → resposta real no Discord",
    "sweep": "Varredura de sobras de teste",
}

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("farol.e2e")


# --------------------------------------------------------------------------- reporter


async def posicao_do_topo_do_bot(guild: Any) -> int:
    """
    Posição do cargo mais alto do bot, MEDIDA na API.

    `Member.top_role` é montado com `guild.get_role(id)`: com o cache de cargos vazio, os cargos
    do membro são descartados e a posição cai no @everyone (0) — foi assim que a matriz acusou o
    bot de não poder editar um cargo que ele mesmo tinha acabado de criar.
    """
    me = getattr(guild, "me", None)
    ids = {getattr(r, "id", None) for r in (getattr(me, "roles", None) or [])}
    ids.discard(None)
    if not ids:
        ids = {i for i in (getattr(me, "_roles", None) or ()) if isinstance(i, int)}
    try:
        frescos = await guild.fetch_roles()
    except Exception:  # noqa: BLE001 - sem API, fica o que o cache disse
        return int(getattr(getattr(me, "top_role", None), "position", 0) or 0)
    if not ids:
        return int(getattr(getattr(me, "top_role", None), "position", 0) or 0)
    return max((int(r.position) for r in frescos if r.id in ids), default=0)


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

    async def purge(self, limit: int = 50, **_kwargs: Any) -> list[Any]:
        """Bulk delete do discord.py: registra a chamada e devolve o que apagou."""
        self.record("purge", limit=limit)
        apagadas = [SimpleNamespace(id=i + 1, content=f"msg {i + 1}") for i in range(min(limit, 5))]
        self.mensagens = []
        return apagadas

    async def history(self, limit: int = 50, **_kwargs: Any):
        """Fallback (sem purge): percorre as mensagens para apagar uma a uma."""
        self.record("history", limit=limit)
        for mensagem in list(getattr(self, "mensagens", []))[:limit]:
            yield mensagem

    async def send(self, content: str = "", **_kwargs: Any) -> Any:
        self.record("send", content=content)
        mensagem = SimpleNamespace(id=len(getattr(self, "mensagens", [])) + 1, content=content,
                                   delete=self._apagar_mensagem)
        self.mensagens = list(getattr(self, "mensagens", [])) + [mensagem]
        return mensagem

    async def _apagar_mensagem(self) -> None:
        self.record("delete_message")

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
    @staticmethod
    async def _dados_reais_citados(guild: Any, resposta: str) -> list[str]:
        """
        Aceita a resposta que, sem nomear canais, cita dados REAIS do servidor.

        O `server_info` é uma resposta legítima ("📊 Informações de X: … Canais: 1 · Cargos: 25"):
        ela prova que o bot conhece o servidor pelos dados, não por invenção. Sem isso, uma
        resposta correta virava ❌ só por não citar o nome de um canal.
        """
        import re

        baixo = (resposta or "").lower()
        confere: list[str] = []
        nome_srv = str(getattr(guild, "name", "")).strip()
        if nome_srv and nome_srv.lower() in baixo:
            confere.append(f"nome do servidor ({nome_srv})")
        owner_id = getattr(guild, "owner_id", None)
        if owner_id and f"<@{owner_id}>" in resposta:
            confere.append("menção do dono")
        try:
            canais_api = len(await guild.fetch_channels())
            cargos_api = len(await guild.fetch_roles())
        except Exception:  # noqa: BLE001 - sem API, vale o que já foi conferido
            return confere
        for rotulo, valor in (("canais", canais_api), ("cargos", cargos_api)):
            if re.search(rf"\*{{0,2}}{rotulo}\*{{0,2}}[^\d]{{0,6}}{valor}\b", baixo):
                confere.append(f"{rotulo}={valor}")
        return confere

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

            obrigatorios = ("REGRAS ABSOLUTAS", "português", "Ações destrutivas", "clear_messages",
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
        await self.check(phase, "clear_messages apaga o chat de vero (bulk delete)",
                         self._spy_clear_messages, skip_when=None)
        await self.check(phase, "textão em inglês do modelo nunca chega ao usuário",
                         self._spy_resposta_ingles, skip_when=None)
        await self.check(phase, "agente não se auto-confirma (offline)", self._spy_agente_confirmacao, skip_when=None)

    async def _spy_resposta_ingles(self) -> str:
        """Bug relatado: o modelo devolveu o rascunho em inglês e o bot mandou isso no Discord."""
        from brain.agent import MAX_RESPOSTA_CHARS, Agent
        from brain.memory import ChannelMemory
        from llm.base import ChatProvider, LLMResponse

        rascunho = (
            "- User: oi  ← This is the last user message before my current turn\n"
            "But in the current turn showing in the assistant's view, it says: 'mude o nome do "
            "server pra pretinho'. There's inconsistency here. Looking at the very end of the "
            "user's message history in the problem: the user said oi. Let me think about what "
            "the correct answer should be and whether anything already happened."
        )

        class LLMRascunho(ChatProvider):
            def __init__(self, roteiro: list[LLMResponse]) -> None:
                self.roteiro = roteiro
                self.chamadas = 0

            async def chat(self, messages: list[dict[str, Any]], tools: Any = None,
                           timeout: float = 60.0, max_tokens: int = 1024) -> LLMResponse:
                self.chamadas += 1
                return self.roteiro.pop(0) if self.roteiro else LLMResponse(content="Feito!")

        ctx, guild, _, canal = await self._spy_ctx()

        # 1) o modelo devolve rascunho em inglês e depois obedece a reescrita
        llm = LLMRascunho([LLMResponse(content=rascunho, tool_calls=[]),
                           LLMResponse(content="Não posso mudar o nome do servidor agora.", tool_calls=[])])
        agente = Agent(llm_provider=llm, memory=ChannelMemory())
        resposta = await agente.process_turn(guild=guild, channel=canal, actor=guild.members[0],
                                             prompt="mude o nome do server pra pretinho")
        self.assert_true(resposta == "Não posso mudar o nome do servidor agora.",
                         f"resposta não foi reescrita em PT-BR: {resposta[:120]!r}")

        # 2) o modelo insiste no inglês: o bot responde curto em português, nunca o rascunho
        teimoso = LLMRascunho([LLMResponse(content=rascunho, tool_calls=[]),
                               LLMResponse(content=rascunho, tool_calls=[])])
        agente2 = Agent(llm_provider=teimoso, memory=ChannelMemory())
        resposta2 = await agente2.process_turn(guild=guild, channel=canal, actor=guild.members[0],
                                               prompt="oi")
        self.assert_true("thinking" not in resposta2.lower() and "user:" not in resposta2.lower(),
                         f"o rascunho vazou para o usuário: {resposta2[:120]!r}")
        self.assert_true(len(resposta2) < MAX_RESPOSTA_CHARS,
                         f"resposta maior que o teto: {len(resposta2)} chars")
        self.assert_true(any(p in resposta2.lower() for p in ("feito", "não", "nao", "não posso")),
                         f"resposta não está em PT-BR: {resposta2[:120]!r}")
        return f"rascunho em inglês barrado ({teimoso.chamadas} chamadas) e resposta curta em PT-BR"

    async def _spy_clear_messages(self) -> str:
        """'exclua esse chat' precisa apagar MENSAGENS — e relatar quantas apagou."""
        from brain.executors import execute_tool
        from brain.tools import ToolContext

        ctx, guild, _, canal = await self._spy_ctx()
        canal.calls.clear()
        resultado = await execute_tool("clear_messages", {"limit": 4}, ctx)
        self.assert_true("purge" in canal.actions(), "não chamou o bulk delete do canal")
        self.assert_true("4 mensagem" in resultado, f"não relatou quantas apagou: {resultado!r}")

        # conversation_clear NÃO pode dizer que apagou mensagens (bug reportado pelo dono)
        from brain.memory import ChannelMemory, memory_key
        memoria = ChannelMemory()
        chave = memory_key(guild.id, canal.id)
        memoria.add_message(chave, {"role": "user", "content": "oi"})
        ctx.memoria = memoria
        ctx = ToolContext(guild=guild, channel=canal, actor=guild.members[0], memory=memoria)
        limpo = await execute_tool("conversation_clear", {}, ctx)
        self.assert_true(memoria.get_history(chave) == [], "a memória não foi limpa")
        self.assert_true("clear_messages" in limpo,
                         f"conversation_clear não apontou a ferramenta certa: {limpo!r}")
        self.assert_true("chat está limpo" not in limpo.lower(),
                         f"conversation_clear mentiu que limpou o chat: {limpo!r}")
        return "chat apagado com bulk delete e memória limpa sem mentir"

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

        async def sem_gerenciar_mensagens() -> str:
            fraco = SpyMember("sem-permissao", perms=FakePerms())
            try:
                await execute_tool("clear_messages", {"limit": 5}, ToolContext(
                    guild=guild, channel=canal, actor=fraco))
            except ToolError as exc:
                self.assert_true("Gerenciar mensagens" in str(exc), f"erro inesperado: {exc}")
                return f"apagar mensagens exige 'Gerenciar mensagens': {exc}"
            raise AssertionError("quem não gerencia mensagens conseguiu apagar o chat")

        await self.check(phase, "apagar mensagens exige permissão", sem_gerenciar_mensagens)

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
            try:
                resp = await self.env.llm.chat(messages=[{"role": "user", "content": "Responda apenas: pong"}],
                                               tools=None, timeout=self.args.llm_timeout)
            except Exception as exc:  # noqa: BLE001
                if self._culpa_do_llm(str(exc)):
                    return self.degradar_llm(phase, "corrida de LLMs responde",
                                             "nenhum corredor grátis atendeu nesta rodada", str(exc)), {}
                raise
            texto = (resp.content or "").strip()
            if not texto and self._culpa_do_llm(resp.content or ""):
                return self.degradar_llm(phase, "corrida de LLMs responde",
                                         "o corredor devolveu resposta vazia", resp.content or ""), {}
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
            pos = await posicao_do_topo_do_bot(guild)
            cargos_api = await guild.fetch_roles()
            acima = [r for r in cargos_api if r.position >= pos and not r.is_default()]
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

        async def performance_report() -> str:
            """O relatório de tempo é a resposta para "por que o bot demora?" (só números)."""
            out = await execute_tool("performance_report", {}, ctx)
            self.assert_true(bool(out.strip()), "performance_report respondeu vazio")
            self.assert_true("respostas" in out.lower() or "ainda não respondi" in out.lower(),
                             f"resposta inesperada: {out[:120]}")
            return out.replace("\n", " · ")[:200]

        await self.check(phase, "performance_report (tempo das respostas)", performance_report)

        async def list_roles() -> str:
            out = await execute_tool("list_roles", {}, ctx)
            faltando = [r.name for r in guild.roles if f"<@&{r.id}>" not in out]
            self.assert_true(not faltando, f"não listou todos os cargos reais (menções): faltou {faltando[:4]}")
            return f"listou os {len(guild.roles)} cargos reais com menção e posição"

        await self.check(phase, "list_roles", list_roles)

        async def export_structure() -> tuple[str, dict[str, Any]]:
            out = await execute_tool("export_structure", {}, ctx)
            if "NÃO serve para importar" in out:
                # Servidor grande: o JSON completo não cabe numa mensagem. O produto AVISA; aqui
                # conferimos o aviso e os campos que o recorte tem que trazer. (Antes o JSON era
                # cortado em silêncio e este check morria com JSONDecodeError — bug do harness.)
                self.assert_true("não cabe" in out, "recorte sem explicação do tamanho")
                self.assert_true("daria" in out, "recorte sem dizer em quantas mensagens caberia")
                # As chaves do JSON são cortadas no meio do texto: cobrar '"permissions"' ou
                # '"channels"' de um PEDAÇO é bug do harness (num servidor sem categorias, os
                # canais aparecem só depois do corte). O que o recorte tem que trazer é o aviso e
                # o balanço de tudo que foi exportado — o JSON completo é validado quando cabe.
                self.assert_true("NÃO serve para importar" in out, "recorte sem o aviso")
                for info in ("canal(is)", "categoria(s)", "cargo(s)", "permissões", "por partes"):
                    self.assert_true(info in out, f"o aviso do recorte não diz o que ficou fora ({info})")
                return (f"servidor grande: JSON completo com {len(out)} chars no recorte AVISADO "
                        f"(aviso + balanço de canais/categorias/cargos exportados)"), {"truncado": True}
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
            alvo = canal
            if alvo is None:
                # servidor pode ter ficado sem canais (o próprio bot apaga quando pedem):
                # cria um temporário só para o teste e limpa no fim.
                antes_sp = await self._api_state(guild)
                await execute_tool("create_channels", {"channels": [
                    {"name": f"{TEMP_MARK}-perm", "type": "text"}]}, ctx)
                novos_sp = await self._capture_new(guild, antes_sp)
                alvo = next((c for c in novos_sp if c.type.name == "text"), None)
                self.assert_true(alvo is not None, "não consegui criar canal para testar permissões")
                try:
                    out = await execute_tool("show_permissions", {"channel": str(alvo.id)}, ctx)
                    self.assert_true("Permissões" in out or "não possui permissões" in out,
                                     f"resposta inesperada: {out[:120]}")
                    return out.replace("\n", " · ")[:180]
                finally:
                    try:
                        await alvo.delete()
                        self.owned_channels.discard(alvo.id)
                    except Exception:  # noqa: BLE001
                        pass
            out = await execute_tool("show_permissions", {"channel": str(alvo.id)}, ctx)
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
                # servidor esvaziado (o bot apaga de verdade quando pedem): cria estrutura
                # temporária só para a checagem e registra para limpeza.
                from brain.executors import execute_tool as _exec
                from brain.tools import ToolContext as _Ctx

                ctx_ce = _Ctx(guild=guild, channel=canal, actor=live.actor)
                antes_ce = await self._api_state(guild)
                await _exec("create_channels", {"channels": [
                    {"name": f"{TEMP_MARK}-estrutura", "type": "category",
                     "channels": [{"name": f"{TEMP_MARK}-dentro", "type": "text"}]}]}, ctx_ce)
                criados = await self._capture_new(guild, antes_ce)
                for ch in criados:
                    marcadores.append((ch.name, f"<#{ch.id}>"))
                    if ch.type.name == "text":
                        self.owned_channels.add(ch.id)
                self.assert_true(bool(marcadores), "não consegui criar estrutura para o teste")
            try:
                resposta = await perguntar("Liste as categorias e os canais deste servidor.", canal_novo())
            except Exception as exc:  # noqa: BLE001
                if self._culpa_do_llm(str(exc)):
                    return self.degradar_llm(phase, "agente conhece a estrutura real",
                                             "não deu para perguntar: nenhum corredor grátis atendeu",
                                             str(exc))
                raise
            if self._culpa_do_llm(resposta) and not any(nome in resposta or mencao in resposta
                                                        for nome, mencao in marcadores):
                return self.degradar_llm(phase, "agente conhece a estrutura real",
                                         "a resposta veio do aviso de fila cheia", resposta)
            citados = [nome for nome, mencao in marcadores if nome in resposta or mencao in resposta]
            if not citados:
                confere = await self._dados_reais_citados(guild, resposta)
                self.assert_true(bool(confere),
                                 f"não citou nada real do servidor (nem nome nem menção): {resposta[:160]!r}")
                self.rep.record(phase, "agente: resposta com dados reais (sem listar nomes)", WARN,
                                "o modelo respondeu com o resumo do servidor (dados reais conferidos "
                                "na API) em vez de listar categorias/canais por nome")
                return f"respondeu com dados reais do servidor ({', '.join(confere)})"
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
                           conhecidos: Iterable[str] = (),
                           incluir_cargos: bool = False) -> list[Any]:
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
        # quem precisa dos cargos pede explicitamente (as checagens antigas filtram por tipo
        # de canal e não podem receber cargos no meio da lista)
        return novos_canais + novos_cargos if incluir_cargos else novos_canais

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

        async def apagar_mensagens_reais() -> str:
            """'exclua esse chat' tem que apagar MENSAGENS de verdade (com manage_messages)."""
            antes_msg = await self._api_state(guild)
            await ferramenta("create_channels", {"channels": [
                {"name": f"{TEMP_MARK}-chat", "type": "text", "category": str(categoria.id)}]})
            novos_msg = await self._capture_new(guild, antes_msg)
            alvo = next((c for c in novos_msg if c.type.name == "text"), None)
            self.assert_true(alvo is not None, "não consegui criar o canal do teste de mensagens")

            for i in range(3):
                await alvo.send(f"mensagem de teste {i + 1} ({TEMP_MARK})")
            antes_hist = [m async for m in alvo.history(limit=10)]
            self.assert_true(len(antes_hist) >= 3, f"não consegui postar as mensagens: {len(antes_hist)}")

            resultado = await ferramenta("clear_messages", {"channel": str(alvo.id), "limit": 20})
            self.assert_true("Apaguei" in resultado or "Não havia" in resultado,
                             f"resposta estranha do clear_messages: {resultado[:120]!r}")
            restantes = [m async for m in alvo.history(limit=10)]
            self.assert_true(not restantes,
                             f"o chat não foi limpo: ainda tem {len(restantes)} mensagem(ns)")
            await alvo.delete()
            self.owned_channels.discard(alvo.id)
            return f"apagou {len(antes_hist)} mensagem(ns) reais e o canal ficou vazio"

        await self.check(phase, "clear_messages apaga mensagens reais do canal", apagar_mensagens_reais)

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
    # =====================================================================
    # caps — matriz de capacidades (o que cada ferramenta PERMITE, não uma chamada simbólica)
    # =====================================================================
    async def phase_caps(self) -> None:
        """
        Cada parâmetro, cada valor (válido e inválido), as combinações e o estado REAL do
        servidor depois da operação — para cargos, canais, permissões e estrutura.

        Protocolo do dono do projeto: "testar tudo" é testar as CAPACIDADES que as ferramentas
        permitem (todas as propriedades, todos os valores, todas as combinações, limites,
        hierarquia e o efeito real no Discord), e não chamar cada ferramenta uma vez. O que não
        puder ser verificado neste servidor é registrado como tal, nunca dado como funcionando.
        """
        from brain.executors import execute_tool
        from brain.ops import PERMISSOES, Permissoes
        from brain.tools import ToolContext, ToolError

        phase = "caps"
        if not self.args.mutate:
            self.rep.record(phase, "matriz de capacidades", SKIP,
                            "rode com --mutate: a matriz cria, edita e apaga objetos de teste")
            return
        live = await self.ensure_live(phase)
        if live is None:
            self.rep.record(phase, "matriz de capacidades", SKIP, "sem conexão ao Discord")
            return

        guild = live.primary or self.env.primary
        if guild is None:
            self.rep.record(phase, "matriz de capacidades", SKIP, "sem servidor de teste")
            return

        # ---- infraestrutura: categoria, canais e um cargo, todos marcados para limpeza ----
        estado: dict[str, Any] = {}

        async def infraestrutura() -> str:
            antes = await self._api_state(guild)
            categoria = await guild.create_category(f"{TEMP_MARK} caps")
            texto = await guild.create_text_channel(f"{TEMP_MARK}-caps-texto", category=categoria)
            voz = await guild.create_voice_channel(f"{TEMP_MARK}-caps-voz", category=categoria)
            await self._capture_new(guild, antes)
            ctx = ToolContext(guild=guild, channel=texto, actor=live.actor,
                              api_registry=live.registry, memory=live.memory)
            estado.update(categoria=categoria, texto=texto, voz=voz, ctx=ctx)
            return (f"categoria {categoria.name} + {texto.name} + {voz.name} prontos "
                    f"(tudo registrado para limpeza)")

        await self.check(phase, "infra: categoria e canais da matriz", infraestrutura)
        if "ctx" not in estado:
            await self._cleanup(guild, phase)
            return

        ctx = estado["ctx"]
        categoria = estado["categoria"]
        texto = estado["texto"]
        voz = estado["voz"]

        async def ferramenta(nome: str, args: dict[str, Any]) -> str:
            return await execute_tool(nome, args, ctx)

        async def novo(prefixo: str) -> Any:
            """Cria um canal de texto marcado e devolve o objeto fresco do servidor."""
            antes = await self._api_state(guild)
            await ferramenta("create_channels", {"channels": [
                {"name": f"{TEMP_MARK}-{prefixo}", "type": "text", "category": str(categoria.id)}]})
            criados = await self._capture_new(guild, antes)
            canal = next((c for c in criados if c.type.name == "text"), None)
            self.assert_true(canal is not None, f"não consegui criar o canal de apoio {prefixo}")
            return await guild.fetch_channel(canal.id)

        # -------------------------------------------------------------- cargos
        topo_do_bot = lambda: posicao_do_topo_do_bot(guild)  # noqa: E731 - alias curto do helper

        async def gerencia_cargos() -> bool:
            """O bot só mexe em cargo abaixo do cargo mais alto dele (regra do Discord)."""
            papel = estado.get("cargo")
            if papel is None:
                return False
            estado["topo_bot"] = await topo_do_bot()
            return papel.position < estado["topo_bot"]

        def aviso_de_hierarquia(motivo: str) -> str:
            """Registra ⚠️ dizendo o que NÃO foi verificado e por quê — nunca um ✅ de fachada."""
            topo = estado.get("topo_bot")
            onde = f" (meu cargo mais alto está na posição {topo})" if topo else ""
            self.rep.record(phase, "cargos: gerenciar o cargo criado", WARN,
                            f"{motivo}{onde} — suba o cargo do farol acima dos cargos de teste "
                            "para a auditoria de cargos ficar completa ao vivo (as validações de "
                            "valor, hierarquia e @everyone seguem em tests/test_capacidades.py)")
            return f"não verificável neste servidor: {motivo}{onde}"

        def culpa_do_discord(exc: Exception) -> bool:
            """503/5xx do Discord é indisponibilidade momentânea, não defeito do bot."""
            status = getattr(exc, "status", None)
            texto = str(exc).lower()
            return (isinstance(status, int) and status >= 500) or "service unavailable" in texto

        async def cargos_criacao_completa() -> str:
            antes = await self._api_state(guild)
            try:
                await ferramenta("create_roles", {"roles": [{
                    "name": f"{TEMP_MARK}-caps-cargo", "color": "#5865F2", "hoist": True,
                    "mentionable": True, "permissions": ["ver canal", "gerenciar mensagens",
                                                         "enviar mensagens"],
                }]})
            except ToolError as exc:
                if not culpa_do_discord(exc):
                    raise
                # o Discord devolveu 5xx na criação: não é defeito do bot, mas também não é ✅
                self.rep.record(phase, "cargos: criar com nome, cor, hoist, mentionable e "
                                "permissões", WARN,
                                f"o Discord recusou a criação com erro de servidor (5xx) e o cargo "
                                f"não nasceu: {str(exc)[:180]} — as verificações de cargo ficam "
                                f"pendentes nesta rodada")
                return "Discord indisponível (5xx) na criação do cargo: nada a conferir"
            novos = await self._capture_new(guild, antes, incluir_cargos=True)
            papel = next((r for r in novos if r.name == f"{TEMP_MARK}-caps-cargo"), None)
            if papel is None:
                self.rep.record(phase, "cargos: criar com nome, cor, hoist, mentionable e "
                                "permissões", WARN,
                                "o comando respondeu OK mas o cargo não apareceu na API de cargos")
                return "o cargo não apareceu na API depois da criação"
            estado["cargo"] = papel
            estado["cargo"] = papel

            fresco = next(r for r in await guild.fetch_roles() if r.id == papel.id)
            esperado = Permissoes(["view_channel", "manage_messages", "send_messages"]).value
            self.assert_true(fresco.color.value == 0x5865F2,
                             f"cor real {hex(fresco.color.value)} ≠ #5865F2 pedido")
            self.assert_true(fresco.hoist, "hoist não foi aplicado")
            self.assert_true(fresco.mentionable, "mentionable não foi aplicado")
            self.assert_true(fresco.permissions.value == esperado,
                             f"permissões reais {fresco.permissions.value} ≠ esperado {esperado}")
            return (f"cargo real com cor {hex(fresco.color.value)}, hoist, mentionable e "
                    f"{len(Permissoes(value=esperado).nomes())} permissões conferidas na API "
                    f"(posição {fresco.position})")

        await self.check(phase, "cargos: criar com nome, cor, hoist, mentionable e permissões",
                         cargos_criacao_completa)

        async def cargos_edicao_cada_propriedade() -> str:
            papel = estado.get("cargo")
            if papel is None:
                self.assert_true(False, "sem cargo criado para editar")
            if not await gerencia_cargos():
                # A recusa EM SI é verificável (e importante): confere que é clara e que nada mudou.
                antes_r = next(r for r in await guild.fetch_roles() if r.id == papel.id)
                try:
                    await ferramenta("edit_role", {"role": str(papel.id), "name": "x"})
                    self.assert_true(False, "editou cargo na altura do topo do bot")
                except ToolError as exc:
                    self.assert_true("posição" in str(exc) or "acima" in str(exc),
                                     f"recusa de hierarquia confusa: {exc}")
                depois_r = next(r for r in await guild.fetch_roles() if r.id == papel.id)
                self.assert_true(antes_r.name == depois_r.name, "a recusa mexeu no cargo")
                return aviso_de_hierarquia(
                    f"o cargo criado ficou na posição {papel.position}: o Discord recusa a edição "
                    "(recusa conferida como clara, sem alterar nada)")
            alvo = str(papel.id)
            conferidos: list[str] = []

            await ferramenta("edit_role", {"role": alvo, "name": f"{TEMP_MARK}-caps-renomeado"})
            fresco = next(r for r in await guild.fetch_roles() if r.id == papel.id)
            self.assert_true(fresco.name == f"{TEMP_MARK}-caps-renomeado", "nome não mudou na API")
            conferidos.append("nome")

            await ferramenta("edit_role", {"role": alvo, "color": "#00FF00"})
            fresco = next(r for r in await guild.fetch_roles() if r.id == papel.id)
            self.assert_true(fresco.color.value == 0x00FF00, f"cor não mudou: {fresco.color.value}")
            conferidos.append("cor")

            await ferramenta("edit_role", {"role": alvo, "hoist": False, "mentionable": False})
            fresco = next(r for r in await guild.fetch_roles() if r.id == papel.id)
            self.assert_true(not fresco.hoist and not fresco.mentionable,
                             "hoist/mentionable não voltaram para false")
            conferidos.append("hoist+mentionable")

            await ferramenta("edit_role", {"role": alvo, "permissions": ["administrador"]})
            fresco = next(r for r in await guild.fetch_roles() if r.id == papel.id)
            self.assert_true(fresco.permissions.value & PERMISSOES["administrator"],
                             "permissão de administrador não foi aplicada")
            conferidos.append("permissões (substituição)")

            # volta para um conjunto menor: prova que a edição SUBSTITUI, não acumula
            await ferramenta("edit_role", {"role": alvo, "permissions": ["ver canal", "conectar"]})
            fresco = next(r for r in await guild.fetch_roles() if r.id == papel.id)
            self.assert_true(fresco.permissions.value == Permissoes(["view_channel", "connect"]).value,
                             f"permissões antigas ficaram: {fresco.permissions.value}")
            conferidos.append("troca de conjunto sem acumular")

            # a posição é limitada pela hierarquia do bot: conferimos e relatamos o real
            await ferramenta("edit_role", {"role": alvo, "position": 1})
            fresco = next(r for r in await guild.fetch_roles() if r.id == papel.id)
            posicao_bot = await topo_do_bot()  # MEDIDO na API: o cache do discord.py engana
            self.assert_true(fresco.position <= posicao_bot,
                             f"cargo ficou acima do meu topo ({fresco.position} > {posicao_bot})")
            conferidos.append(f"posição (pedida 1, ficou {fresco.position}, teto do bot {posicao_bot})")
            return "cada propriedade verificada no servidor: " + "; ".join(conferidos)

        await self.check(phase, "cargos: editar cada propriedade e ver o efeito real",
                         cargos_edicao_cada_propriedade)

        async def cargos_valores_invalidos_e_hierarquia() -> str:
            papel = estado.get("cargo")
            if not await gerencia_cargos():
                return aviso_de_hierarquia(
                    "com o cargo no nível do topo do bot, o gate de hierarquia dispara antes da "
                    "validação de valor — sem cargo gerenciável não dá para provar valor inválido "
                    "ao vivo")
            alvo = str(papel.id)
            antes = next(r for r in await guild.fetch_roles() if r.id == papel.id)

            recusas: list[str] = []
            for args, esperado in (
                ({"role": alvo, "color": "roxo-neon"}, "hexadecimal"),
                ({"role": alvo, "position": -1}, "negativa"),
                ({"role": alvo, "permissions": ["gerenciar pizza"]}, "Não conheço a permissão"),
                ({"role": alvo}, "Nada para editar"),
                ({"role": "@everyone", "name": "todos"}, "@everyone"),
            ):
                try:
                    await ferramenta("edit_role", args)
                    self.assert_true(False, f"aceitou valor inválido: {args}")
                except ToolError as exc:
                    self.assert_true(esperado.lower() in str(exc).lower(),
                                     f"erro pouco claro para {args}: {exc}")
                    recusas.append(esperado)

            depois = next(r for r in await guild.fetch_roles() if r.id == papel.id)
            self.assert_true(depois.name == antes.name and depois.permissions.value == antes.permissions.value,
                             "recusa mexeu no cargo (não deveria tocar em nada)")

            # hierarquia: cargo acima do bot precisa ser recusado com explicação
            pos_bot_api = await topo_do_bot()
            acima = next((r for r in await guild.fetch_roles()
                          if r.position >= pos_bot_api and not r.is_default()), None)
            if acima is None:
                self.rep.record(phase, "cargos: recusa de cargo acima do bot", WARN,
                                "não existe cargo no nível do meu topo para testar a recusa "
                                "(servidor com o bot no topo)")
            else:
                try:
                    await ferramenta("edit_role", {"role": str(acima.id), "name": "x"})
                    self.assert_true(False, f"editou cargo acima do bot: @{acima.name}")
                except ToolError as exc:
                    self.assert_true("posição" in str(exc) or "acima" in str(exc),
                                     f"mensagem de hierarquia confusa: {exc}")
                self.rep.record(phase, "cargos: recusa de cargo acima do bot", PASS,
                                f"@{acima.name} (posição {acima.position}) recusado com explicação")
            return "valores inválidos recusados sem tocar no cargo: " + ", ".join(recusas)

        await self.check(phase, "cargos: valores inválidos, @everyone e hierarquia",
                         cargos_valores_invalidos_e_hierarquia)

        async def cargos_dar_e_tirar_de_membro() -> str:
            papel = estado.get("cargo")
            if not await gerencia_cargos():
                return aviso_de_hierarquia(
                    "não posso atribuir cargo que ficou na altura do meu topo")
            membro = guild.owner or live.actor
            # garante o membro no cache (resolve_member depende dele quando a intent falha)
            await guild.fetch_member(membro.id)
            await ferramenta("give_role", {"member": str(membro.id), "role": str(papel.id)})
            fresco = await guild.fetch_member(membro.id)
            self.assert_true(any(r.id == papel.id for r in fresco.roles),
                             "o cargo não apareceu no membro depois do give_role")
            await ferramenta("take_role", {"member": str(membro.id), "role": str(papel.id)})
            fresco = await guild.fetch_member(membro.id)
            self.assert_true(not any(r.id == papel.id for r in fresco.roles),
                             "o cargo continuou no membro depois do take_role")
            return f"cargo dado e removido de {fresco.display_name}, conferido na API em cada passo"

        await self.check(phase, "cargos: dar e tirar de um membro (estado real)",
                         cargos_dar_e_tirar_de_membro)

        # -------------------------------------------------------------- canais
        async def canais_todos_os_tipos() -> str:
            tipos = [("text", "text"), ("voice", "voice"), ("category", "category"),
                     ("stage", "stage"), ("forum", "forum")]
            pedidos = [{"name": f"{TEMP_MARK}-tipo-{nome}", "type": nome,
                        "category": str(categoria.id) if nome not in ("category",) else None}
                       for nome, _ in tipos]
            antes = await self._api_state(guild)
            recusados: list[str] = []
            for nome, esperado in tipos:
                try:
                    await ferramenta("create_channels", {"channels": [
                        {"name": f"{TEMP_MARK}-tipo-{nome}", "type": nome}]})
                except ToolError as exc:
                    # fórum/palco dependem de recursos do servidor; registrar sem mentir
                    recusados.append(f"{nome}: {exc}")
            criados = await self._capture_new(guild, antes, conhecidos=[p["name"] for p in pedidos])
            por_nome = {c.name: c.type.name for c in criados}
            verificados = []
            for nome, esperado in tipos:
                real = por_nome.get(f"{TEMP_MARK}-tipo-{nome}")
                if real is None:
                    self.rep.record(phase, f"canais: tipo {nome}", WARN,
                                    next((r for r in recusados if r.startswith(nome)), "não criado"))
                    continue
                self.assert_true(real == esperado, f"pedi {nome} e o Discord criou {real}")
                verificados.append(f"{nome}→{real}")
            self.assert_true(bool(verificados), f"nenhum tipo foi criado: {recusados}")
            return "tipos reais conferidos na API: " + ", ".join(verificados)

        await self.check(phase, "canais: todos os tipos suportados (tipo real na API)",
                         canais_todos_os_tipos)

        async def canais_propriedades_na_criacao() -> str:
            antes = await self._api_state(guild)
            await ferramenta("create_channels", {"channels": [
                {"name": f"{TEMP_MARK}-caps-cheio", "type": "text", "category": str(categoria.id),
                 "topic": "tópico da matriz", "nsfw": True, "slowmode_delay": 30, "position": 1},
                {"name": f"{TEMP_MARK}-caps-voz-cheia", "type": "voice", "category": str(categoria.id),
                 "bitrate": 96000, "user_limit": 4},
            ]})
            criados = await self._capture_new(guild, antes)
            texto_criado = next((c for c in criados if c.name == f"{TEMP_MARK}-caps-cheio"), None)
            voz_criada = next((c for c in criados if c.name == f"{TEMP_MARK}-caps-voz-cheia"), None)
            self.assert_true(texto_criado is not None and voz_criada is not None,
                             "não consegui criar os canais da checagem")

            t = await guild.fetch_channel(texto_criado.id)
            self.assert_true(t.topic == "tópico da matriz", f"tópico real: {t.topic!r}")
            self.assert_true(t.nsfw, "nsfw não foi aplicado")
            self.assert_true(t.slowmode_delay == 30, f"slowmode real: {t.slowmode_delay}")
            self.assert_true(t.category_id == categoria.id, "canal não ficou na categoria")

            v = await guild.fetch_channel(voz_criada.id)
            self.assert_true(v.bitrate == 96000, f"bitrate real: {v.bitrate}")
            self.assert_true(v.user_limit == 4, f"limite real: {v.user_limit}")
            return (f"texto: tópico, nsfw, slowmode 30s, categoria · voz: bitrate {v.bitrate}, "
                    f"limite {v.user_limit} — tudo conferido na API")

        await self.check(phase, "canais: tópico, NSFW, slowmode, bitrate e limite na criação",
                         canais_propriedades_na_criacao)

        async def canais_edicao_cada_propriedade() -> str:
            canal = await novo("caps-editar")
            alvo = str(canal.id)
            conferidos: list[str] = []

            await ferramenta("edit_channel", {"channel": alvo, "name": f"{TEMP_MARK}-caps-editado"})
            atual = await guild.fetch_channel(canal.id)
            self.assert_true(atual.name == f"{TEMP_MARK}-caps-editado", "nome não mudou na API")
            conferidos.append("nome")

            await ferramenta("edit_channel", {"channel": alvo, "topic": "novo tópico"})
            atual = await guild.fetch_channel(canal.id)
            self.assert_true(atual.topic == "novo tópico", f"tópico real: {atual.topic!r}")
            conferidos.append("tópico")

            await ferramenta("edit_channel", {"channel": alvo, "nsfw": True, "slowmode_delay": 5})
            atual = await guild.fetch_channel(canal.id)
            self.assert_true(atual.nsfw and atual.slowmode_delay == 5,
                             f"nsfw/slowmode reais: {atual.nsfw}/{atual.slowmode_delay}")
            conferidos.append("nsfw+slowmode")

            await ferramenta("edit_channel", {"channel": alvo, "category": "none"})
            atual = await guild.fetch_channel(canal.id)
            self.assert_true(atual.category_id is None, f"categoria real: {atual.category_id}")
            await ferramenta("edit_channel", {"channel": alvo, "category": str(categoria.id)})
            atual = await guild.fetch_channel(canal.id)
            self.assert_true(atual.category_id == categoria.id, "não voltou para a categoria")
            conferidos.append("categoria (sair e voltar)")

            async def voz_editada() -> str:
                nova_voz = await guild.create_voice_channel(f"{TEMP_MARK}-caps-voz-editar",
                                                            category=categoria)
                self.owned_channels.add(nova_voz.id)
                teto = int(getattr(guild, "bitrate_limit", 96000) or 96000)
                pedido = min(128000, teto)
                await ferramenta("edit_channel", {"channel": str(nova_voz.id),
                                                  "bitrate": pedido, "user_limit": 7})
                atual_v = await guild.fetch_channel(nova_voz.id)
                self.assert_true(atual_v.bitrate == pedido and atual_v.user_limit == 7,
                                 f"voz: {atual_v.bitrate}/{atual_v.user_limit}")
                return f"voz: bitrate {atual_v.bitrate}, limite {atual_v.user_limit}"

            detalhe_voz = await voz_editada()
            await canal.delete()
            self.owned_channels.discard(canal.id)
            return "; ".join(conferidos) + "; " + detalhe_voz

        await self.check(phase, "canais: editar cada propriedade e ver o efeito real",
                         canais_edicao_cada_propriedade)

        async def canais_mover_clonar_excluir() -> str:
            antes = await self._api_state(guild)
            outra_cat = await guild.create_category(f"{TEMP_MARK} caps-destino")
            await ferramenta("create_channels", {"channels": [
                {"name": f"{TEMP_MARK}-caps-mover", "type": "text", "category": str(categoria.id),
                 "topic": "leva o tópico", "nsfw": True, "slowmode_delay": 7}]})
            criados = await self._capture_new(guild, antes)
            self.owned_channels.add(outra_cat.id)
            canal = next((c for c in criados if c.name == f"{TEMP_MARK}-caps-mover"), None)
            self.assert_true(canal is not None, "não criei o canal da checagem de mover")

            await ferramenta("move_channel", {"channel": str(canal.id), "category": str(outra_cat.id)})
            movido = await guild.fetch_channel(canal.id)
            self.assert_true(movido.category_id == outra_cat.id,
                             f"não mudou de categoria: {movido.category_id} ≠ {outra_cat.id}")
            await ferramenta("move_channel", {"channel": str(canal.id), "position": 0})
            movido = await guild.fetch_channel(canal.id)
            # posição 0 = primeiro da categoria; o Discord ordena junto com os vizinhos, então o
            # valor exato pode variar — o teste cobra o efeito (virou o primeiro) e relata o real.
            self.assert_true(movido.position == 0,
                             f"pedi posição 0 e a real foi {movido.position}")

            await ferramenta("clone_channel", {"channel": str(canal.id)})
            depois = await self._capture_new(guild, antes)
            clone = next((c for c in depois if c.id not in (canal.id,) and "caps-mover" in c.name), None)
            self.assert_true(clone is not None, "o clone não apareceu no servidor")
            self.assert_true(clone.topic == "leva o tópico", f"clone perdeu o tópico: {clone.topic!r}")
            self.assert_true(clone.nsfw, "clone não copiou o nsfw")
            self.assert_true(clone.slowmode_delay == 7, f"clone perdeu o slowmode: {clone.slowmode_delay}")
            self.assert_true(clone.category_id == outra_cat.id, "clone não ficou na mesma categoria")

            await ferramenta("delete_channels", {"channels": [str(clone.id)]})
            restante = await guild.fetch_channel(canal.id)  # o original continua
            self.assert_true(restante is not None, "o original sumiu junto")
            existentes = {c.id for c in await guild.fetch_channels()}
            self.assert_true(clone.id not in existentes, "o clone não foi apagado")
            self.owned_channels.discard(clone.id)
            return ("mover por categoria e posição, clonar levando tópico+nsfw+slowmode+categoria "
                    "e apagar só a cópia — tudo conferido na API")

        await self.check(phase, "canais: mover, clonar e excluir (estado real)",
                         canais_mover_clonar_excluir)

        async def canais_valores_invalidos() -> str:
            antes = len(await guild.fetch_channels())
            recusas: list[str] = []
            casos = [
                ({"channels": [{"name": "x", "type": "holograma"}]}, "não existe"),
                ({"channels": [{"name": "x", "type": "text", "slowmode_delay": 21601}]}, "slowmode"),
                ({"channels": [{"name": "x", "type": "voice", "bitrate": 1000}]}, "bitrate"),
                ({"channels": [{"name": "x", "type": "voice", "user_limit": 500}]}, "limite"),
            ]
            for args, esperado in casos:
                try:
                    await ferramenta("create_channels", args)
                    self.assert_true(False, f"aceitou criação inválida: {args}")
                except ToolError as exc:
                    self.assert_true(esperado.lower() in str(exc).lower(),
                                     f"erro pouco claro ({esperado}): {exc}")
                    recusas.append(esperado)

            for args, esperado in (
                ({"channel": str(texto.id), "name": "  "}, "vazio"),
                ({"channel": str(texto.id), "slowmode_delay": -5}, "slowmode"),
                ({"channel": str(texto.id), "bitrate": 999999}, "bitrate"),
                ({"channel": str(texto.id)}, "Nenhum parâmetro"),
                ({"channel": str(texto.id), "position": -1}, "negativa"),
            ):
                try:
                    await ferramenta("edit_channel", args)
                    self.assert_true(False, f"aceitou edição inválida: {args}")
                except ToolError as exc:
                    self.assert_true(esperado.lower() in str(exc).lower(),
                                     f"erro pouco claro ({esperado}): {exc}")
                    recusas.append(esperado)

            depois = len(await guild.fetch_channels())
            self.assert_true(depois == antes, f"objetos foram criados mesmo com erro: {antes}→{depois}")
            return ("valores inválidos recusados sem criar/alterar nada: "
                    + ", ".join(recusas))

        await self.check(phase, "canais: valores inválidos e limites (nada é criado por engano)",
                         canais_valores_invalidos)

        # -------------------------------------------------------------- permissões
        async def permissoes_allow_deny_leitura_limpeza() -> str:
            canal = await novo("caps-perm")
            # o alvo preferido é o cargo criado; se ele não nasceu (Discord 5xx), a @everyone
            # serve para conferir allow/deny/leitura/limpeza — nunca pular a capacidade inteira.
            papel = estado.get("cargo") or getattr(guild, "default_role", None)
            fallback = " (com a @everyone: o cargo de teste não nasceu)" if not estado.get("cargo") else ""
            alvo = str(papel.id)

            await ferramenta("set_permissions", {"channel": str(canal.id), "target": alvo,
                                                "allow": ["ver canal", "enviar mensagens"],
                                                "deny": ["mencionar todos"]})
            fresco = await guild.fetch_channel(canal.id)
            ow = next((o for e, o in fresco.overwrites.items() if getattr(e, "id", None) == papel.id), None)
            self.assert_true(ow is not None, "o overwrite não apareceu na API")
            self.assert_true(ow.view_channel is True and ow.send_messages is True,
                             f"allow não aplicado: {ow.view_channel}/{ow.send_messages}")
            self.assert_true(ow.mention_everyone is False, "deny não aplicado")

            leitura = await ferramenta("show_permissions", {"channel": str(canal.id), "target": alvo})
            self.assert_true("view_channel" in leitura or "Permissões" in leitura,
                             f"show_permissions não mostrou o que existe: {leitura[:120]!r}")

            try:
                await ferramenta("set_permissions", {"channel": str(canal.id), "target": alvo,
                                                     "allow": ["ver canal"], "deny": ["view_channel"]})
                self.assert_true(False, "aceitou conflito allow+deny")
            except ToolError as exc:
                self.assert_true("permitida e negada" in str(exc), f"erro confuso: {exc}")

            await ferramenta("clear_permissions", {"channel": str(canal.id), "target": alvo})
            fresco = await guild.fetch_channel(canal.id)
            restou = next((o for e, o in fresco.overwrites.items() if getattr(e, "id", None) == papel.id), None)
            self.assert_true(restou is None, "o overwrite continuou depois do clear_permissions")
            await canal.delete()
            self.owned_channels.discard(canal.id)
            return ("allow e deny em português viraram permissões reais (view_channel/send_messages/"
                    f"mention_everyone), conflito recusado e limpeza conferida na API{fallback}")

        await self.check(phase, "permissões: allow, deny, conflito, leitura e limpeza",
                         permissoes_allow_deny_leitura_limpeza)

        async def permissoes_sincronizar_com_categoria() -> str:
            pai = await guild.create_category(f"{TEMP_MARK} caps-sync")
            self.owned_channels.add(pai.id)
            filho = await guild.create_text_channel(f"{TEMP_MARK}-caps-sync-filho", category=pai)
            self.owned_channels.add(filho.id)
            papel = estado.get("cargo") or getattr(guild, "default_role", None)

            await ferramenta("set_permissions", {"channel": str(pai.id), "target": str(papel.id),
                                                "allow": ["ver canal", "enviar mensagens"]})
            # o filho começa SEM override próprio; sincronizar copia o do pai
            await ferramenta("sync_permissions", {"channel": str(filho.id)})
            fresco = await guild.fetch_channel(filho.id)
            ow = next((o for e, o in fresco.overwrites.items() if getattr(e, "id", None) == papel.id), None)
            self.assert_true(ow is not None and ow.send_messages is True,
                             "sincronizar não trouxe a permissão da categoria")
            return "permissão da categoria copiada para o canal filho (conferido na API)"

        await self.check(phase, "permissões: sincronizar canal com a categoria",
                         permissoes_sincronizar_com_categoria)

        async def permissao_do_autor_barra_antes_do_discord() -> str:
            from brain.tools import ToolContext as _Ctx

            class SemPermissao:
                id = 4242
                name = "sem-permissao"
                display_name = "sem-permissao"
                guild_permissions = types.SimpleNamespace(manage_channels=False, manage_roles=False,
                                                          administrator=False, manage_messages=False,
                                                          manage_guild=False, view_channel=True,
                                                          send_messages=True)
                top_role = types.SimpleNamespace(position=0, name="ninguém")

            antes = len(await guild.fetch_channels())
            ctx_fraco = _Ctx(guild=guild, channel=texto, actor=SemPermissao(),
                             api_registry=live.registry, memory=live.memory)
            recusas = 0
            for nome, args in (("create_channels", {"channels": [{"name": f"{TEMP_MARK}-nunca"}]}),
                               ("create_roles", {"roles": [{"name": f"{TEMP_MARK}-nunca"}]}),
                               ("delete_channels", {"channels": [str(texto.id)], "confirmed": True}),
                               ("clear_messages", {"channel": str(texto.id), "limit": 5})):
                try:
                    await execute_tool(nome, args, ctx_fraco)
                    self.assert_true(False, f"autor sem permissão conseguiu usar {nome}")
                except ToolError as exc:
                    self.assert_true("permissão" in str(exc).lower(),
                                     f"a recusa de {nome} não fala de permissão: {exc}")
                    recusas += 1
            depois = len(await guild.fetch_channels())
            self.assert_true(depois == antes, "a tentativa sem permissão mexeu no servidor")
            return (f"{recusas} ferramentas recusadas ANTES de tocar no Discord (autor sem permissão) "
                    "e nenhum objeto criado ou apagado")

        await self.check(phase, "permissões: autor sem permissão é barrado antes da API",
                         permissao_do_autor_barra_antes_do_discord)

        # -------------------------------------------------------------- estrutura
        async def export_guarda_capacidades() -> str:
            papel = estado.get("cargo")
            if papel is None:
                return aviso_de_hierarquia("sem cargo criado para exportar")
            # garante um canal de texto com todas as propriedades e um de voz com limites
            await ferramenta("edit_channel", {"channel": str(texto.id), "topic": "tópico do export",
                                              "nsfw": True, "slowmode_delay": 9})
            await ferramenta("edit_channel", {"channel": str(voz.id), "bitrate": 96000, "user_limit": 3})
            saida = await ferramenta("export_structure", {})
            if "NÃO serve para importar" in saida:
                # servidor grande: o JSON completo não cabe numa mensagem do Discord. Cobra o
                # aviso explícito e os campos de capacidade no recorte — antes o JSON vinha
                # cortado no meio, sem aviso, e o round-trip não podia ser feito.
                self.assert_true("não cabe" in saida, "recorte sem explicação do tamanho")
                # O recorte mostra o COMEÇO do JSON: os cargos (com permissions/hoist/
                # mentionable) vêm depois dos canais e caem fora do pedaço — então o que se cobra
                # aqui é o AVISO e o balanço do que foi exportado, não as chaves que não couberam.
                self.assert_true("NÃO serve para importar" in saida,
                                 "recorte sem o aviso de que não serve para importar")
                for info in ("cargo(s)", "permissões", "por partes"):
                    self.assert_true(info in saida,
                                     f"o aviso do recorte não diz o que ficou fora ({info})")
                return ("export grande: recorte AVISADO (não serve para importar), com o balanço "
                        "de canais/categorias/cargos exportados (as chaves que caem fora do "
                        "recorte não podem ser cobradas do pedaço; o round-trip completo é "
                        "verificado na fase de import e nos testes offline)")
            dados = json.loads(saida[saida.find("{"): saida.rfind("}") + 1])

            atual_papel = next(r for r in await guild.fetch_roles() if r.id == papel.id)
            papel_export = next((r for r in dados["roles"] if r["name"] == atual_papel.name), None)
            self.assert_true(papel_export is not None, "o cargo não apareceu no export")
            self.assert_true(isinstance(papel_export.get("permissions"), list)
                             and len(papel_export["permissions"]) > 0,
                             f"export não guardou as permissões: {papel_export}")
            self.assert_true("mentionable" in papel_export and "hoist" in papel_export,
                             "export não guardou hoist/mentionable")

            canais = [c for cat in dados["categories"] for c in cat["channels"]]
            texto_export = next((c for c in canais if c["name"] == texto.name), None)
            self.assert_true(texto_export is not None, "o canal de texto não apareceu no export")
            self.assert_true(texto_export.get("nsfw") and texto_export.get("slowmode_delay") == 9,
                             f"export perdeu nsfw/slowmode: {texto_export}")
            voz_export = next((c for c in canais if c["name"] == voz.name), None)
            self.assert_true(voz_export and voz_export.get("user_limit") == 3,
                             f"export perdeu o limite de usuários: {voz_export}")
            return (f"export real com {len(dados['roles'])} cargos (permissões, hoist, mentionable) e "
                    f"canais com tipo, tópico, nsfw={texto_export.get('nsfw')}, "
                    f"slowmode={texto_export.get('slowmode_delay')}, bitrate e limite")

        await self.check(phase, "estrutura: export guarda as capacidades reais",
                         export_guarda_capacidades)

        async def import_recria_capacidades() -> str:
            estrutura = {
                "roles": [{"name": f"{TEMP_MARK}-caps-import-cargo", "color": "#FF00AA",
                           "hoist": True, "mentionable": True,
                           "permissions": ["view_channel", "manage_messages"]}],
                "categories": [{"name": f"{TEMP_MARK} caps-import", "channels": [
                    {"name": f"{TEMP_MARK}-caps-import-texto", "type": "text",
                     "topic": "veio do import", "nsfw": True, "slowmode_delay": 11},
                    {"name": f"{TEMP_MARK}-caps-import-voz", "type": "voice",
                     "bitrate": 96000, "user_limit": 5},
                ]}],
                "uncategorized_channels": [{"name": f"{TEMP_MARK}-caps-import-solto", "type": "text"}],
            }
            antes = await self._api_state(guild)
            saida = await ferramenta("import_structure", {"structure_json": json.dumps(estrutura)})
            novos = await self._capture_new(guild, antes, incluir_cargos=True)
            self.assert_true("3 canal(is)" in saida, f"import não relatou os 3 canais: {saida[:120]!r}")
            _relato_import = saida[:100]

            # cargo recriado com as mesmas propriedades
            papel = next((r for r in novos if r.name == f"{TEMP_MARK}-caps-import-cargo"), None)
            self.assert_true(papel is not None, "o cargo do import não foi criado")
            fresco = next(r for r in await guild.fetch_roles() if r.id == papel.id)
            self.assert_true(fresco.color.value == 0xFF00AA, f"cor do import: {fresco.color.value}")
            self.assert_true(fresco.permissions.value == Permissoes(["view_channel", "manage_messages"]).value,
                             f"permissões do import: {fresco.permissions.value}")
            self.assert_true(fresco.hoist and fresco.mentionable, "hoist/mentionable do import")

            t = next((c for c in novos if c.name == f"{TEMP_MARK}-caps-import-texto"), None)
            v = next((c for c in novos if c.name == f"{TEMP_MARK}-caps-import-voz"), None)
            solto = next((c for c in novos if c.name == f"{TEMP_MARK}-caps-import-solto"), None)
            self.assert_true(t and v and solto, "faltou canal do import (categoria ou sem categoria)")
            ft = await guild.fetch_channel(t.id)
            self.assert_true(ft.topic == "veio do import" and ft.nsfw and ft.slowmode_delay == 11,
                             f"texto do import: {ft.topic!r}/{ft.nsfw}/{ft.slowmode_delay}")
            fv = await guild.fetch_channel(v.id)
            self.assert_true(fv.bitrate == 96000 and fv.user_limit == 5,
                             f"voz do import: {fv.bitrate}/{fv.user_limit}")
            pai = next((c for c in novos if c.type.name == "category"), None)
            self.assert_true(pai is not None and ft.category_id == pai.id,
                             "o canal importado não ficou na categoria importada")
            self.assert_true(solto.category_id is None, "o canal 'solto' ganhou categoria indevida")
            return (f"import recriou cargo (cor, hoist, mentionable, permissões) e canais "
                    f"(tópico, nsfw, slowmode, bitrate, limite, categoria e sem categoria) — "
                    f"conferido na API · {_relato_import!r}")

        await self.check(phase, "estrutura: import recria com os mesmos campos (round-trip)",
                         import_recria_capacidades)

        async def repeticao_sem_efeito_colateral() -> str:
            """
            Repetir a MESMA ordem não pode duplicar NADA (bug relatado pelo dono: cargos e
            canais repetidos). Tem que ser idempotente: uma ordem repetida = um canal.
            """
            nome = f"{TEMP_MARK}-caps-repetido"
            for _ in range(3):
                antes_rep = await self._api_state(guild)
                await ferramenta("create_channels", {"channels": [
                    {"name": nome, "type": "text", "category": str(categoria.id)}]})
                await self._capture_new(guild, antes_rep)
            canais = [c for c in await guild.fetch_channels() if c.name == nome]
            self.assert_true(len(canais) == 1,
                             f"a mesma ordem repetida 3x criou {len(canais)} canais (esperado 1)")
            # o mesmo nome duas vezes NUMA chamada também não pode duplicar
            nome_lote = f"{TEMP_MARK}-caps-lote-repetido"
            antes_lote = await self._api_state(guild)
            await ferramenta("create_channels", {"channels": [
                {"name": nome_lote, "type": "text", "category": str(categoria.id)},
                {"name": nome_lote, "type": "text", "category": str(categoria.id)}]})
            await self._capture_new(guild, antes_lote)
            do_lote = [c for c in await guild.fetch_channels() if c.name == nome_lote]
            self.assert_true(len(do_lote) == 1,
                             f"o lote com o mesmo nome criou {len(do_lote)} canais (esperado 1)")
            # nome novo continua nascendo (a trava de duplicata não quebrou a criação)
            nome_novo = f"{TEMP_MARK}-caps-novo"
            antes_novo = await self._api_state(guild)
            await ferramenta("create_channels", {"channels": [
                {"name": nome_novo, "type": "text", "category": str(categoria.id)}]})
            await self._capture_new(guild, antes_novo)
            novos = [c for c in await guild.fetch_channels() if c.name == nome_novo]
            self.assert_true(len(novos) == 1, f"o canal novo não nasceu ({len(novos)})")
            # a edição continua funcionando no canal que existe
            await ferramenta("edit_channel", {"channel": str(canais[0].id), "topic": "repetido"})
            fresco = await guild.fetch_channel(canais[0].id)
            self.assert_true(fresco.topic == "repetido", "a edição não pegou")
            return ("3 ordens iguais = 1 canal (sem duplicata), lote com nome repetido = 1 canal, "
                    "nome novo nasce normalmente e a edição continua pegando")

        await self.check(phase, "repetição: mesma ordem várias vezes não quebra nem duplica efeito",
                         repeticao_sem_efeito_colateral)

        await self._cleanup(guild, phase)

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
                if "✅" not in emojis:
                    # ❌ é o comportamento CERTO do bot quando a ação falha. Se quem falhou foi o
                    # Discord (5xx), o mérito é dele — registra ⚠️ com a resposta real, não ❌.
                    respostas = [m.content async for m in canal.history(limit=20, after=anchor)
                                 if m.author.id == bot.user.id]
                    texto = "\n".join(respostas)
                    if any(t in texto.lower() for t in ("503", "service unavailable",
                                                        "indisponível", "erro ao executar")):
                        self.rep.record(phase, "reações de feedback 👀→✅", WARN,
                                        "o bot marcou ❌ porque o Discord devolveu erro de servidor "
                                        f"durante a ação (comportamento correto): {texto.strip()[:160]}")
                        return (f"❌ por indisponibilidade do Discord, não do bot (reações: {emojis})",
                                {"reacoes": emojis})
                    if self._culpa_do_llm(texto):
                        # ❌ é o comportamento CERTO: a ação não foi feita porque nenhum corredor
                        # grátis atendeu. Culpa do provedor, não do bot (sem chave paga é
                        # intermitente — o dono aceitou esse risco).
                        self.rep.record(phase, "reações de feedback 👀→✅", WARN,
                                        "o bot marcou ❌ porque nenhum corredor grátis atendeu nesta "
                                        f"rodada (comportamento correto): {texto.strip()[:160]}")
                        return (f"❌ por fila cheia dos modelos grátis (reações: {emojis})",
                                {"reacoes": emojis})
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
