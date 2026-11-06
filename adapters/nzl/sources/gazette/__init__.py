"""The gazette source: task-type registry, seed generation, shared helpers.

New Zealand Gazette (Te Kāhiti o Aotearoa) — the official government
gazette, published since 1841 by the Gazette Office at the Department of
Internal Affairs. Collected from the DigitalNZ aggregation API
(api.digitalnz.org/v3), where the office publishes notice metadata and
full text as the "New Zealand Gazette" collection. The gazette.govt.nz
site itself is Incapsula-walled and its robots.txt disallows both
``/home/search`` and ``*/pdf`` (probed 2026-10-11), so the sanctioned
machine channel is the aggregation API — anonymous (no key), collection
filtered, date-addressed per calendar day, every record carrying the
notice's full text.

Flat document path: zero domain tables — one notice is one publication
event and one document; ``documents`` is the whole ledger. Coverage
starts 2000 (1999 answers zero records; probed 2026-10-11).

Task types (each = one module with ``build_request`` + ``parse``):

===============  =====================================================
type             what one task does
===============  =====================================================
gazette_day      one calendar day, one request (per_page=100 + the
                 collection facet): up to 100 notices → parsed directly;
                 more than 100 → the facet block names the day's notice
                 types and the task spawns one gazette_slice per type
                 name (probed 2026-10-12: the API's offset pagination is
                 unreliable across pages of one day — rotating views,
                 22% duplicate rows on a 350-notice day — so multi-page
                 days are never paginated; they are *sliced* by the
                 collection facet, whose single-page slices are complete
                 by construction. Slicing reproduced the probe day
                 exactly: 24 slices, sum 350 = union 350 = total.)
gazette_slice    one (day × collection-name) slice, one request: the
                 full subset of that day's notices of one type; single
                 page (all probed slices ≤ 100); a slice answering more
                 than 100 is an unexplained shape and dies loudly
===============  =====================================================

Params (key=value on the CLI)::

    window=2026-10-05:2026-10-09   closed date range (required, or
                                    sync=1, or repair_days=…)
    sync=1                          from = day after the kv cursor
                                    gazette_last_date, to = *two days
                                    before now* — DigitalNZ's syndication
                                    lag is unpublished, and a day fetched
                                    before its notices arrive would record
                                    a false empty and advance the cursor
                                    past them permanently; two days is the
                                    conservative buffer (the probed Friday
                                    notices were visible two days later)
    repair_days=2000-03-15,2000-03-16
                                    spawn gazette_slice tasks for the
                                    named days over the full collection
                                    vocabulary — the surgical repair /
                                    vocabulary-extension entry: existing
                                    done slices are deduped by identity,
                                    so only never-fetched (or newly named)
                                    slices actually fetch
    signal=1                        stamp every seed with the current UTC
                                    timestamp — re-enqueue reopens the done
                                    day tasks (same identity, newer
                                    signal), i.e. the re-sweep entry for a
                                    window suspected of missing records
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "API_BASE",
    "COLLECTION",
    "COLLECTION_NAMES",
    "CURSOR_KEY",
    "NOTICE_TYPE_NAMES",
    "PAGE_SIZE",
    "PRIMARY_COLLECTION_FACET",
    "build_source",
    "parse_notice_number",
    "start_tasks",
]

API_BASE = "https://api.digitalnz.org/v3"
#: The DigitalNZ collection holding every gazette notice (probed total
#: 207,296 records on 2026-10-11).
COLLECTION = "New Zealand Gazette"
PAGE_SIZE = 100  # server-enforced per_page cap (probed: >100 → HTTP 400)
#: The facet bucket that mirrors the whole filter (facet value == total).
#: Note the facet's own label — "The New Zealand Gazette" — differs from
#: the filter value; slicing by it would re-fetch the whole day and hit
#: the broken pagination, so it is excluded from slice fan-out.
PRIMARY_COLLECTION_FACET = "The New Zealand Gazette"

CURSOR_KEY = "gazette_last_date"

#: Gazette notice-type codes (the middle segment of a notice number like
#: ``2026-sl5906``) -> human names as shown on gazette.govt.nz (homepage
#: notice-type lists, probed 2026-10-11). Used for the meta type-name
#: lookup; unknown codes keep their code and the raw record always
#: carries the truth.
NOTICE_TYPE_NAMES: dict[str, str] = {
    # Commercial
    "aw": "Applications for Winding up/Liquidations",
    "aa": "Appointment/Release of Administrators",
    "al": "Appointment/Release of Liquidators",
    "ar": "Appointment/Release of Receivers & Managers",
    "ba": "Bankruptcies",
    "cb": "Cessation of Business in New Zealand",
    "ct": "Charitable Trusts",
    "fs": "Friendly Societies and Credit Unions",
    "gn": "General Notices",
    "is": "Incorporated Societies",
    "lt": "Land Transfers/Joint Family Homes",
    "md": "Meetings/Last Dates for Debts & Claims",
    "ot": "Other",
    "pn": "Partnerships",
    "ds": "Removals",
    # Government
    "au": "Authorities/Other Agencies of State",
    "go": "Departmental",
    "gs": "General Section",
    "ln": "Land Notices",
    "ps": "Parliamentary",
    "sl": "Secondary Legislation",
    "vr": "Vice Regal",
}

#: The collection-name vocabulary used to slice busy days: the site's
#: notice-type list plus the archive-era names observed in the corpus
#: (probed from January-2001 records, 2026-10-12 — the old decades use
#: names the modern homepage no longer shows). The per-day facet block
#: contributes its own names on top; anything outside both surfaces is
#: caught by the per-year count audit.
COLLECTION_NAMES: tuple[str, ...] = tuple(
    sorted(set(NOTICE_TYPE_NAMES.values()) | {
        "Customs",
        "Private Bills",
        "Regulation Summary",
    })
)

#: ``YYYY-<type><serial>`` — notice numbers like ``2026-sl5906`` or
#: ``2009-al4199``; the type letters are absent on the delegated-
#: legislation numbers of the Legislation Act 2012 era (``2019-197``,
#: probed 2026-10-12), so the segment is optional.
_NOTICE_NUMBER_RE = re.compile(r"^(\d{4})-([a-z]*)(\d+)$")


def parse_notice_number(raw: str) -> tuple[str, str, str] | None:
    """Split a notice number into (year, type_code, serial); None if alien."""
    match = _NOTICE_NUMBER_RE.match(raw.strip())
    if match is None:
        return None
    return match.group(1), match.group(2), match.group(3)


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country nzl --source gazette window=2026-10-05:2026-10-09\n"
        "  python cli.py collect --country nzl --source gazette sync=1\n"
        "  python cli.py collect --country nzl --source gazette window=2000-01-01:2004-12-31 --delay 2:4\n"
        "  python cli.py collect --country nzl --source gazette window=2026-10-05:2026-10-09 signal=1\n"
        "  python cli.py collect --country nzl --source gazette repair_days=2000-03-15,2000-03-16\n"
        "  python cli.py status --country nzl --source gazette"
    )


def _parse_date(raw: str, label: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    from adapters.nzl.sources.gazette.slice import SLICE_TYPE

    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")
    # Re-sweep stamp: a newer signal reopens already-done day tasks on
    # enqueue (same identity, fresh signal) — never part of task identity.
    signal = (
        datetime.now(UTC).replace(microsecond=0).isoformat()
        if str(params.get("signal", "")).strip() in ("1", "true", "yes")
        else None
    )

    dates: list[date]
    if params.get("repair_days"):
        raw = str(params["repair_days"])
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if not parts:
            raise _fail("repair_days must be a comma-separated list of ISO dates")
        dates = [_parse_date(p, "repair_days entry") for p in parts]
        seeds: list[TaskSeed] = []
        for day in dates:
            for name in COLLECTION_NAMES:
                seeds.append(
                    TaskSeed(
                        type=SLICE_TYPE,
                        params={"date": day.isoformat(), "collection": name},
                        signal=signal,
                    )
                )
        return seeds

    if params.get("window"):
        window = str(params["window"])
        from_str, sep, to_str = window.partition(":")
        if not sep or not from_str or not to_str:
            raise _fail(f"window must look like FROM:TO (got {window!r})")
        from_date = _parse_date(from_str.strip(), "window FROM")
        to_date = _parse_date(to_str.strip(), "window TO")
        if from_date > to_date:
            raise _fail(f"window start {from_date} is after its end {to_date}")
        dates = []
        day = from_date
        while day <= to_date:
            dates.append(day)
            day += timedelta(days=1)
    elif is_sync:
        kv = params.get("_kv", {})
        cursor = kv.get(CURSOR_KEY)
        if not cursor:
            raise _fail("sync=1 needs a previous sweep; run an initial window=… first")
        from_date = date.fromisoformat(str(cursor)) + timedelta(days=1)
        # Never claim recent days: the aggregation's syndication lag is
        # unpublished (probed Friday notices surfaced two days later), and
        # a false empty would advance the cursor past real notices for
        # good. Two full days of buffer.
        to_date = datetime.now(UTC).date() - timedelta(days=2)
        if from_date > to_date:
            return []  # already in sync — nothing due
        dates = []
        day = from_date
        while day <= to_date:
            dates.append(day)
            day += timedelta(days=1)
    else:
        raise _fail("give window=FROM:TO or sync=1 (or repair_days=…)")

    return [
        TaskSeed(type="gazette_day", params={"date": day.isoformat(), "w": "2"}, signal=signal)
        for day in dates
    ]


def build_source() -> SourceDefinition:
    from adapters.nzl.sources.gazette.day import GazetteDayHandler
    from adapters.nzl.sources.gazette.slice import GazetteSliceHandler

    return SourceDefinition(
        name="gazette",
        start_tasks=start_tasks,
        task_types={
            "gazette_day": GazetteDayHandler(),
            "gazette_slice": GazetteSliceHandler(),
        },
        domain_schema="",  # flat gazette path: documents are the whole ledger
        domain_keys={},
        # DigitalNZ's anonymous rate limits are unpublished; stay single
        # worker with polite --delay until a key (and published limits)
        # justify revisiting.
        parallel_safe=False,
    )
