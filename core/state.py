"""State model for the task ledger.

ARCHITECTURE.md section 6.1/6.2 (task model v1 draft): the old item×stage
matrix is gone — processing stages are task types now. What remains is the
status vocabulary every task lives through.

Status semantics (error trisection, ARCHITECTURE.md section 2.1):

- ``pending`` — waiting to be picked up.
- ``retry`` — transient error (timeout, rate limit); retry with backoff.
- ``done`` — succeeded (a newer signal may reopen it, section 6.5).
- ``failed_permanent`` — permanent error (404, structural corruption).
- ``needs_agent`` — escalation exit of the deterministic engine (unknown
  errors, or retries exhausted).
- ``needs_human`` — terminal after an agent also failed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

__all__ = [
    "TERMINAL_STATUSES",
    "Status",
    "format_ts",
    "is_terminal",
    "utc_now_iso",
]

_TS_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def format_ts(dt: datetime) -> str:
    """Format a datetime as a fixed-width UTC ISO string.

    Fixed width matters: these strings are compared lexicographically in SQL
    (``next_attempt_at <= now``), which must agree with chronological order.
    """
    return dt.astimezone(UTC).strftime(_TS_FORMAT)


def utc_now_iso() -> str:
    """Current UTC time as a fixed-width ISO string (see :func:`format_ts`)."""
    return format_ts(datetime.now(UTC))


class Status(str, Enum):
    """Status of one task."""

    PENDING = "pending"
    RETRY = "retry"
    DONE = "done"
    FAILED_PERMANENT = "failed_permanent"
    NEEDS_AGENT = "needs_agent"
    NEEDS_HUMAN = "needs_human"


#: Statuses from which the engine will never pick the task up again.
TERMINAL_STATUSES = frozenset(
    {
        Status.DONE,
        Status.FAILED_PERMANENT,
        Status.NEEDS_AGENT,
        Status.NEEDS_HUMAN,
    }
)


def is_terminal(status: Status) -> bool:
    """Whether the engine considers this status final."""
    return status in TERMINAL_STATUSES
