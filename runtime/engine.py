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

import gzip
import json
import sys
from collections.abc import Collection
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from adapters.base import Response, SourceDefinition, TaskResult, TaskSeed, TaskView
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
    skipped_foreign: int = 0
    cleaned: int = 0
    detail: dict[str, int] = field(default_factory=dict)

    def summary_lines(self) -> list[str]:
        lines = [
            f"seeds enqueued: {self.planned}",
            (
                f"tasks done: {self.done} (retried {self.retried}, "
                f"permanent {self.failed_permanent}, escalated {self.escalated}, "
                f"empty-warned {self.empty_warned})"
            ),
        ]
        if self.skipped_foreign:
            lines.append(
                f"due tasks skipped (no handler in this source): {self.skipped_foreign}"
            )
        if self.cleaned:
            lines.append(f"documents cleaned: {self.cleaned}")
        return lines


class TaskEngine:
    """Drives one country × source against its ledger."""

    #: Tasks per dispatch round on the parallel path = factor × workers
    #: (internal constant, deliberately not a CLI knob — plan Q4).
    _BATCH_FACTOR = 4

    def __init__(
        self,
        store: StateStore,
        data_root: str | Path,
        country_code: str,
        source: SourceDefinition,
        transport: Transport | None = None,
        *,
        retry_policy: RetryPolicy | None = None,
        max_workers: int = 1,
    ) -> None:
        self.store = store
        self.country_root = paths.country_dir(data_root, country_code)
        self.country_code = country_code.upper()
        self.source = source
        self.transport = transport
        self.retry_policy = retry_policy or RetryPolicy()
        self.max_workers = max_workers
        self._warned_foreign: set[str] = set()
        self._only_types: set[str] | None = None  # narrowed fetch set (run_cleaning)

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

    def run_cleaning(self, only_types: Collection[str]) -> EngineReport:
        """Work only the source's cleaning task types (cli ``clean``):
        seeds were enqueued by the caller; this resumes the queue with a
        NARROWED fetch-type set. The foreign-task warning keeps the FULL
        type set — a narrowed set would flag this source's own pending
        collection tasks as foreign (framework-cleaning 2.4)."""
        self._only_types = set(only_types)
        try:
            return self.resume()
        finally:
            self._only_types = None

    # -- internals -----------------------------------------------------------------

    def _work(self, report: EngineReport) -> None:
        """Dispatch (ruling 1.1): the default (max_workers=1) takes the
        serial path below, byte-for-byte the pre-concurrency loop; only an
        explicit >= 2 ever enters the parallel machinery."""
        if self.max_workers >= 2:
            self._work_parallel(report)
            return
        self._work_serial(report)

    def _work_serial(self, report: EngineReport) -> None:
        full_types = set(self.source.task_types)
        run_types = self._only_types if self._only_types is not None else full_types
        self._warn_foreign_due(full_types, report)
        while True:
            due = self.store.iter_due_tasks(types=run_types)
            if not due:
                break
            for task_id in due:
                task = self.store.get_task(task_id)
                if task is None:  # pragma: no cover - raced deletion
                    continue
                self._execute(task, report)
        # Second checkpoint: catches unknown types our own parse enqueued
        # mid-run (still first-wins per type, so no repeat warnings).
        self._warn_foreign_due(full_types, report)

    # -- local-document reads (framework-cleaning 2.1) ----------------------------

    def _is_clean_task(self, task: dict[str, Any]) -> bool:
        clean = self.source.clean
        return clean is not None and task["type"] == clean.task_type

    def _resolve_local_doc_path(self, doc_id: str) -> str:
        """doc_id → documents.local_path. Main-thread only on the parallel
        path (workers never touch the store); inline on the serial path.
        Loud PermanentError names the doc_id and the expected path."""
        local_path = self.store.get_document_local_path(doc_id)
        if not local_path:
            raise PermanentError(
                f"local_doc {doc_id!r}: no documents row with a local_path"
            )
        if not (self.country_root / local_path).is_file():
            raise PermanentError(
                f"local_doc {doc_id!r}: file missing at "
                f"{self.country_root / local_path}"
            )
        return local_path

    def _read_local_doc_bytes(self, doc_id: str, rel_path: str) -> bytes:
        """Read one local document (any thread): bytes in, ``.gz`` suffix
        decompressed. Missing file raced away → Permanent; other OSError
        (file locked etc.) → Transient; corrupt gzip → Permanent."""
        target = self.country_root / rel_path
        try:
            raw = target.read_bytes()
        except FileNotFoundError as exc:
            raise PermanentError(
                f"local_doc {doc_id!r}: file missing at {target}"
            ) from exc
        except OSError as exc:
            raise TransientError(f"local_doc {doc_id!r}: {exc}") from exc
        if rel_path.lower().endswith(".gz"):
            try:
                raw = gzip.decompress(raw)
            except OSError as exc:  # BadGzipFile subclasses OSError
                raise PermanentError(
                    f"local_doc {doc_id!r}: corrupt gzip at {target}"
                ) from exc
        return raw

    # -- parallel path (framework-concurrency, rulings 1.2/1.4) -------------------

    def _work_parallel(self, report: EngineReport) -> None:
        """Thread-pool path: workers run build_request → fetch → parse only
        (I/O plus pure functions); every ledger write happens on the main
        thread in :meth:`_commit`, so the store keeps a single writer.
        Bounded batches keep the in-flight set small and SIGINT simple."""
        if not self.source.parallel_safe:
            print(
                f"[warn] source {self.source.name!r} is not declared parallel_safe — "
                "running with 1 worker (declare parallel_safe=True on the "
                "SourceDefinition if the source has no cross-task session state)",
                file=sys.stderr,
            )
            self._work_serial(report)
            return
        full_types = set(self.source.task_types)
        run_types = self._only_types if self._only_types is not None else full_types
        self._warn_foreign_due(full_types, report)
        batch_size = max(4, self._BATCH_FACTOR * self.max_workers)
        pool = ThreadPoolExecutor(
            max_workers=self.max_workers, thread_name_prefix="gpi-worker"
        )
        # SIGINT best-effort (plan): KeyboardInterrupt propagates through
        # the finally below — dispatching stops, not-yet-started work is
        # cancelled, in-flight requests finish uninterpreted; anything
        # uncommitted stays pending and is redone on the next run (ledger
        # idempotency is the backstop).
        try:
            while True:
                due = self.store.iter_due_tasks(types=run_types)
                if not due:
                    break
                futures: list[Future[_IOOutcome]] = []
                for task_id in due[:batch_size]:
                    task = self.store.get_task(task_id)
                    if task is None:  # pragma: no cover - raced deletion
                        continue
                    if self._is_clean_task(task):
                        # Workers never touch the store: resolve the local
                        # path on the main thread and hand it in (ruling
                        # 2.1). Resolution failures classify here directly.
                        doc_id = str(task["params"].get("doc_id", ""))
                        try:
                            preloaded = self._resolve_local_doc_path(doc_id)
                        except PermanentError as exc:
                            self._commit(
                                _IOOutcome(task=task, kind="permanent", error=exc),
                                report,
                            )
                            continue
                        except TransientError as exc:
                            self._commit(
                                _IOOutcome(task=task, kind="transient", error=exc),
                                report,
                            )
                            continue
                        futures.append(pool.submit(self._execute_io, task, preloaded))
                    else:
                        futures.append(pool.submit(self._execute_io, task))
                for future in as_completed(futures):
                    self._commit(future.result(), report)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        self._warn_foreign_due(full_types, report)

    def _execute_io(self, task: dict[str, Any], local_path: str | None = None) -> _IOOutcome:
        """Worker half of one task: build_request → fetch → parse. No store
        access whatsoever (the sqlite connection must never cross threads);
        local-read tasks get their pre-resolved path from the dispatch
        loop. Classification mirrors _execute exactly; ledger writes
        happen later on the main thread."""
        view = TaskView(
            task_id=task["task_id"],
            type=task["type"],
            params=task["params"],
            signal=task.get("signal"),
        )
        handler = self.source.task_types.get(view.type)
        if handler is None:
            return _IOOutcome(task=task, kind="guard")
        try:
            spec = handler.build_request(view)
            if not spec.url and not spec.local_doc:
                raise PermanentError(
                    f"RequestSpec has neither url nor local_doc "
                    f"(task {task['task_id']}, type {view.type!r})"
                )
            if spec.local_doc is not None:
                if local_path is None:
                    raise PermanentError(
                        f"local_doc task {task['task_id']} reached a worker "
                        "without a pre-resolved path"
                    )
                response = Response(
                    content=self._read_local_doc_bytes(spec.local_doc, local_path),
                    status_code=200,
                )
            else:
                if spec.transport != "http":
                    raise PermanentError(
                        f"Transport {spec.transport!r} is not implemented yet (section 6.6)."
                    )
                if self.transport is None:
                    raise PermanentError("No transport configured for this engine.")
                response = self.transport.fetch(spec)
        except TransientError as exc:
            return _IOOutcome(task=task, kind="transient", error=exc)
        except PermanentError as exc:
            return _IOOutcome(task=task, kind="permanent", error=exc)
        except Exception as exc:  # noqa: BLE001 — unknown errors are a classified outcome
            return _IOOutcome(task=task, kind="escalate", error=exc)
        try:
            result = handler.parse(response, view)
        except TransientError as exc:
            return _IOOutcome(task=task, kind="transient", error=exc, response=response)
        except PermanentError as exc:
            return _IOOutcome(task=task, kind="permanent", error=exc, response=response)
        except Exception as exc:  # noqa: BLE001
            return _IOOutcome(task=task, kind="escalate", error=exc, response=response)
        return _IOOutcome(task=task, kind="result", result=result, response=response)

    def _commit(self, outcome: _IOOutcome, report: EngineReport) -> None:
        """Main-thread half: apply one worker outcome through the same
        trisection and bookkeeping as the serial path (single writer,
        ruling 1.2)."""
        task = outcome.task
        task_id = task["task_id"]
        attempt_number = task["attempts"] + 1

        if outcome.kind == "result":
            result, response = outcome.result, outcome.response
            assert result is not None and response is not None
            if result.is_empty() and not result.expected_empty:
                report.empty_warned += 1
                print(
                    f"[warn] empty result for {task['type']} {task_id} — "
                    "archived raw response for inspection",
                    file=sys.stderr,
                )
                self._archive_failure(task, response, "empty result")
            try:
                self._write_files(result)
                self._write_cleaned(result)
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
            counter["cleaned"] = counter.get("cleaned", 0) + summary["cleaned"]
            report.cleaned += summary["cleaned"]
            return

        if outcome.kind == "transient":
            assert outcome.error is not None
            if outcome.response is not None:  # parse-side failure: keep evidence
                self._archive_failure(task, outcome.response, _describe(outcome.error))
            self._record_transient(task_id, attempt_number, outcome.error, report)
            return
        if outcome.kind == "permanent":
            assert outcome.error is not None
            if outcome.response is not None:
                self._archive_failure(task, outcome.response, _describe(outcome.error))
            self.store.record_task_outcome(
                task_id, Status.FAILED_PERMANENT, error=_describe(outcome.error)
            )
            report.failed_permanent += 1
            return
        if outcome.kind == "escalate":
            assert outcome.error is not None
            if outcome.response is not None:
                self._archive_failure(task, outcome.response, _describe(outcome.error))
            self.store.record_task_outcome(
                task_id, Status.NEEDS_AGENT, error=_describe(outcome.error)
            )
            report.escalated += 1
            return
        # guard: a fetched task without a handler (race between pull and
        # execute, or a renamed type) — skip, never kill (hardening 1.1).
        print(
            f"[warn] due task {task_id} of type {task['type']!r} has no handler "
            "in this source — left pending (other source or renamed type)",
            file=sys.stderr,
        )
        self._warned_foreign.add(task["type"])
        self.store.note_event(
            "engine",
            f"foreign:{task['type']}",
            f"task {task_id} skipped by the execution guard; left pending",
        )
        report.skipped_foreign += 1

    def _warn_foreign_due(self, own_types: set[str], report: EngineReport) -> None:
        """Visibility for due tasks this source cannot run (other sources'
        leftovers or renamed types). The fetch layer already keeps them out
        of the engine (ruling 2026-09-02); this reports what was held back:
        one stderr warning and one audit note per type per run, tasks left
        pending. The engine does not know who those tasks belong to, so the
        wording must not claim it."""
        for task_type, ids in sorted(self.store.foreign_due_tasks(own_types).items()):
            if task_type in self._warned_foreign:
                continue
            self._warned_foreign.add(task_type)
            print(
                f"[warn] {len(ids)} due tasks of type {task_type!r} have no handler "
                "in this source — left pending (other source or renamed type)",
                file=sys.stderr,
            )
            self.store.note_event(
                "engine",
                f"foreign:{task_type}",
                f"{len(ids)} due tasks have no handler in this source; left pending; "
                f"examples: {', '.join(ids[:3])}",
            )
            report.skipped_foreign += len(ids)

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
            # Second line of defense (ruling 2026-09-02): the fetch layer
            # filters foreign types, so reaching here means a race between
            # fetch and execute or a renamed type. Skip — never claim, never
            # kill (2026-09-01 incident: 794 tasks lost to the old behavior).
            print(
                f"[warn] due task {task_id} of type {view.type!r} has no handler "
                "in this source — left pending (other source or renamed type)",
                file=sys.stderr,
            )
            self._warned_foreign.add(view.type)
            self.store.note_event(
                "engine",
                f"foreign:{view.type}",
                f"task {task_id} skipped by the execution guard; left pending",
            )
            report.skipped_foreign += 1
            return

        attempt_number = task["attempts"] + 1
        try:
            spec = handler.build_request(view)
            if not spec.url and not spec.local_doc:
                raise PermanentError(
                    f"RequestSpec has neither url nor local_doc "
                    f"(task {task_id}, type {view.type!r})"
                )
            if spec.local_doc is not None:
                response = Response(
                    content=self._read_local_doc_bytes(
                        spec.local_doc, self._resolve_local_doc_path(spec.local_doc)
                    ),
                    status_code=200,
                )
            else:
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
            self._write_cleaned(result)
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
        counter["cleaned"] = counter.get("cleaned", 0) + summary["cleaned"]
        report.cleaned += summary["cleaned"]

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

    def _write_cleaned(self, result: Any) -> None:
        """Write cleaned texts to their framework-derived paths (before
        write_batch, files-style: a crash in between leaves an orphan the
        re-run rewrites). The path is derived from doc_id alone — country
        packs never specify it — and the determinism contract is enforced
        loudly (framework-cleaning 2.2)."""
        for record in result.cleaned:
            content = record.content
            if (
                content.startswith(b"\xef\xbb\xbf")
                or b"\r" in content
                or not content.endswith(b"\n")
            ):
                raise PermanentError(
                    f"cleaned output for {record.doc_id} violates the determinism "
                    "contract (BOM / CR / trailing newline)"
                )
            target = self.country_root / paths.cleaned_rel_path(record.doc_id)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

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
        own_types = set(self.source.task_types)
        due = self.store.iter_due_tasks(types=own_types)
        print(f"  tasks already due in ledger (this source): {len(due)}")
        # Operational check from the 2026-09-01 incident: before switching
        # sources, confirm the other sources' queues are drained.
        for task_type, ids in sorted(self.store.foreign_due_tasks(own_types).items()):
            print(
                f"  due tasks of type {task_type!r} (no handler in this source): "
                f"{len(ids)} — left pending"
            )
        return len(seeds)


@dataclass
class _IOOutcome:
    """What one worker produced for one task (ruling 1.2): workers never
    touch the store — the classified outcome travels back to the main
    thread, where :meth:`TaskEngine._commit` applies the very same
    trisection code as the serial path."""

    task: dict[str, Any]
    kind: Literal["result", "transient", "permanent", "escalate", "guard"]
    result: TaskResult | None = None
    response: Response | None = None
    error: Exception | None = None


def _describe(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"
