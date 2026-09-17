"""
Memória de conversação por canal com limite de histórico (FIFO).
NÃO importa discord (duck-typing estrito).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChannelMemory:
    max_turns: int = 10
    _storage: dict[int, list[dict[str, Any]]] = field(default_factory=lambda: defaultdict(list))

    def get_history(self, channel_id: int) -> list[dict[str, Any]]:
        return list(self._storage[channel_id])

    def add_message(self, channel_id: int, message: dict[str, Any]) -> None:
        hist = self._storage[channel_id]
        hist.append(message)
        # Manter apenas as últimas max_turns * 3 mensagens (turnos de conversa)
        limit = max(4, self.max_turns * 3)
        if len(hist) > limit:
            self._storage[channel_id] = hist[-limit:]

    def clear(self, channel_id: int) -> None:
        if channel_id in self._storage:
            self._storage[channel_id] = []
