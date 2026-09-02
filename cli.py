"""Command-line interface for GlobalPolicyInfra.

Commands (ARCHITECTURE.md section 6.3): ``init``, ``config``, ``collect``
(country + source + key=value params; ``--dry-run`` plans without touching
anything), ``status`` (ledger counts), ``export`` (parquet snapshot), the
repair channel ``requeue`` / ``reset`` / ``repair-documents`` /
``events-archive``, and the one-time ``migrate-layout`` (USA 2026-09-01
directory spec; see docs/tasks/2026-08-24-usa/layout-migration.md).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from __version__ import __version__
from adapters.base import SourceDefinition
from adapters.registry import RegistryError, get_source
from core import paths
from core.config import (
    ConfigError,
    load_env_file,
    resolve_data_root,
    write_config,
)
from runtime.engine import TaskEngine
from runtime.proclock import CollectLock, LockBusyError
from runtime.transport.http import HttpTransport
from store.index_io import write_index
from store.state_store import StateStore

__all__ = ["build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gpi",
        description="GlobalPolicyInfra: infrastructure for cross-country policy documents.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser(
        "init", help="Create the global config file (guided first run)."
    )
    init_parser.add_argument(
        "--data-root", default=None, help="Data root directory to record in the config file."
    )
    init_parser.add_argument(
        "--config-dir", default=None,
        help="Where to write the config directory (default: ~/.globalpolicyinfra).",
    )
    init_parser.add_argument("--force", action="store_true", help="Overwrite an existing config file.")

    config_parser = subparsers.add_parser(
        "config", help="Show the resolved data root (or how to configure one)."
    )
    config_parser.add_argument(
        "--config-file", default=None,
        help="Explicit config file location (default: ~/.globalpolicyinfra/config.toml).",
    )

    collect_parser = subparsers.add_parser(
        "collect", help="Run a country source's task pipeline (params as key=value)."
    )
    collect_parser.add_argument("--country", required=True, help="ISO3 code, e.g. usa")
    collect_parser.add_argument("--source", required=True, help="Source name, e.g. bills")
    collect_parser.add_argument(
        "params", nargs="*", metavar="key=value",
        help="Source parameters, e.g. congress=119 window=2026-08-10:2026-08-24",
    )
    collect_parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be enqueued and what is already due; no writes, no fetching",
    )
    collect_parser.add_argument(
        "--delay", default=None, metavar="MIN:MAX",
        help="Request interval override in seconds, e.g. 3:6 (or one value "
        "for a fixed interval); default politeness 0.5:1.0. Runtime-only — "
        "never stored in task params or the ledger",
    )
    collect_parser.add_argument(
        "--config-file", default=None,
        help="Explicit config file location (default: ~/.globalpolicyinfra/config.toml).",
    )

    status_parser = subparsers.add_parser("status", help="Ledger counts for one country.")
    status_parser.add_argument("--country", required=True, help="ISO3 code, e.g. usa")
    status_parser.add_argument("--source", default=None, help="Include domain-table counts of this source")
    status_parser.add_argument(
        "--config-file", default=None,
        help="Explicit config file location (default: ~/.globalpolicyinfra/config.toml).",
    )

    export_parser = subparsers.add_parser("export", help="Export the policy_index.parquet snapshot.")
    export_parser.add_argument("--country", required=True, help="ISO3 code, e.g. usa")
    export_parser.add_argument(
        "--config-file", default=None,
        help="Explicit config file location (default: ~/.globalpolicyinfra/config.toml).",
    )

    requeue_parser = subparsers.add_parser(
        "requeue", help="Repair channel: un-fail failed/escalated tasks back to pending."
    )
    requeue_parser.add_argument("--country", required=True, help="ISO3 code, e.g. usa")
    requeue_parser.add_argument("--type", default=None, dest="task_type", help="Only tasks of this type")
    requeue_parser.add_argument("--id", default=None, help="A single task_id")
    requeue_parser.add_argument(
        "--config-file", default=None,
        help="Explicit config file location (default: ~/.globalpolicyinfra/config.toml).",
    )

    reset_parser = subparsers.add_parser(
        "reset", help="Repair channel: force tasks back to pending regardless of status."
    )
    reset_parser.add_argument("--country", required=True, help="ISO3 code, e.g. usa")
    reset_parser.add_argument("--type", default=None, dest="task_type", help="Tasks of this type")
    reset_parser.add_argument("--id", default=None, help="A single task_id")
    reset_parser.add_argument(
        "--config-file", default=None,
        help="Explicit config file location (default: ~/.globalpolicyinfra/config.toml).",
    )

    repair_parser = subparsers.add_parser(
        "repair-documents",
        help="Repair channel: re-derive doc_type on documents rows (audited).",
    )
    repair_parser.add_argument("--country", required=True, help="ISO3 code, e.g. usa")
    repair_parser.add_argument(
        "--entity-ref", required=True,
        help="Entity reference of the rows to correct, e.g. fr_documents:2026-16979",
    )
    repair_parser.add_argument(
        "--doc-type", required=True,
        help="Replacement doc_type from the controlled vocabulary",
    )
    repair_parser.add_argument(
        "--config-file", default=None,
        help="Explicit config file location (default: ~/.globalpolicyinfra/config.toml).",
    )

    layout_parser = subparsers.add_parser(
        "migrate-layout",
        help="One-time move to the 2026-09-01 USA directory spec (layout-migration.md).",
    )
    layout_parser.add_argument("--country", required=True, help="ISO3 code, e.g. usa")
    layout_parser.add_argument(
        "--apply", action="store_true",
        help="Execute the plan (default: dry run)",
    )
    layout_parser.add_argument(
        "--config-file", default=None,
        help="Explicit config file location (default: ~/.globalpolicyinfra/config.toml).",
    )

    events_parser = subparsers.add_parser(
        "events-archive", help="Archive audit events older than a cutoff to a .jsonl.gz file."
    )
    events_parser.add_argument("--country", required=True, help="ISO3 code, e.g. usa")
    events_parser.add_argument(
        "--before", default=None, metavar="ISO_TS",
        help="Archive events with ts < this timestamp (default: now, i.e. all)",
    )
    events_parser.add_argument(
        "--out", default=None,
        help="Output file (default: {country}/00_metadata/events-archive-<ts>.jsonl.gz)",
    )
    events_parser.add_argument(
        "--config-file", default=None,
        help="Explicit config file location (default: ~/.globalpolicyinfra/config.toml).",
    )

    return parser


def _run_init(args: argparse.Namespace) -> int:
    data_root = args.data_root
    if data_root is None:
        if sys.stdin.isatty():
            data_root = input("Data root directory for GPI: ").strip()
        if not data_root:
            print("No data root given. Re-run with --data-root <path>.", file=sys.stderr)
            return 2
    try:
        path = write_config(data_root, config_dir=args.config_dir, overwrite=args.force)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote config to {path}")
    return 0


def _run_config(args: argparse.Namespace) -> int:
    try:
        data_root = resolve_data_root(config_path=args.config_file)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(data_root)
    return 0


def _parse_kv_params(raw: Sequence[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for item in raw:
        key, sep, value = item.partition("=")
        if not sep or not key.strip():
            raise SystemExit(f"error: params must look like key=value (got {item!r})")
        params[key.strip()] = value.strip()
    return params


def _parse_delay(raw: str) -> tuple[float, float]:
    """Parse ``--delay MIN:MAX`` (seconds; a single value means a fixed
    interval). Runtime-only politeness knob (framework-hardening 1.3): it
    flows CLI → transport construction and must never enter task params —
    task_id is derived from type+params (section 6.1)."""
    lo, sep, hi = raw.partition(":")
    try:
        lo_f = float(lo)
        hi_f = float(hi) if sep else lo_f
    except ValueError:
        raise SystemExit(
            f"error: --delay must look like MIN:MAX or N in seconds (got {raw!r})"
        ) from None
    if not (0.0 <= lo_f <= hi_f):
        raise SystemExit(f"error: --delay requires 0 <= MIN <= MAX (got {raw!r})")
    return lo_f, hi_f


def _resolve_source(args: argparse.Namespace, country: str) -> tuple[SourceDefinition, Path]:
    try:
        data_root = resolve_data_root(config_path=args.config_file)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    try:
        source = get_source(country, args.source)
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    return source, data_root


def _run_collect(args: argparse.Namespace) -> int:
    country = args.country.upper()
    params = _parse_kv_params(args.params)
    source, data_root = _resolve_source(args, country)
    paths.ensure_layout(data_root, country)
    # Single-process lock (framework-hardening 1.2): dry-run never locks
    # (ruling Q5 — zero writes, diagnostics stay usable under a live lock).
    lock: CollectLock | None = None
    took_over = False
    previous_pid: int | None = None
    if not args.dry_run:
        lock = CollectLock(paths.country_dir(data_root, country))
        try:
            acquired = lock.acquire()
        except LockBusyError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 3  # lock-busy exit code (ruling Q6, 2026-09-02)
        took_over = acquired.took_over
        previous_pid = acquired.previous_pid
    try:
        with StateStore.for_country(
            data_root, country, domain_schema=source.domain_schema,
            domain_keys=source.domain_keys,
        ) as store:
            if took_over:
                store.note_event(
                    "engine",
                    "collect.lock",
                    f"lock taken over from stale holder (pid {previous_pid}); "
                    "previous run likely crashed",
                )
            transport = (
                HttpTransport(delay_range=_parse_delay(args.delay))
                if args.delay
                else HttpTransport()
            )
            engine = TaskEngine(store, data_root, country, source, transport)
            report = engine.run(params, dry_run=args.dry_run)
    finally:
        if lock is not None:
            lock.release()
    if not args.dry_run:
        print(f"[{country}/{args.source}] collection finished")
        for line in report.summary_lines():
            print(f"  {line}")
        for key in sorted(report.detail):
            print(f"  {key}: {report.detail[key]}")
    return 0


def _run_status(args: argparse.Namespace) -> int:
    try:
        data_root = resolve_data_root(config_path=args.config_file)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    country = args.country.upper()
    domain_tables: tuple[str, ...] = ()
    if args.source:
        try:
            source = get_source(country, args.source)
            domain_tables = source.domain_tables
        except RegistryError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    with StateStore.for_country(data_root, country) as store:
        status = store.collection_status(domain_tables)
    print(f"[{country}] ledger status @ {paths.state_db_path(data_root, country)}")
    for task_type, counts in sorted(status["tasks"].items()):
        rendered = ", ".join(f"{s}: {n}" for s, n in sorted(counts.items()))
        print(f"  {task_type}: {rendered}")
    print(f"  documents: {status['documents']}")
    for table, count in sorted(status["domain"].items()):
        print(f"  {table}: {count if count >= 0 else '(table not created)'}")
    for key, value in sorted(status["kv"].items()):
        print(f"  kv {key} = {value}")
    return 0


def _run_export(args: argparse.Namespace) -> int:
    try:
        data_root = resolve_data_root(config_path=args.config_file)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    country = args.country.upper()
    with StateStore.for_country(data_root, country) as store:
        rows = store.connection.execute(
            """
            SELECT doc_id, country_code, title, publication_date, doc_type,
                   entity_ref, produced_by, raw_format, local_path, file_hash,
                   content_length, source_url
            FROM documents ORDER BY doc_id
            """
        ).fetchall()
    import pandas as pd

    frame = pd.DataFrame([dict(r) for r in rows])
    target = paths.index_path(data_root, country)
    write_index(frame, target)
    print(f"Wrote {len(frame)} rows to {target}")
    return 0


def _run_requeue(args: argparse.Namespace) -> int:
    try:
        data_root = resolve_data_root(config_path=args.config_file)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    country = args.country.upper()
    with StateStore.for_country(data_root, country) as store:
        tasks = store.requeue_tasks(task_type=args.task_type, task_id=args.id)
    print(f"[{country}] requeued {tasks} task(s) back to pending")
    return 0


def _run_reset(args: argparse.Namespace) -> int:
    if not (args.task_type or args.id):
        print("error: give --type or --id (refusing to reset everything)", file=sys.stderr)
        return 2
    try:
        data_root = resolve_data_root(config_path=args.config_file)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    country = args.country.upper()
    with StateStore.for_country(data_root, country) as store:
        tasks = store.reset_tasks_force(task_type=args.task_type, task_id=args.id)
    print(f"[{country}] force-reset {tasks} task(s) to pending")
    return 0


def _run_repair_documents(args: argparse.Namespace) -> int:
    try:
        data_root = resolve_data_root(config_path=args.config_file)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    country = args.country.upper()
    with StateStore.for_country(data_root, country) as store:
        touched = store.correct_document_doc_type(
            country_code=country, entity_ref=args.entity_ref, doc_type=args.doc_type
        )
    print(f"[{country}] corrected doc_type on {touched} documents row(s) "
          f"({args.entity_ref} -> {args.doc_type})")
    return 0 if touched else 1


# -- migrate-layout (one-time, USA 2026-09-01 layout spec) ----------------------------
#
# DEVIATION (recorded in layout-migration.md §4.5): this command performs
# bulk ALTER/UPDATE/moves outside the write_batch path. Every step is
# idempotent (prefix rewrites match nothing on a second run; disk moves
# detect already-moved sources), ledger updates run in ONE transaction, and
# an events row records the application.

_LAYOUT_PREFIX_REWRITES: tuple[tuple[str, str], ...] = (
    # bills: policies/{congress} -> bills/{congress}
    ("01_raw/policies/119/", "01_raw/bills/119/"),
    # FR publications: policies/fr -> regulations/fr
    ("01_raw/policies/fr/", "01_raw/regulations/fr/"),
    # guidance: department layer (epa maps to itself — no change)
    ("01_raw/guidance/irs/", "01_raw/guidance/treasury/irs/"),
    ("01_raw/guidance/ofac/", "01_raw/guidance/treasury/ofac/"),
    ("01_raw/guidance/occ/", "01_raw/guidance/treasury/occ/"),
    ("01_raw/guidance/bis/", "01_raw/guidance/commerce/bis/"),
    ("01_raw/guidance/nws/", "01_raw/guidance/commerce/nws/"),
)

_LAYOUT_DIR_MOVES: tuple[tuple[str, str], ...] = (
    ("01_raw/policies/119", "01_raw/bills/119"),
    ("01_raw/policies/fr", "01_raw/regulations/fr"),
    ("01_raw/guidance/irs", "01_raw/guidance/treasury/irs"),
    ("01_raw/guidance/ofac", "01_raw/guidance/treasury/ofac"),
    ("01_raw/guidance/occ", "01_raw/guidance/treasury/occ"),
    ("01_raw/guidance/bis", "01_raw/guidance/commerce/bis"),
    ("01_raw/guidance/nws", "01_raw/guidance/commerce/nws"),
)

_NIST_OLD = "01_raw/guidance/nist/snapshots/July2026/allrecords-MODS.xml"
_NIST_NEW = "01_raw/guidance/commerce/nist/catalog/July2026.xml"

_LAYOUT_REMOVE_EMPTY: tuple[str, ...] = (
    "01_raw/policies",
    "01_raw/guidance/nist",
    "01_raw/html",
    "01_raw/listings",
    "01_raw/pdf",
)

_DEPARTMENT_MAP = {
    "irs": "treasury", "ofac": "treasury", "occ": "treasury",
    "bis": "commerce", "nist": "commerce", "nws": "commerce", "epa": "epa",
}


def _run_migrate_layout(args: argparse.Namespace) -> int:
    try:
        data_root = resolve_data_root(config_path=args.config_file)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    country = args.country.upper()
    country_root = paths.country_dir(data_root, country)
    with StateStore.for_country(data_root, country) as store:
        conn = store.connection

        _path_tables = [
            (table, column)
            for table, column in (
                ("bills", "folder"), ("fr_documents", "folder"),
                ("guidance_documents", "folder"), ("documents", "local_path"),
                ("tasks", "params"),
            )
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
        ]

        # -- plan (idempotent steps report what they would still touch) -----
        plan: list[tuple[str, int]] = []
        for old, new in _LAYOUT_PREFIX_REWRITES:
            n = 0
            for table, column in _path_tables:
                n += conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {column} LIKE ?",
                    (old + "%",),
                ).fetchone()[0]
            if n:
                plan.append((f"{old} -> {new}", n))
        nist_rows = conn.execute(
            "SELECT COUNT(*) FROM source_snapshots WHERE file_path = ?", (_NIST_OLD,)
        ).fetchone()[0]
        if nist_rows:
            plan.append((_NIST_OLD + " -> " + _NIST_NEW, nist_rows))
        dept_null = conn.execute(
            "SELECT COUNT(*) FROM guidance_documents WHERE department IS NULL"
        ).fetchone()[0] if "department" in [
            r[1] for r in conn.execute("PRAGMA table_info(guidance_documents)")
        ] else conn.execute("SELECT COUNT(*) FROM guidance_documents").fetchone()[0]
        if dept_null:
            plan.append(("guidance_documents.department backfill", dept_null))
        moves = [
            (src, dst) for src, dst in _LAYOUT_DIR_MOVES
            if (country_root / src).exists() and not (country_root / dst).exists()
        ]
        nist_move = (country_root / _NIST_OLD).exists() and not (country_root / _NIST_NEW).exists()

        print(f"[{country}] layout migration plan (spec: layout-migration.md):")
        for item, n in plan:
            print(f"  ledger: {item}  ({n} rows)")
        for src, dst in moves:
            print(f"  disk:   {src} -> {dst}")
        if nist_move:
            print(f"  disk:   {_NIST_OLD} -> {_NIST_NEW}")
        if not (plan or moves or nist_move):
            print("  nothing to do (already migrated)")
            return 0
        if not args.apply:
            print("dry run — pass --apply to execute")
            return 0

        # -- apply: one ledger transaction, then disk moves ------------------
        from datetime import UTC as _UTC
        from datetime import datetime as _dt
        with store.transaction() as tx:
            if "department" not in [r[1] for r in tx.execute("PRAGMA table_info(guidance_documents)")]:
                tx.execute("ALTER TABLE guidance_documents ADD COLUMN department TEXT")
            for agency, dept in _DEPARTMENT_MAP.items():
                tx.execute(
                    "UPDATE guidance_documents SET department = ? WHERE agency = ?",
                    (dept, agency),
                )
            for old, new in _LAYOUT_PREFIX_REWRITES:
                for table, column in _path_tables:
                    tx.execute(
                        f"UPDATE {table} SET {column} = replace({column}, ?, ?) "
                        f"WHERE {column} LIKE ?",
                        (old, new, old + "%"),
                    )
            tx.execute(
                "UPDATE source_snapshots SET file_path = ? WHERE file_path = ?",
                (_NIST_NEW, _NIST_OLD),
            )
            tx.execute(
                "INSERT INTO events (ts, entity_type, subject_id, stage, "
                "from_status, to_status, detail) VALUES (?, 'layout', "
                "'migrate-layout', NULL, NULL, 'applied', ?)",
                (
                    _dt.now(_UTC).isoformat().replace("+00:00", "Z"),
                    "USA layout spec 2026-09-01 applied (see layout-migration.md)",
                ),
            )

        moved = 0
        for src, dst in _LAYOUT_DIR_MOVES:
            s, d = country_root / src, country_root / dst
            if s.exists() and not d.exists():
                d.parent.mkdir(parents=True, exist_ok=True)
                s.rename(d)
                moved += 1
        if nist_move:
            s, d = country_root / _NIST_OLD, country_root / _NIST_NEW
            d.parent.mkdir(parents=True, exist_ok=True)
            s.rename(d)
            moved += 1
            # remove the now-empty nist tree (snapshots/July2026 dirs)
            for parent in (s.parent, s.parent.parent):
                try:
                    parent.rmdir()
                except OSError:
                    pass
        for rel in _LAYOUT_REMOVE_EMPTY:
            p = country_root / rel
            try:
                p.rmdir()
                print(f"  removed empty dir: {rel}")
            except OSError:
                pass
        print(f"[{country}] layout migration applied: {moved} dir move(s), "
              "ledger rewritten in one transaction")
        return 0


def _run_events_archive(args: argparse.Namespace) -> int:
    try:
        data_root = resolve_data_root(config_path=args.config_file)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    country = args.country.upper()
    cutoff = args.before or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    with StateStore.for_country(data_root, country) as store:
        if args.out:
            out_path = Path(args.out)
        else:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            out_path = (
                paths.country_dir(data_root, country)
                / "00_metadata"
                / f"events-archive-{stamp}.jsonl.gz"
            )
        exported = store.export_events_before(cutoff, out_path)
        if exported == 0:
            print(f"[{country}] no events older than {cutoff} — nothing archived")
            return 0
        deleted = store.delete_events_before(cutoff)
    print(f"[{country}] archived {exported} events to {out_path} (deleted {deleted})")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    # Secrets channel (decision record 2026-08-20): load the repo-local .env
    # into the environment; existing variables win.
    load_env_file()

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        return _run_init(args)
    if args.command == "config":
        return _run_config(args)
    if args.command == "collect":
        return _run_collect(args)
    if args.command == "status":
        return _run_status(args)
    if args.command == "export":
        return _run_export(args)
    if args.command == "requeue":
        return _run_requeue(args)
    if args.command == "reset":
        return _run_reset(args)
    if args.command == "repair-documents":
        return _run_repair_documents(args)
    if args.command == "migrate-layout":
        return _run_migrate_layout(args)
    if args.command == "events-archive":
        return _run_events_archive(args)
    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
