"""The single-loop task engine (ARCHITECTURE.md section 6.1).

    pick a due task → country builds the request → framework fetches →
    country parses → framework commits everything in one transaction
    (domain rows / documents / files / follow-up tasks / cursors / status)
    → pick the next one.

Collection, cleaning and extraction all ride this loop — a cleaning step is
just a ``type=clean`` task. The engine holds no country knowledge: it knows
the four contract types and nothing else (the testable boundary of §6.3).

Failure semantics (unchanged engine disciplines from the pilot):
- TransientError → retry with backoff (minutes-scale, persisted so a
  restart resumes); exhausted → needs_agent.
- PermanentError → failed_permanent; unknown exceptions → needs_agent.
- Empty result (zero rows/documents/files/next-tasks) → loud warning +
  raw response archived to ``failures/{task_id}/`` — the pilot's silent
  empty-parse incident made this mandatory.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from adapters.base import Response, SourceDefinition, TaskSeed, TaskView
from core import paths
from core.state import Status
from runtime.errors import PermanentError, TransientError
from runtime.retry import RetryPolicy
from runtime.transport.http import Transport
from store.state_store import StateStore

__all__ = ["EngineReport", "TaskEngine"]


@dataclass
class EngineReport:
    """Outcome counters of one engine run."""

    planned: int = 0
    done: int = 0
    retried: int = 0
    failed_permanent: int = 0
    escalated: int = 0
    empty_warned: int = 0
    detail: dict[str, int] = field(default_factory=dict)

    def summary_lines(self) -> list[str]:
        return [
            f"seeds enqueued: {self.planned}",
            (
                f"tasks done: {self.done} (retried {self.retried}, "
                f"permanent {self.failed_permanent}, escalated {self.escalated}, "
                f"empty-warned {self.empty_warned})"
            ),
        ]


class TaskEngine:
    """Drives one country × source against its ledger."""

    def __init__(
        self,
        store: StateStore,
        data_root: str | Path,
        country_code: str,
        source: SourceDefinition,
        transport: Transport | None = None,
        *,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.store = store
        self.country_root = paths.country_dir(data_root, country_code)
        self.country_code = country_code.upper()
        self.source = source
        self.transport = transport
        self.retry_policy = retry_policy or RetryPolicy()

    # -- public entry points ----------------------------------------------------

    def run(self, params: dict[str, Any], *, dry_run: bool = False) -> EngineReport:
        """Interpret params via the country's ``start_tasks``, enqueue the
        seeds, then work the queue until nothing is due."""
        # Sync seeds may need ledger cursors; hand them in via params so
        # country code stays a pure function of its inputs (section 6.3).
        params_with_kv = {**params, "_kv": self.store.kv_all()}
        seeds = self.source.start_tasks(params_with_kv)
        report = EngineReport()
        if dry_run:
            report.planned = self._dry_run(seeds)
            return report
        for seed in seeds:
            _task_id, changed = self.store.enqueue(seed)
            if changed:
                report.planned += 1
        self._work(report)
        return report

    def resume(self) -> EngineReport:
        """Keep working an existing queue (no new seeds)."""
        report = EngineReport()
        self._work(report)
        return report

    # -- internals -----------------------------------------------------------------

    def _work(self, report: EngineReport) -> None:
        while True:
            due = self.store.iter_due_tasks()
            if not due:
                return
            for task_id in due:
                task = self.store.get_task(task_id)
                if task is None:  # pragma: no cover - raced deletion
                    continue
                self._execute(task, report)

    def _execute(self, task: dict[str, Any], report: EngineReport) -> None:
        task_id = task["task_id"]
        view = TaskView(
            task_id=task_id,
            type=task["type"],
            params=task["params"],
            signal=task.get("signal"),
        )
        handler = self.source.task_types.get(view.type)
        if handler is None:
            self.store.record_task_outcome(
                task_id,
                Status.FAILED_PERMANENT,
                error=f"No handler registered for task type {view.type!r}",
            )
            report.failed_permanent += 1
            return

        attempt_number = task["attempts"] + 1
        try:
            spec = handler.build_request(view)
            if spec.transport != "http":
                raise PermanentError(
                    f"Transport {spec.transport!r} is not implemented yet (section 6.6)."
                )
            if self.transport is None:
                raise PermanentError("No transport configured for this engine.")
            response = self.transport.fetch(spec)
        except TransientError as exc:
            self._record_transient(task_id, attempt_number, exc, report)
            return
        except PermanentError as exc:
            self.store.record_task_outcome(
                task_id, Status.FAILED_PERMANENT, error=_describe(exc)
            )
            report.failed_permanent += 1
            return
        except Exception as exc:  # noqa: BLE001 — unknown errors are a classified outcome
            self.store.record_task_outcome(
                task_id, Status.NEEDS_AGENT, error=_describe(exc)
            )
            report.escalated += 1
            return

        try:
            result = handler.parse(response, view)
        except (TransientError, PermanentError) as exc:
            # Parse-side classification: transient retries, permanent dies;
            # either way the raw response is evidence — archive it.
            self._archive_failure(task, response, _describe(exc))
            if isinstance(exc, TransientError):
                self._record_transient(task_id, attempt_number, exc, report)
            else:
                self.store.record_task_outcome(
                    task_id, Status.FAILED_PERMANENT, error=_describe(exc)
                )
                report.failed_permanent += 1
            return
        except Exception as exc:  # noqa: BLE001
            self._archive_failure(task, response, _describe(exc))
            self.store.record_task_outcome(
                task_id, Status.NEEDS_AGENT, error=_describe(exc)
            )
            report.escalated += 1
            return

        if result.is_empty() and not result.expected_empty:
            report.empty_warned += 1
            print(
                f"[warn] empty result for {view.type} {task_id} — "
                "archived raw response for inspection",
                file=sys.stderr,
            )
            self._archive_failure(task, response, "empty result")

        try:
            self._write_files(result)
            summary = self.store.write_batch(task_id, self.country_code, result)
        except PermanentError as exc:
            self.store.record_task_outcome(
                task_id, Status.FAILED_PERMANENT, error=_describe(exc)
            )
            report.failed_permanent += 1
            return
        except Exception as exc:  # noqa: BLE001 — unknown errors are a classified outcome
            self.store.record_task_outcome(
                task_id, Status.NEEDS_AGENT, error=_describe(exc)
            )
            report.escalated += 1
            return
        report.done += 1
        counter = report.detail
        counter["rows"] = counter.get("rows", 0) + summary["rows"]
        counter["documents"] = counter.get("documents", 0) + summary["documents"]
        counter["tasks"] = counter.get("tasks", 0) + summary["tasks"]

    def _record_transient(
        self, task_id: str, attempt_number: int, exc: Exception, report: EngineReport
    ) -> None:
        if self.retry_policy.is_exhausted(attempt_number):
            self.store.record_task_outcome(
                task_id, Status.NEEDS_AGENT, error=_describe(exc)
            )
            report.escalated += 1
        else:
            self.store.record_task_outcome(
                task_id,
                Status.RETRY,
                error=_describe(exc),
                next_attempt_at=self.retry_policy.next_attempt_at(
                    attempt_number, datetime.now(UTC)
                ),
            )
            report.retried += 1

    def _write_files(self, result: Any) -> None:
        """Write declared files under the country root. A path escaping the
        country directory is a contract violation (permanent)."""
        for file_out in result.files:
            target = (self.country_root / file_out.path).resolve()
            if not target.is_relative_to(self.country_root.resolve()):
                raise PermanentError(
                    f"Refusing to write outside the country directory: {file_out.path}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(file_out.content)

    def _archive_failure(self, task: dict[str, Any], response: Response, reason: str) -> None:
        failures_dir = self.country_root / "failures" / task["task_id"]
        failures_dir.mkdir(parents=True, exist_ok=True)
        (failures_dir / "response.bin").write_bytes(response.content)
        meta = {
            "task_id": task["task_id"],
            "type": task["type"],
            "params": task["params"],
            "status_code": response.status_code,
            "reason": reason,
            "archived_at": datetime.now(UTC).isoformat(),
        }
        (failures_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _dry_run(self, seeds: list[TaskSeed]) -> int:
        print("dry-run — nothing enqueued, nothing fetched")
        print(f"  seeds this run would enqueue: {len(seeds)}")
        for shown, seed in enumerate(seeds[:20], start=1):
            print(f"    [{seed.type}] {json.dumps(seed.params, ensure_ascii=False)}")
        if len(seeds) > 20:
            print(f"  … and {len(seeds) - shown} more")
        due = self.store.iter_due_tasks()
        print(f"  tasks already due in ledger: {len(due)}")
        return len(seeds)


def _describe(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"
