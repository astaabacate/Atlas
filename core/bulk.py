"""
Execução em lote com semáforo de concorrência, atraso e isolamento de falhas.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


@dataclass
class BulkResult:
    total: int
    succeeded: list[Any] = field(default_factory=list)
    failed: list[tuple[Any, Exception]] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return len(self.succeeded)

    @property
    def failure_count(self) -> int:
        return len(self.failed)

    def summary(self) -> str:
        if self.failure_count == 0:
            return f"✅ {self.success_count}/{self.total} concluídos com sucesso."

        # Agrupar falhas pelo tipo de erro / mensagem curta
        counts: Counter[str] = Counter()
        for _, exc in self.failed:
            name = type(exc).__name__
            msg = str(exc)
            label = f"{name}: {msg}" if msg else name
            # Se for muito longo, encurtar
            if len(label) > 35:
                label = label[:32] + "..."
            counts[label] += 1

        details = ", ".join(f"{lbl}×{cnt}" for lbl, cnt in counts.items())
        return f"✅ {self.success_count}/{self.total} concluídos. Falhas: {self.failure_count} ({details})"


async def run_bulk(
    items: Iterable[T],
    op: Callable[[T], Awaitable[R]],
    concurrency: int = 3,
    delay: float = 0.0,
    dedupe: bool = False,
) -> BulkResult:
    """
    Executa `op(item)` concorrentemente para todos os itens em `items`.
    A falha de um item NÃO aborta os demais.
    """
    raw_list = list(items)
    if dedupe:
        seen = set()
        unique_items = []
        for x in raw_list:
            if x not in seen:
                seen.add(x)
                unique_items.append(x)
        items_list = unique_items
    else:
        items_list = raw_list

    total = len(items_list)
    if total == 0:
        return BulkResult(total=0)

    semaphore = asyncio.Semaphore(max(1, concurrency))
    result = BulkResult(total=total)

    async def _worker(item: T) -> None:
        async with semaphore:
            try:
                out = await op(item)
                result.succeeded.append(out)
            except Exception as exc:
                result.failed.append((item, exc))
            if delay > 0:
                await asyncio.sleep(delay)

    tasks = [_worker(item) for item in items_list]
    await asyncio.gather(*tasks, return_exceptions=True)
    return result
