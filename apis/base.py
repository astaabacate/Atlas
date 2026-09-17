"""
Infraestrutura base para APIs externas: Rate Limiting, Circuit Breaker e ApiRegistry.
"""

from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from typing import Any, Awaitable, Callable

logger = logging.getLogger("farol.apis.base")


class CircuitState(Enum):
    CLOSED = "closed"       # Saudável, requisições passam normalmente
    OPEN = "open"           # Circuito aberto, falhas frequentes, requisições bloqueadas
    HALF_OPEN = "half_open" # Testando recuperação


class CircuitBreakerError(Exception):
    pass


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        cooldown: float = 60.0,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.last_failure_time = 0.0

    def can_execute(self) -> bool:
        now = time.monotonic()
        if self.state == CircuitState.OPEN:
            if now - self.last_failure_time >= self.cooldown:
                self.state = CircuitState.HALF_OPEN
                logger.info("Circuit breaker [%s] passou para HALF_OPEN", self.name)
                return True
            return False
        return True

    def record_success(self) -> None:
        self.consecutive_failures = 0
        if self.state != CircuitState.CLOSED:
            logger.info("Circuit breaker [%s] recuperado e CLOSED", self.name)
        self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        self.last_failure_time = time.monotonic()
        if self.consecutive_failures >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(
                "Circuit breaker [%s] ABRIU após %d falhas consecutivas. Cooldown de %.1fs",
                self.name,
                self.consecutive_failures,
                self.cooldown,
            )


class RateLimiter:
    def __init__(self, max_calls: int = 15, period_seconds: float = 60.0) -> None:
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self.timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        async with self._lock:
            now = time.monotonic()
            cutoff = now - self.period_seconds
            self.timestamps = [t for t in self.timestamps if t > cutoff]
            if len(self.timestamps) < self.max_calls:
                self.timestamps.append(now)
                return True
            return False


class ApiRegistry:
    def __init__(
        self,
        disabled_apis: set[str] | None = None,
        default_timeout: float = 10.0,
    ) -> None:
        self.disabled_apis = set(disabled_apis or [])
        self.default_timeout = default_timeout
        self.breakers: dict[str, CircuitBreaker] = {}
        self.limiters: dict[str, RateLimiter] = {}

    def get_breaker(self, name: str) -> CircuitBreaker:
        if name not in self.breakers:
            self.breakers[name] = CircuitBreaker(name=name, failure_threshold=3, cooldown=45.0)
        return self.breakers[name]

    def get_limiter(self, name: str) -> RateLimiter:
        if name not in self.limiters:
            self.limiters[name] = RateLimiter(max_calls=20, period_seconds=60.0)
        return self.limiters[name]

    async def execute(
        self,
        name: str,
        coro_fn: Callable[..., Awaitable[Any]],
        fallback_fn: Callable[..., Any] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if name in self.disabled_apis:
            logger.debug("API [%s] está desativada por configuração.", name)
            if fallback_fn:
                return fallback_fn(*args, **kwargs)
            raise RuntimeError(f"API '{name}' desativada por configuração.")

        breaker = self.get_breaker(name)
        if not breaker.can_execute():
            logger.warning("API [%s] com circuito aberto.", name)
            if fallback_fn:
                return fallback_fn(*args, **kwargs)
            raise CircuitBreakerError(f"API '{name}' temporariamente indisponível (circuito aberto).")

        limiter = self.get_limiter(name)
        allowed = await limiter.acquire()
        if not allowed:
            logger.warning("API [%s] excedeu rate limit.", name)
            if fallback_fn:
                return fallback_fn(*args, **kwargs)
            raise RuntimeError(f"API '{name}' excedeu o limite de requisições por minuto.")

        try:
            res = await asyncio.wait_for(coro_fn(*args, **kwargs), timeout=self.default_timeout)
            breaker.record_success()
            return res
        except Exception as exc:
            breaker.record_failure()
            logger.warning("Erro ao chamar API [%s]: %s", name, exc)
            if fallback_fn:
                return fallback_fn(*args, **kwargs)
            raise
