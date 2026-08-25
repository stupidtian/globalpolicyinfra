"""Error trisection for the deterministic loop.

ARCHITECTURE.md section 2.1: adapters classify failures by raising

- :class:`TransientError` — timeout, rate limit, ... → retry with backoff;
- :class:`PermanentError` — 404, structural corruption, ... → failed_permanent;
- any other exception — unknown → escalated to ``needs_agent``.

Adapters raise; they never retry and never write state (that is the runtime
loop's job, ARCHITECTURE.md section 3).
"""

from __future__ import annotations

__all__ = ["GPIRuntimeError", "PermanentError", "TransientError"]


class GPIRuntimeError(Exception):
    """Base class for classified runtime errors."""


class TransientError(GPIRuntimeError):
    """A failure worth retrying (timeout, rate limit, temporary outage)."""


class PermanentError(GPIRuntimeError):
    """A failure that retrying cannot fix (404, corrupted structure, ...)."""
