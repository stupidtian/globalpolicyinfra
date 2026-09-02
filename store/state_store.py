"""The per-country ledger: tasks + documents + kv + events (+ domain tables).

ARCHITECTURE.md section 6.2 (task model v1 draft, 2026-08-24):

- ``tasks`` is the core: todo list, progress and retry book in one table
  (processing stages are task types; the old stage_states matrix is gone).
- ``documents`` is the cross-country research layer (section 5.1), linking
  to domain entities via ``entity_ref`` and to its producing task via
  ``produced_by``.
- ``kv`` holds small scalars (incremental-sync cursors); ``events`` is the
  optional audit trail (status jumps only, archived periodically).
- Domain tables belong to the country pack: their DDL is handed to this
  store at open time and executed here — but all writes go through
  :meth:`write_batch` (the single sanctioned write path), never by country
  code touching a connection.

One SQLite database per country (``{data_root}/{ISO3}_policy/state.db``),
WAL mode. Synchronous single worker (decision record 2026-08-20).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from collections.abc import Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Self, cast

from adapters.base import TaskResult, TaskSeed
from core import paths
from core.document import compute_doc_id
from core.state import Status, utc_now_iso

__all__ = ["StateStore"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    params TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    signal TEXT,
    next_attempt_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(status, next_attempt_at);

CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    country_code TEXT,
    title TEXT,
    publication_date TEXT,
    issuing_authority TEXT,
    doc_type TEXT,
    source_url TEXT,
    entity_ref TEXT,
    produced_by TEXT,
    raw_format TEXT,
    local_path TEXT,
    file_hash TEXT,
    content_length INTEGER,
    language TEXT,
    collection_date TEXT,
    meta TEXT NOT NULL DEFAULT '{}',
    registered_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_entity ON documents(entity_ref);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    stage TEXT,
    from_status TEXT,
    to_status TEXT,
    detail TEXT
);
"""

_REQUEUEABLE = (Status.FAILED_PERMANENT, Status.NEEDS_AGENT, Status.NEEDS_HUMAN)


def _append_event(
    conn: sqlite3.Connection,
    ts: str,
    entity_type: str,
    subject_id: str,
    stage: str | None,
    from_status: str | None,
    to_status: str | None,
    detail: str | None,
) -> None:
    conn.execute(
        "INSERT INTO events (ts, entity_type, subject_id, stage, from_status, to_status, detail) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ts, entity_type, subject_id, stage, from_status, to_status, detail),
    )


