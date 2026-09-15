"""The ris source: task-type registry and seed generation.

Bundesgesetzblatt (BGBl), the Austrian federal gazette, collected from the
Bundeskanzleramt's OGD RIS API (see docs/countries/aut/ris-zh.md). Flat
document path: zero domain tables, ``documents`` is the whole ledger — one
gazette entry is one document, registered by the window task from the
search response's structured metadata (the entry XML itself carries no
metadata block), with the XML full-text file attached by the file task.

The API serves two non-overlapping eras on the same ``Bundesrecht``
endpoint, selected by application (probed 2026-09-13/14, samples in the
task archive):

- ``BgblAuth`` — authentic electronic layer, 2004–now; window params
  ``Kundmachung.Von``/``Kundmachung.Bis``;
- ``BgblPdf`` — scan era, 1945–2003, with OCR full-text XML; window
  params ``Kundgemacht.Von``/``Kundgemacht.Bis`` (note the different
  param name).

Entries may only appear with a publication date up to *yesterday*: today's
issue is generated during the day, and a pre-publication fetch is
indistinguishable from an empty window — so every window's end is capped
at yesterday and ``sync`` never claims today (same rule as ESP/BOE).

Params (key=value on the CLI)::

    date=YYYY-MM-DD   one day (required, or month=/year=/sync=1)
    month=YYYY-MM     one calendar month (the recommended slicing unit)
    year=YYYY         one year, internally sliced into month windows
    sync=1            from = day after the kv cursor ``ris_last_publication_date``,
                      to = *yesterday*, sliced into month windows
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "API_BASE",
    "APPL_AUTH",
    "APPL_PDF",
    "CURSOR_KEY",
    "FILE_BASE",
    "application_for_year",
    "build_source",
    "start_tasks",
    "window_query",
]

API_BASE = "https://data.bka.gv.at/ris/api/v2.6"
FILE_BASE = "https://ogd.ris.bka.gv.at/Dokumente"

#: The two gazette eras (one ``Bundesrecht`` endpoint, two applications).
APPL_AUTH = "BgblAuth"
APPL_PDF = "BgblPdf"

#: Era boundary: the authentic electronic gazette starts with 2004.
AUTH_FIRST_YEAR = 2004

CURSOR_KEY = "ris_last_publication_date"

#: Page size in the API's own vocabulary (Ten/Twenty/Fifty/OneHundred).
PAGE_SIZE = "OneHundred"


def application_for_year(year: int) -> str:
    """Era selection: windows are month-aligned so they never straddle years."""
    return APPL_AUTH if year >= AUTH_FIRST_YEAR else APPL_PDF


def window_query(application: str, von: str, bis: str) -> dict[str, str]:
    """The window parameter block for one application (names differ!).
    Dates are ISO strings — the wire format of ``Kundmachung.Von`` etc."""
    if application == APPL_AUTH:
        von_key, bis_key = "Kundmachung.Von", "Kundmachung.Bis"
    elif application == APPL_PDF:
        von_key, bis_key = "Kundgemacht.Von", "Kundgemacht.Bis"
    else:
        raise ValueError(f"unknown RIS application {application!r}")
    return {von_key: von, bis_key: bis}


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country aut --source ris date=2026-01-05\n"
        "  python cli.py collect --country aut --source ris month=2026-01\n"
        "  python cli.py collect --country aut --source ris year=2025\n"
        "  python cli.py collect --country aut --source ris month=2003-06\n"
        "  python cli.py collect --country aut --source ris sync=1\n"
        "  python cli.py status --country aut --source ris"
    )


def _parse_ymd(raw: str, label: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None


def _parse_month(raw: str, label: str) -> date:
    """``YYYY-MM`` -> first day of the month (strictly two-digit month;
    the stdlib's ``%m`` would silently accept ``2026-1``)."""
    parts = raw.split("-")
    if (
        len(parts) != 2
        or len(parts[0]) != 4
        or not parts[0].isdigit()
        or len(parts[1]) != 2
        or not parts[1].isdigit()
    ):
        raise _fail(f"{label} must be a month YYYY-MM (got {raw!r})") from None
    return date(int(parts[0]), int(parts[1]), 1)


def _month_end(day: date) -> date:
    """Last day of ``day``'s month."""
    nxt = day.replace(day=28) + timedelta(days=4)
    return nxt.replace(day=1) - timedelta(days=1)


def _month_windows(from_date: date, to_date: date) -> list[tuple[date, date]]:
    """Slice [from_date, to_date] into month-aligned closed windows."""
    windows: list[tuple[date, date]] = []
    start = from_date
    while start <= to_date:
        end = min(_month_end(start), to_date)
        windows.append((start, end))
        start = end + timedelta(days=1)
    return windows


def _yesterday() -> date:
    return datetime.now(UTC).date() - timedelta(days=1)


def _seed_window(von: date, bis: date) -> TaskSeed:
    application = application_for_year(von.year)
    return TaskSeed(
        type="bgbl_window",
        params={
            "applikation": application,
            "von": von.isoformat(),
            "bis": bis.isoformat(),
            "seitennummer": "1",
        },
    )


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    yesterday = _yesterday()
    given = [k for k in ("date", "month", "year", "sync") if params.get(k)]
    if len(given) > 1:
        raise _fail(f"give exactly one of date=/month=/year=/sync=1 (got {', '.join(given)})")

    if params.get("date"):
        day = _parse_ymd(str(params["date"]), "date")
        if day > yesterday:
            raise _fail(f"date={day} is in the future (the gazette day is only "
                        "complete after it has ended); give a date up to "
                        f"{yesterday.isoformat()}")
        return [_seed_window(day, day)]

    if params.get("month"):
        first = _parse_month(str(params["month"]), "month")
        last = min(_month_end(first), yesterday)
        if first > last:
            raise _fail(f"month={params['month']} has not started yet "
                        f"(today is {(yesterday + timedelta(days=1)).isoformat()})")
        return [_seed_window(first, last)]

    if params.get("year"):
        raw = str(params["year"])
        if not raw.isdigit() or len(raw) != 4:
            raise _fail(f"year must be YYYY (got {raw!r})")
        first = date(int(raw), 1, 1)
        last = min(date(int(raw), 12, 31), yesterday)
        if first > last:
            raise _fail(f"year={raw} has not started yet")
        if int(raw) < 1945:
            raise _fail(f"year={raw}: the scan era in this pack starts at 1945 "
                        "(BgblAlt, 1848–1940, is not collected)")
        return [_seed_window(von, bis) for von, bis in _month_windows(first, last)]

    if str(params.get("sync", "")).strip() in ("1", "true", "yes"):
        kv = params.get("_kv", {})
        cursor = kv.get(CURSOR_KEY)
        if not cursor:
            raise _fail("sync=1 needs a previous sweep; run an initial "
                        "date=/month=/year= window first")
        from_date = _parse_ymd(str(cursor), f"cursor {CURSOR_KEY}") + timedelta(days=1)
        if from_date > yesterday:
            return []  # already in sync — nothing due
        return [_seed_window(von, bis) for von, bis in _month_windows(from_date, yesterday)]

    raise _fail("give one of date=YYYY-MM-DD, month=YYYY-MM, year=YYYY or sync=1")


def build_source() -> SourceDefinition:
    from adapters.aut.sources.ris.file import BgblFileHandler
    from adapters.aut.sources.ris.window import BgblWindowHandler

    return SourceDefinition(
        name="ris",
        start_tasks=start_tasks,
        task_types={
            "bgbl_window": BgblWindowHandler(),
            "bgbl_file": BgblFileHandler(),
        },
    )
