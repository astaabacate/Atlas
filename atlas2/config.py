"""Configuração — tudo por variável de ambiente (nenhum segredo no código)."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(valor: str, padrao: bool = False) -> bool:
    if valor is None or valor == "":
        return padrao
    return valor.strip().lower() in {"1", "true", "sim", "yes", "on"}


def _lista(valor: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in (valor or "").replace(";", ",").split(",") if p.strip())


@dataclass(frozen=True)
class Config:
    token: str
    base_url: str
    chave: str
    modelo: str
    modelo_rapido: str
    canais_permitidos: frozenset[int]
    timeout_llm: float
    avisar_canal: bool

    @classmethod
    def do_ambiente(cls, env: dict[str, str] | None = None) -> "Config":
        src = env if env is not None else os.environ
        base = (src.get("OMNIROUTE_URL") or src.get("LLM_BASE_URL") or "").strip().rstrip("/")
        return cls(
            token=(src.get("DISCORD_TOKEN") or "").strip(),
            base_url=base,
            chave=(src.get("OMNIROUTE_KEY") or src.get("LLM_API_KEY") or "").strip(),
            modelo=(src.get("OMNIROUTE_MODEL") or "auto").strip(),
            modelo_rapido=(src.get("OMNIROUTE_MODEL_RAPIDO") or "").strip(),
            canais_permitidos=frozenset(
                int(c) for c in _lista(src.get("CANAIS_PERMITIDOS", "")) if c.isdigit()
            ),
            timeout_llm=float(src.get("LLM_TIMEOUT", "20") or 20),
            avisar_canal=_bool(src.get("AVISAR_NO_CANAL", "true"), True),
        )

    @property
    def tem_llm(self) -> bool:
        return bool(self.base_url and self.chave)

    def canal_permitido(self, canal_id: int) -> bool:
        return not self.canais_permitidos or canal_id in self.canais_permitidos
