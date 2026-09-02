"""Single-process lock for collect runs.

Framework-owned runtime component (ARCHITECTURE.md section 3: the runtime
layer owns execution safety; module added by framework-hardening task 1.2
with architecture approval, ruling Q1 2026-09-02). Purpose: refuse a second
``collect`` process on the same country ledger — the 2026-08-25 and
2026-09-01 incidents both had two engines splitting one queue.

Design: a lock file (``{country_root}/collect.lock``) recording the
holder's pid / host / start time, created atomically with
``O_CREAT | O_EXCL`` (portable across Windows and POSIX — no fcntl). A
pre-existing lock is probed for liveness (win32: ctypes
OpenProcess/GetExitCodeProcess; POSIX: ``os.kill(pid, 0)``). A live holder
is refused; a dead one is taken over atomically (``os.replace``), with the
takeover noted in the ledger's events by the caller. Uncertain cases fail
safe: refusal over a wrong takeover. A crash between create and write can
leave a pid-less file; a well-formed lock always has a pid, so an
unreadable or pid-less leftover counts as stale and is taken over.

Known v1 limitation (accepted in plan section 1.2): PID reuse or a
cross-user permission failure makes an uncertain probe read as "alive" —
the refusal message names the lock file for a human decision.
"""

from __future__ import annotations

import json
import os
import platform
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = ["AcquiredInfo", "CollectLock", "LockBusyError"]

LOCK_FILE_NAME = "collect.lock"

_WIN32_STILL_ACTIVE = 259
_WIN32_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class LockBusyError(RuntimeError):
    """Another live process holds the collect lock."""

    def __init__(self, path: Path, pid: int, started_at: str) -> None:
        self.path = path
        self.pid = pid
        self.started_at = started_at
        super().__init__(
            f"another collect process appears to be running "
            f"(pid {pid}, started {started_at}); if that is wrong, "
            f"remove {path} after checking"
        )


@dataclass(frozen=True)
class AcquiredInfo:
    """Outcome of a successful acquire."""

    took_over: bool
    previous_pid: int | None = None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            _WIN32_PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True  # cannot tell — assume alive (fail safe)
            alive: bool = code.value == _WIN32_STILL_ACTIVE
            return alive
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but owned by another user
    return True


class CollectLock:
    """Exclusive per-country lock for collect runs (see module docstring)."""

    def __init__(self, country_root: str | Path) -> None:
        self.path = Path(country_root) / LOCK_FILE_NAME
        self._pid = os.getpid()
        self._held = False

    def acquire(self) -> AcquiredInfo:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": self._pid,
            "host": platform.node(),
            "started_at": datetime.now(UTC).isoformat(),
        }
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(payload))
            self._held = True
            return AcquiredInfo(took_over=False)

        previous = self._read()
        if previous is not None:
            pid = _safe_int(previous.get("pid"))
            if pid is not None and _pid_alive(pid):
                raise LockBusyError(
                    self.path, pid, str(previous.get("started_at", "?"))
                )
        # Stale: dead pid, or an unreadable/pid-less leftover. Atomic takeover.
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, self.path)
        self._held = True
        return AcquiredInfo(
            took_over=True,
            previous_pid=_safe_int(previous.get("pid")) if previous else None,
        )

    def release(self) -> None:
        if not self._held:
            return
        current = self._read()
        if current is not None and current.get("pid") == self._pid:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
        # A successor rewrote the file: leave it alone.
        self._held = False

    def _read(self) -> dict[str, Any] | None:
        try:
            payload: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None


def _safe_int(raw: Any) -> int | None:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
