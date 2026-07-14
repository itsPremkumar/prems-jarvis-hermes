"""recovery: self-healing primitives — retry-with-backoff and circuit breaker.

These are the reusable building blocks for requirements 1, 3, 7, 8. They are
pure stdlib, fully unit-tested, and used by the cycle for external ops (network
probes, worker dispatch retries, DB reconnects).
"""
from __future__ import annotations
import time
import random
from typing import Callable, TypeVar, Optional

T = TypeVar("T")


class TransientError(Exception):
    """Raised when an operation failed but may succeed on retry."""


class PermanentError(Exception):
    """Raised when an operation failed and retrying is pointless."""


def retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff: float = 2.0,
    jitter: bool = True,
    on_error: Optional[Callable[[Exception, int], None]] = None,
) -> T:
    """Exponential backoff retry.

    - max_attempts<=0 means INFINITE retry (safe for critical infra per req 8).
    - PermanentError short-circuits immediately.
    - TransientError (and any Exception) is retried with capped exponential delay.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except PermanentError:
            raise
        except Exception as e:  # noqa: treat as transient
            if on_error:
                on_error(e, attempt)
            if 0 < max_attempts <= attempt:
                raise
            delay = min(max_delay, base_delay * (backoff ** (attempt - 1)))
            if jitter:
                delay *= (0.5 + random.random())
            time.sleep(delay)


class CircuitBreaker:
    """Stops hammering a failing dependency; opens after `threshold` failures,
    half-opens after `cooldown`, closes on success. Classic fault-tolerance
    pattern (req 3, 15)."""

    def __init__(self, threshold: int = 5, cooldown: float = 30.0):
        self.threshold = threshold
        self.cooldown = cooldown
        self._failures = 0
        self._opened_at = 0.0
        self.state = "closed"

    def allow(self) -> bool:
        if self.state == "open":
            if time.time() - self._opened_at >= self.cooldown:
                self.state = "half-open"
                return True
            return False
        return True

    def success(self):
        self._failures = 0
        self.state = "closed"

    def failure(self):
        self._failures += 1
        if self.state == "half-open" or self._failures >= self.threshold:
            self.state = "open"
            self._opened_at = time.time()

    def call(self, fn: Callable[[], T]) -> T:
        if not self.allow():
            raise TransientError(f"circuit open ({self.state})")
        try:
            result = fn()
            self.success()
            return result
        except Exception:
            self.failure()
            raise
