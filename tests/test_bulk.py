"""
Testes de execução em lote (bulk).
Garante isolamento de falhas, semáforo de concorrência e deduplicação.
"""

from __future__ import annotations

import asyncio
import unittest

from core.bulk import run_bulk


class TestBulk(unittest.TestCase):
    def test_all_succeed(self) -> None:
        async def double(x: int) -> int:
            await asyncio.sleep(0.01)
            return x * 2

        items = [1, 2, 3, 4]
        res = asyncio.run(run_bulk(items, double, concurrency=2))

        self.assertEqual(res.total, 4)
        self.assertEqual(res.success_count, 4)
        self.assertEqual(res.failure_count, 0)
        self.assertEqual(set(res.succeeded), {2, 4, 6, 8})
        self.assertIn("✅ 4/4 concluídos com sucesso", res.summary())

    def test_isolated_failure(self) -> None:
        async def fail_on_two(x: int) -> int:
            if x == 2:
                raise PermissionError("Forbidden")
            return x * 10

        items = [1, 2, 3]
        res = asyncio.run(run_bulk(items, fail_on_two, concurrency=2))

        self.assertEqual(res.total, 3)
        self.assertEqual(res.success_count, 2)
        self.assertEqual(res.failure_count, 1)
        self.assertEqual(set(res.succeeded), {10, 30})
        self.assertEqual(res.failed[0][0], 2)
        self.assertIsInstance(res.failed[0][1], PermissionError)

        summary = res.summary()
        self.assertIn("✅ 2/3 concluídos", summary)
        self.assertIn("Falhas: 1", summary)
        self.assertIn("Forbidden", summary)

    def test_concurrency_ceiling(self) -> None:
        current_active = 0
        max_active = 0

        async def worker(x: int) -> int:
            nonlocal current_active, max_active
            current_active += 1
            if current_active > max_active:
                max_active = current_active
            await asyncio.sleep(0.02)
            current_active -= 1
            return x

        items = list(range(10))
        asyncio.run(run_bulk(items, worker, concurrency=3))
        self.assertLessEqual(max_active, 3, "A concorrência não pode ultrapassar o teto estipulado")

    def test_deduplication(self) -> None:
        async def echo(x: str) -> str:
            return x

        items = ["a", "b", "a", "c", "b"]
        res = asyncio.run(run_bulk(items, echo, dedupe=True))
        self.assertEqual(res.total, 3)
        self.assertEqual(res.succeeded, ["a", "b", "c"])


if __name__ == "__main__":
    unittest.main()
