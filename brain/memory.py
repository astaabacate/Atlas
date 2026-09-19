"""
Memória de conversação por CANAL, isolada por SERVIDOR.

Chave de cada conversa: `servidor:canal` (ex.: "1234:5678"). O mesmo bot atende vários
servidores ao mesmo tempo — o histórico de um NUNCA pode aparecer no outro.

A memória é limitada de propósito: um bot que fica anos no ar atendendo centenas de
servidores não pode acumular uma lista de conversas para sempre.

NÃO importa discord (duck-typing estrito).
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any


def memory_key(guild_id: Any, channel_id: Any) -> str:
    """
    Chave da conversa: sempre `servidor:canal`.

    O ID do canal já é único no Discord, mas amarrar o servidor deixa o isolamento
    explícito (e protege testes/duplos que reutilizam IDs entre servidores).
    """
    return f"{guild_id if guild_id is not None else '?'}:{channel_id if channel_id is not None else '?'}"


@dataclass
class ChannelMemory:
    max_turns: int = 10
    # Quantas conversas ficam na memória ao mesmo tempo (LRU: a mais antiga sai primeiro).
    max_conversations: int = 400
    _storage: OrderedDict[Any, list[dict[str, Any]]] = field(default_factory=OrderedDict)

    # ------------------------------------------------------------------ leitura
    def get_history(self, key: Any) -> list[dict[str, Any]]:
        hist = self._storage.get(key)
        if hist is None:
            return []
        self._storage.move_to_end(key)
        return list(hist)

    def add_message(self, key: Any, message: dict[str, Any]) -> None:
        hist = self._storage.get(key)
        if hist is None:
            hist = []
            self._storage[key] = hist
        hist.append(message)

        # Manter apenas as últimas max_turns * 3 mensagens (turnos de conversa)
        limit = max(4, self.max_turns * 3)
        if len(hist) > limit:
            self._storage[key] = hist[-limit:]

        self._storage.move_to_end(key)
        self._evict()

    def clear(self, key: Any) -> None:
        if key in self._storage:
            self._storage[key] = []

    # ------------------------------------------------------------------ manutenção
    def _evict(self) -> None:
        """Descarta as conversas mais antigas quando passa do limite."""
        limite = max(1, int(self.max_conversations))
        while len(self._storage) > limite:
            self._storage.popitem(last=False)

    def __len__(self) -> int:
        return len(self._storage)

    def conversations(self) -> list[Any]:
        """Chaves ativas (mais recentes primeiro) — útil em diagnóstico."""
        return list(reversed(self._storage.keys()))