class StateStore:
    """The per-country ledger and the single sanctioned write path."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        domain_schema: str = "",
        domain_keys: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.domain_keys: dict[str, tuple[str, ...]] = dict(domain_keys or {})
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        if domain_schema:
            self._conn.executescript(domain_schema)
        self._conn.commit()

    @classmethod
    def for_country(
        cls,
        data_root: str | Path,
        country_code: str,
        *,
        domain_schema: str = "",
        domain_keys: dict[str, tuple[str, ...]] | None = None,
    ) -> StateStore:
        return cls(
            paths.state_db_path(data_root, country_code),
            domain_schema=domain_schema,
            domain_keys=domain_keys,
        )

    # -- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @property
    def connection(self) -> sqlite3.Connection:
        """Diagnostics only — routine writes go through write_batch."""
        return self._conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise

    # -- tasks: enqueue with dedup / reopen -------------------------------------

    def enqueue(self, seed: TaskSeed) -> tuple[str, bool]:
        """Enqueue one task. Returns ``(task_id, changed)``.

        Dedup/reopen semantics (section 6.5): the same type+params always
        maps to the same task_id. A new seed for a pending/retry task only
        refreshes its signal; for a done task it reopens it **iff** the seed
        carries a newer signal (source-side update stamp); terminal-failed
        tasks are left for the repair channel.
        """
        task_id = compute_task_id(seed.type, seed.params)
        now = utc_now_iso()
        params_json = json.dumps(seed.params, ensure_ascii=False, sort_keys=True)
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT status, signal FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO tasks (task_id, type, params, status, signal, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (task_id, seed.type, params_json, Status.PENDING.value,
                     seed.signal, now, now),
                )
                _append_event(conn, now, "task", task_id, None, None,
                              Status.PENDING.value, "task enqueued")
                return task_id, True
            status = Status(row["status"])
            changed = False
            if status in (Status.PENDING, Status.RETRY):
                if seed.signal and (not row["signal"] or seed.signal > row["signal"]):
                    conn.execute(
                        "UPDATE tasks SET signal = ?, updated_at = ? WHERE task_id = ?",
                        (seed.signal, now, task_id),
                    )
                    changed = True
            elif status is Status.DONE and seed.signal and (not row["signal"] or seed.signal > row["signal"]):
                conn.execute(
                    "UPDATE tasks SET status = ?, attempts = 0, last_error = NULL, "
                    "next_attempt_at = NULL, signal = ?, updated_at = ? WHERE task_id = ?",
                    (Status.PENDING.value, seed.signal, now, task_id),
                )
                _append_event(conn, now, "task", task_id, None, Status.DONE.value,
                              Status.PENDING.value, "task reopened (newer signal)")
                changed = True
        return task_id, changed

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["params"] = json.loads(record["params"])
        return record

    def iter_due_tasks(
        self, now: str | None = None, *, types: Collection[str] | None = None
    ) -> list[str]:
        """Task ids the engine may run: pending, or retry whose scheduled
        time has come. Ordered by creation time (oldest work first).

        With ``types`` (the running source's task-type set) only tasks of
        those types are returned — other sources' tasks stay in the ledger
        untouched. This fetch-layer filter is the main defense against the
        2026-09-01 cross-source kill (794 tasks; architecture ruling
        2026-09-02). ``None`` keeps the unfiltered behavior.
        """
        now = now or utc_now_iso()
        params: list[Any] = [Status.PENDING.value, Status.RETRY.value, now]
        query = (
            "SELECT task_id FROM tasks "
            "WHERE (status = ? OR (status = ? AND (next_attempt_at IS NULL OR next_attempt_at <= ?))) "
        )
        if types is not None:
            if not types:
                return []
            placeholders = ", ".join("?" for _ in types)
            query += f"AND type IN ({placeholders}) "
            params.extend(types)
        query += "ORDER BY created_at, task_id"
        rows = self._conn.execute(query, params).fetchall()
        return [row["task_id"] for row in rows]

    def foreign_due_tasks(
        self, own_types: Collection[str], now: str | None = None
    ) -> dict[str, list[str]]:
        """Due tasks whose type is NOT in ``own_types``, grouped by type —
        the engine's material for the foreign-task warning and audit note
        (ruling 2026-09-02). The id list doubles as count and examples."""
        now = now or utc_now_iso()
        params: list[Any] = [Status.PENDING.value, Status.RETRY.value, now]
        query = (
            "SELECT type, task_id FROM tasks "
            "WHERE (status = ? OR (status = ? AND (next_attempt_at IS NULL OR next_attempt_at <= ?))) "
        )
        if own_types:
            placeholders = ", ".join("?" for _ in own_types)
            query += f"AND type NOT IN ({placeholders}) "
            params.extend(own_types)
        query += "ORDER BY created_at, task_id"
        grouped: dict[str, list[str]] = {}
        for row in self._conn.execute(query, params).fetchall():
            grouped.setdefault(row["type"], []).append(row["task_id"])
        return grouped

    def record_task_outcome(
        self,
        task_id: str,
        status: Status,
        *,
        error: str | None = None,
        next_attempt_at: str | None = None,
    ) -> None:
        """Record one execution outcome (attempt count + status + schedule)."""
        now = utc_now_iso()
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT status, attempts FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Task {task_id!r} is not enqueued.")
            attempts = row["attempts"] + 1
            conn.execute(
                "UPDATE tasks SET status = ?, attempts = ?, last_error = ?, "
                "next_attempt_at = ?, updated_at = ? WHERE task_id = ?",
                (status.value, attempts, error, next_attempt_at, now, task_id),
            )
            _append_event(conn, now, "task", task_id, None, row["status"],
                          status.value, error)

    def task_status_counts(self) -> dict[tuple[str, str], int]:
        rows = self._conn.execute(
            "SELECT type, status, COUNT(*) AS n FROM tasks GROUP BY type, status"
        ).fetchall()
        return {(row["type"], row["status"]): row["n"] for row in rows}

    # -- write_batch: the single sanctioned ledger write --------------------------

    def write_batch(
        self,
        task_id: str,
        country_code: str,
        result: TaskResult,
    ) -> dict[str, int]:
        """Apply one task's result in a single transaction: task → done,
        domain rows upserted/replaced, documents registered, follow-up tasks
        enqueued, cursors updated, audit event appended.

        Files are written to disk by the engine *before* this call; a crash
        in between leaves harmless orphans (task not done → re-run rewrites).
        """
        now = utc_now_iso()
        summary = {"rows": 0, "documents": 0, "tasks": 0, "cursors": 0}
        with self.transaction() as conn:
            task_row = conn.execute(
                "SELECT status, attempts FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task_row is None:
                raise KeyError(f"Task {task_id!r} is not enqueued.")
            attempts = task_row["attempts"] + 1
            conn.execute(
                "UPDATE tasks SET status = ?, attempts = ?, last_error = NULL, "
                "next_attempt_at = NULL, updated_at = ? WHERE task_id = ?",
                (Status.DONE.value, attempts, now, task_id),
            )
            _append_event(conn, now, "task", task_id, None, task_row["status"],
                          Status.DONE.value, None)

            for table, rows in result.upsert_rows.items():
                for row in rows:
                    _upsert_row(conn, table, row, self.domain_keys.get(table))
                summary["rows"] += len(rows)

            for replacement in result.replacements:
                clause = " AND ".join(f"{col} = ?" for col in replacement.match)
                conn.execute(
                    f"DELETE FROM {replacement.table} WHERE {clause}",
                    tuple(replacement.match.values()),
                )
                for row in replacement.rows:
                    _upsert_row(conn, replacement.table, row, self.domain_keys.get(replacement.table))
                summary["rows"] += len(replacement.rows)

            for record in result.documents:
                doc_id = compute_doc_id(
                    country_code, record.source_url, record.publication_date
                )
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO documents "
                    "(doc_id, country_code, title, publication_date, issuing_authority, "
                    "doc_type, source_url, entity_ref, produced_by, language, meta, "
                    "registered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        doc_id, country_code, record.title, record.publication_date,
                        record.issuing_authority, record.doc_type, record.source_url,
                        record.entity_ref, task_id, record.language,
                        json.dumps(record.raw_metadata, ensure_ascii=False, sort_keys=True),
                        now,
                    ),
                )
                if cursor.rowcount:
                    summary["documents"] += 1

            for file_out in result.files:
                if file_out.doc_id:
                    conn.execute(
                        "UPDATE documents SET local_path = ?, raw_format = ?, file_hash = ?, "
                        "content_length = ?, collection_date = ? WHERE doc_id = ?",
                        (
                            file_out.path,
                            Path(file_out.path).suffix.lstrip(".").lower(),
                            hashlib.sha256(file_out.content).hexdigest(),
                            len(file_out.content),
                            now,
                            file_out.doc_id,
                        ),
                    )

            for seed in result.next_tasks:
                self.enqueue(seed)
                summary["tasks"] += 1

            for key, value in result.cursor_updates.items():
                conn.execute(
                    "INSERT INTO kv (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )
                summary["cursors"] += 1
        return summary

    # -- kv -------------------------------------------------------------------------

    def kv_get(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return None if row is None else row["value"]

    def kv_all(self) -> dict[str, str]:
        rows = self._conn.execute("SELECT key, value FROM kv").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def kv_set(self, key: str, value: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO kv (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def note_event(self, entity_type: str, subject_id: str, detail: str) -> None:
        """Append one audit event outside any task lifecycle — engine-level
        notes (foreign-task summaries, lock takeovers). Exists so callers
        never touch the connection directly."""
        now = utc_now_iso()
        with self.transaction() as conn:
            _append_event(conn, now, entity_type, subject_id, None, None, None, detail)

    # -- repair channel ---------------------------------------------------------------

    def requeue_tasks(
        self,
        *,
        task_type: str | None = None,
        task_id: str | None = None,
    ) -> int:
        """Un-fail tasks: failed/escalated → pending (healthy tasks untouched)."""
        rows = self._select_tasks(task_type=task_type, task_id=task_id)
        requeueable = [s.value for s in _REQUEUEABLE]
        now = utc_now_iso()
        touched = 0
        with self.transaction() as conn:
            for row in rows:
                if row["status"] not in requeueable:
                    continue
                conn.execute(
                    "UPDATE tasks SET status = ?, next_attempt_at = NULL, "
                    "updated_at = ? WHERE task_id = ?",
                    (Status.PENDING.value, now, row["task_id"]),
                )
                _append_event(conn, now, "task", row["task_id"], None,
                              row["status"], Status.PENDING.value,
                              "requeued via repair channel")
                touched += 1
        return touched

    def reset_tasks_force(
        self,
        *,
        task_type: str | None = None,
        task_id: str | None = None,
    ) -> int:
        """Force tasks back to pending regardless of status (redo hammer)."""
        rows = self._select_tasks(task_type=task_type, task_id=task_id)
        now = utc_now_iso()
        with self.transaction() as conn:
            for row in rows:
                conn.execute(
                    "UPDATE tasks SET status = ?, attempts = 0, last_error = NULL, "
                    "next_attempt_at = NULL, updated_at = ? WHERE task_id = ?",
                    (Status.PENDING.value, now, row["task_id"]),
                )
                _append_event(conn, now, "task", row["task_id"], None,
                              row["status"], Status.PENDING.value,
                              "force-reset via repair channel")
        return len(rows)

    def correct_document_doc_type(
        self,
        *,
        country_code: str,
        entity_ref: str,
        doc_type: str,
    ) -> int:
        """Repair channel for the documents registry: re-derive one
        entity's doc_type in place (audited like requeue/reset).

        DEVIATION (2026-09-01, USA pack, batch E): documents rows are
        INSERT OR IGNORE, so resetting the producing task can never heal a
        mis-derived doc_type — re-registration is ignored on conflict. This
        scoped UPDATE is the minimal sanctioned path; every call leaves an
        event row (entity_type='documents')."""
        now = utc_now_iso()
        with self.transaction() as conn:
            rows = conn.execute(
                "SELECT doc_id, doc_type FROM documents "
                "WHERE country_code = ? AND entity_ref = ?",
                (country_code, entity_ref),
            ).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE documents SET doc_type = ? WHERE doc_id = ?",
                    (doc_type, row["doc_id"]),
                )
                _append_event(conn, now, "documents", row["doc_id"], None,
                              row["doc_type"], doc_type,
                              "doc_type corrected via repair channel")
        return len(rows)

    def _select_tasks(self, *, task_type: str | None, task_id: str | None) -> list[sqlite3.Row]:
        if task_id is not None:
            return self._conn.execute(
                "SELECT task_id, status FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchall()
        if task_type is not None:
            return self._conn.execute(
                "SELECT task_id, status FROM tasks WHERE type = ?", (task_type,)
            ).fetchall()
        return self._conn.execute("SELECT task_id, status FROM tasks").fetchall()

    # -- events archive ------------------------------------------------------------------

    def export_events_before(self, cutoff_ts: str, out_path: str | Path) -> int:
        rows = self._conn.execute(
            "SELECT * FROM events WHERE ts < ? ORDER BY id", (cutoff_ts,)
        ).fetchall()
        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(target, "wt", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
        return len(rows)

    def delete_events_before(self, cutoff_ts: str) -> int:
        with self.transaction() as conn:
            cursor = conn.execute("DELETE FROM events WHERE ts < ?", (cutoff_ts,))
            return int(cursor.rowcount or 0)

    def iter_events(
        self, subject_id: str | None = None, entity_type: str | None = None
    ) -> list[sqlite3.Row]:
        query = "SELECT * FROM events"
        clauses: list[str] = []
        params: list[str] = []
        if subject_id is not None:
            clauses.append("subject_id = ?")
            params.append(subject_id)
        if entity_type is not None:
            clauses.append("entity_type = ?")
            params.append(entity_type)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        return self._conn.execute(query + " ORDER BY id", params).fetchall()

    # -- status overview ---------------------------------------------------------------------

    def collection_status(self, domain_tables: Sequence[str] = ()) -> dict[str, Any]:
        task_rows = self._conn.execute(
            "SELECT type, status, COUNT(*) AS n FROM tasks GROUP BY type, status"
        ).fetchall()
        by_type: dict[str, dict[str, int]] = {}
        for row in task_rows:
            by_type.setdefault(row["type"], {})[row["status"]] = row["n"]
        domain: dict[str, int] = {}
        for table in domain_tables:
            try:
                domain[table] = int(
                    self._conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
                )
            except sqlite3.OperationalError:
                domain[table] = -1  # table not created yet
        kv_rows = self._conn.execute("SELECT key, value FROM kv ORDER BY key").fetchall()
        return {
            "tasks": by_type,
            "documents": int(
                self._conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"]
            ),
            "domain": domain,
            "kv": {row["key"]: row["value"] for row in kv_rows},
        }


# -- helpers --------------------------------------------------------------------------


def compute_task_id(task_type: str, params: Mapping[str, Any]) -> str:
    """§6.1: ``sha256(type + canonical(params))[:8]`` — the same work always
    maps to the same id, so re-enqueueing dedups naturally."""
    import hashlib

    canonical = json.dumps(dict(params), ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(f"{task_type}|{canonical}".encode()).hexdigest()[:8]
    return f"{task_type}_{digest}"


def _upsert_row(
    conn: sqlite3.Connection,
    table: str,
    row: dict[str, Any],
    key_columns: tuple[str, ...] | None,
) -> None:
    """Merge one row into a domain table.

    With declared key columns the write is UPDATE-first (partial rows merge
    into the existing record; SQLite would otherwise enforce NOT NULL on the
    insert path even when the row exists and only the update was meant).
    Without keys it falls back to INSERT .. ON CONFLICT DO UPDATE over the
    table's own primary key.
    """
    values = {
        k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
        for k, v in row.items()
    }
    if key_columns and all(col in values for col in key_columns):
        set_cols = [col for col in values if col not in key_columns]
        matched = False
        if set_cols:
            cursor = conn.execute(
                f"UPDATE {table} SET {', '.join(f'{c} = ?' for c in set_cols)} "
                f"WHERE {' AND '.join(f'{c} = ?' for c in key_columns)}",
                [values[c] for c in set_cols] + [values[c] for c in key_columns],
            )
            matched = bool(cursor.rowcount)
        else:
            matched = (
                conn.execute(
                    f"SELECT 1 FROM {table} WHERE "
                    f"{' AND '.join(f'{c} = ?' for c in key_columns)}",
                    [values[c] for c in key_columns],
                ).fetchone()
                is not None
            )
        if not matched:
            conn.execute(
                f"INSERT INTO {table} ({', '.join(values)}) "
                f"VALUES ({', '.join('?' for _ in values)})",
                list(values.values()),
            )
        return
    columns = list(values)
    updates = ", ".join(f"{col} = excluded.{col}" for col in columns)
    conn.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)}) "
        f"ON CONFLICT DO UPDATE SET {updates}",
        list(values.values()),
    )


def cast_meta(raw: str | None) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(raw or "{}"))
