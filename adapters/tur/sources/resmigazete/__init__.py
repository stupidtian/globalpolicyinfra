"""The resmigazete source: task-type registry and seed generation.

Resmî Gazete, the Turkish official gazette (published online by the
Presidency per Cumhurbaşkanlığı Kararnamesi No. 10; daily, with same-day
extra editions marked "Mükerrer"; probed 2026-09-27, samples in the task
folder; see docs/countries/tur/resmigazete-zh.md). Flat document-shaped
source: zero domain tables, ``documents`` is the whole ledger.

Task types (each = one module with ``build_request`` + ``parse``):

===============  =====================================================
type             what one task does
===============  =====================================================
rg_day           one edition of one calendar day (``GET /fihrist?
                 tarih=…[&mukerrer=N]``, server-rendered HTML): issue
                 header (date, issue number, mükerrer ordinal) plus the
                 section → type → item walk. Every in-scope item (default
                 scope=mevzuat drops the İLÂN announcement section,
                 recognised by its ``/ilanlar/`` file path) yields one
                 rg_item seed carrying the bibliographic fields a PDF
                 item cannot recover from its bytes. The task always
                 seeds the next mükerrer probe (rg_day, mukerrer+1): a
                 302-followed homepage body ends the chain as an
                 explained empty. No edition at all (pre-2000-06-28) is
                 the same homepage shape. Every fully consumed edition
                 advances the ``rg_last_date`` cursor.
rg_item          one gazette item file (``/eskiler/{Y}/{M}/
                 {YYYYMMDD}[M{k}]-{seq}.{htm|pdf}``): response bytes
                 stored verbatim as the primary file; htm items are
                 Windows-1254 Word-HTML whose header (issue number,
                 date, native type, issuing authority, uppercase title)
                 enriches the record and cross-checks the seed.
===============  =====================================================

Params (key=value on the CLI)::

    window=2026-09-21:2026-09-26  closed date range (required, or sync=1)
    sync=1                          from = day after the kv cursor
                                    rg_last_date, to = *yesterday* (the
                                    day's edition is generated in the
                                    Ankara morning; fetching before that
                                    follows the homepage redirect exactly
                                    like a no-edition day, so sync never
                                    claims today)
    scope=mevzuat                   which items to keep: mevzuat = the
                                    executive-section items (default;
                                    İLÂN announcement files dropped), all
                                    = everything. The scope travels in
                                    task params, so widening it later
                                    re-fetches automatically.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "API_BASE",
    "CURSOR_KEY",
    "build_source",
    "item_url",
    "start_tasks",
]

API_BASE = "https://www.resmigazete.gov.tr"
CURSOR_KEY = "rg_last_date"


def item_url(date_iso: str, mukerrer: int, seq: int, ext: str) -> str:
    """Canonical, rebuildable address of one item file (probed shape:
    ``/eskiler/2026/09/20260926-2.htm``, mükerrer items carry ``M{k}``)."""
    ymd = date_iso.replace("-", "")
    mark = f"M{mukerrer}" if mukerrer > 0 else ""
    return f"{API_BASE}/eskiler/{ymd[:4]}/{ymd[4:6]}/{ymd}{mark}-{seq}.{ext}"


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country tur --source resmigazete window=2026-09-21:2026-09-26\n"
        "  python cli.py collect --country tur --source resmigazete sync=1\n"
        "  python cli.py collect --country tur --source resmigazete window=2026-09-21:2026-09-26 scope=all\n"
        "  python cli.py status --country tur --source resmigazete"
    )


def _parse_date(raw: str, label: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None


def _parse_scope(raw: str) -> str:
    scope = raw.strip().lower()
    if scope not in ("mevzuat", "all"):
        raise _fail(f"scope must be mevzuat or all (got {raw!r})")
    return scope


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")
    scope = _parse_scope(str(params.get("scope", "mevzuat")))

    if params.get("window"):
        window = str(params["window"])
        from_str, sep, to_str = window.partition(":")
        if not sep or not from_str or not to_str:
            raise _fail(f"window must look like FROM:TO (got {window!r})")
        from_date = _parse_date(from_str.strip(), "window FROM")
        to_date = _parse_date(to_str.strip(), "window TO")
        if from_date > to_date:
            raise _fail(f"window start {from_date} is after its end {to_date}")
    elif is_sync:
        kv = params.get("_kv", {})
        cursor = kv.get(CURSOR_KEY)
        if not cursor:
            raise _fail("sync=1 needs a previous sweep; run an initial window=… first")
        from_date = date.fromisoformat(str(cursor)) + timedelta(days=1)
        # Never claim *today*: its edition is generated in the Ankara morning,
        # and a pre-publication fetch follows the homepage redirect exactly
        # like a no-edition day.
        to_date = datetime.now(UTC).date() - timedelta(days=1)
        if from_date > to_date:
            return []  # already in sync — nothing due
    else:
        raise _fail("give window=FROM:TO or sync=1")

    seeds: list[TaskSeed] = []
    day = from_date
    while day <= to_date:
        seeds.append(
            TaskSeed(
                type="rg_day",
                params={"date": day.isoformat(), "mukerrer": 0, "scope": scope},
            )
        )
        day += timedelta(days=1)
    return seeds


def build_source() -> SourceDefinition:
    from adapters.tur.sources.resmigazete.day import RgDayHandler
    from adapters.tur.sources.resmigazete.item import RgItemHandler

    return SourceDefinition(
        name="resmigazete",
        start_tasks=start_tasks,
        task_types={
            "rg_day": RgDayHandler(),
            "rg_item": RgItemHandler(),
        },
        parallel_safe=True,  # stateless GETs, no cookies (probed 2026-09-27)
    )
