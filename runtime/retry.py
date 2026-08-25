"""Retry and backoff policy for the deterministic loop.

v1 is deterministic by design (decision record 2026-08-20: correctness first,
bugs must be reproducible): exponential backoff without jitter by default.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from core.state import format_ts

__all__ = ["RetryPolicy"]


@dataclass(frozen=True)
class RetryPolicy:
    """How many attempts an item gets and how far retries are spaced.

    ``max_attempts`` counts executions, not retries: with ``max_attempts=3``
    an item runs once, then retries at most twice before escalation.
    """

    max_attempts: int = 3
    base_delay: float = 60.0
    factor: float = 2.0
    max_delay: float = 3600.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1.")
        if self.base_delay < 0:
            raise ValueError("base_delay must be >= 0.")
        if self.factor < 1:
            raise ValueError("factor must be >= 1.")
        if self.max_delay < self.base_delay:
            raise ValueError("max_delay must be >= base_delay.")

    def delay_seconds(self, attempt: int) -> float:
        """Backoff before the next attempt, given ``attempt`` failures so far.

        Attempt 1 failed → wait ``base_delay``; attempt 2 failed →
        ``base_delay * factor``; capped at ``max_delay``.
        """
        if attempt < 1:
            raise ValueError("attempt must be >= 1.")
        return min(self.base_delay * self.factor ** (attempt - 1), self.max_delay)

    def next_attempt_at(self, attempt: int, now: datetime) -> str:
        """Scheduled time of the next attempt as a fixed-width ISO string."""
        return format_ts(now + timedelta(seconds=self.delay_seconds(attempt)))

    def is_exhausted(self, attempts: int) -> bool:
        """True when no further attempt is allowed."""
        return attempts >= self.max_attempts
