"""The jorf source: task-type registry and seed generation.

Journal officiel de la République française ("Lois et Décrets" edition),
collected from DILA's open-data directory at echanges.dila.gouv.fr — a plain
keyless HTTP listing of daily tar.gz snapshots (see docs/countries/fra/
jorf-zh.md). Flat document path: zero domain tables, ``documents`` is the
whole ledger.

Task types (each = one module with ``build_request`` + ``parse``):

===============  =====================================================
type             what one task does
===============  =====================================================
jorf_index       seed: GET the directory listing; every publication date
                 inside the window yields one jorf_issue (the day's
                 *earliest* archive — the complete issue as published)
jorf_issue       one day's tar.gz; unpacks in memory into one document per
                 texte (version + struct + article XMLs in one folder)
===============  =====================================================

Params (key=value on the CLI)::

    window=2026-08-26:2026-08-27   closed date range (required, or sync=1)
    sync=1                          from = day after the kv cursor
                                    jorf_last_date, to = today

Two mechanisms worth knowing (probed 2026-08-28, see the doc):

- Filenames carry an unpredictable timestamp (JORF_20260826-002510.tar.gz),
  so enumeration must go through the listing page — URLs are not
  constructible from a date.
- Each date's earliest archive is the complete daily issue; later archives
  the same day are whole-corpus maintenance diffs (ELI backfills, keyword
  enrichment) that this source deliberately skips: the captured state is
  *as-published*.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "BASE_URL",
    "CURSOR_KEY",
    "FIRST_DATE",
    "USER_AGENT",
    "build_source",
    "start_tasks",
]

BASE_URL = "https://echanges.dila.gouv.fr/OPENDATA/JORF"
#: First daily increment published in the directory (older history lives in
#: the periodic global "stock" archive, out of scope for this source).
FIRST_DATE = "2025-07-13"
CURSOR_KEY = "jorf_last_date"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country fra --source jorf window=2026-08-26:2026-08-27\n"
        "  python cli.py collect --country fra --source jorf sync=1\n"
        "  python cli.py status --country fra --source jorf"
    )


def _parse_date(raw: str, label: str) -> str:
    try:
        date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None
    return raw


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")

    if params.get("window"):
        window = str(params["window"])
        from_str, sep, to_str = window.partition(":")
        if not sep or not from_str or not to_str:
            raise _fail(f"window must look like FROM:TO (got {window!r})")
        from_str = _parse_date(from_str.strip(), "window FROM")
        to_str = _parse_date(to_str.strip(), "window TO")
    elif is_sync:
        kv = params.get("_kv", {})
        cursor = kv.get(CURSOR_KEY)
        if not cursor:
            raise _fail("sync=1 needs a previous sweep; run an initial window=… first")
        from_str = (date.fromisoformat(cursor) + timedelta(days=1)).isoformat()
        to_str = datetime.now(UTC).date().isoformat()
    else:
        raise _fail("give window=FROM:TO or sync=1")

    if from_str > to_str:
        raise _fail(f"window start {from_str} is after its end {to_str}")

    return [TaskSeed(type="jorf_index", params={"from": from_str, "to": to_str})]


def build_source() -> SourceDefinition:
    from adapters.fra.sources.jorf.index import JorfIndexHandler
    from adapters.fra.sources.jorf.issue import JorfIssueHandler

    return SourceDefinition(
        name="jorf",
        start_tasks=start_tasks,
        task_types={
            "jorf_index": JorfIndexHandler(),
            "jorf_issue": JorfIssueHandler(),
        },
    )
