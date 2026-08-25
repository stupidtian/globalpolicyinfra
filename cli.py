"""Command-line interface for GlobalPolicyInfra.

Commands (ARCHITECTURE.md section 6.3): ``init``, ``config``, ``collect``
(country + source + key=value params; ``--dry-run`` plans without touching
anything), ``status`` (ledger counts), ``export`` (parquet snapshot), and the
repair channel ``requeue`` / ``reset`` / ``events-archive``.
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
    with StateStore.for_country(
        data_root, country, domain_schema=source.domain_schema,
        domain_keys=source.domain_keys,
    ) as store:
        engine = TaskEngine(store, data_root, country, source, HttpTransport())
        report = engine.run(params, dry_run=args.dry_run)
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
    if args.command == "events-archive":
        return _run_events_archive(args)
    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
