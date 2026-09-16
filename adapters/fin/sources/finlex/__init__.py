"""FIN country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The finlex source is the
**statute gazette layer** (säädöskokoelma, Finlands författningssamling) of
Finlex — the Ministry of Justice's official statute database — read from the
free open-data REST API on opendata.finlex.fi (no key, no session, no
browser; every request must carry a User-Agent, which the framework's HTTP
transport sets by default). Probed 2026-09-13; burst requests without
connection reuse get the connection dropped (no 429), hence the recommended
``--delay 0.5:1.5``.

Bilingual model (second multilingual source in this repo, CHE-fedlex
conventions): one statute (work) → two language expressions ``fin@`` and
``swe@``, equal legal force, each its own documents row hashing its own
manifestation URL. The work is the persistent cross-document entity and gets
the ``statutes`` domain table; ``entity_ref`` carries
``statutes:{year}/{number}``. Historical decades have single-language
statutes — the manifestations the list returns are the truth, nothing is
assumed.

Task types (each = build_request + parse; enumerators share enum.py):

===============  =====================================================
type             what one task does
===============  =====================================================
sd_day           seed: one date-issued day of the gazette — the list
                 endpoint answers the day's manifestation rows
                 (server-side ``dateIssued`` filter, JSON rows
                 ``{akn_uri, status}``, max 10 per page); every kept
                 row spawns one sd_fetch; a full page chains the next
                 page of the same day; the *last* page advances the
                 ``finlex_sd_last_date`` cursor and chains the **next
                 day** (up to the sweep's ``to_date``) — days are
                 discovered serially, so the cursor is monotone even
                 when one day spans several pages. An empty day is a
                 legal empty — still fully consumed.
sd_year_page     seed: backfill enumeration of one gazette year
                 (``startYear=endYear`` + ``sortBy=number``), chained
                 pages like sd_day but no date cursor — backfill never
                 disturbs the sync watermark.
sd_fix           seed (optional, off by default): source change feed —
                 ``publishedSince={watermark}`` returns rows added or
                 regenerated since the stamp; spawns sd_fetch carrying
                 the row status as its reopen signal; the chain's last
                 page sets the ``finlex_sd_fix_watermark`` to the
                 sweep's start stamp (CHE sr_walk mark_ts pattern).
sd_fetch         one manifestation: GET the full Akoma Ntoso XML
                 (metadata + full text in one response); upserts the
                 ``statutes`` work row (fin-language parse writes the
                 work fields, swe-language parse writes title_sv);
                 registers one document per language variant and
                 stores the response bytes verbatim.
===============  =====================================================

Params (key=value on the CLI)::

    window=2025-02-13:2025-02-15  date-issued window, one sd_day per day
    sync=1                         from = day after the kv cursor
                                   finlex_sd_last_date, to = yesterday
    year=1917 or year=1734:1916    backfill enumeration, one
                                   sd_year_page per year
    fix=1                          change feed from the kv watermark
                                   finlex_sd_fix_watermark
    langs=fin                  language scope (default: Finnish only;
                               swe twin back-fills anytime via
                               langs=fin,swe — new task identity)
    types=act,decree               native typeStatute filter, travels to
                                   the API (server-side); default all
    max_items=N                    spawn cap (enumeration continues, only
                                   deep fetches are capped — CHE
                                   max_works semantics; guard-rail for
                                   trials, the cursor still advances)
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "API_BASE",
    "CURSOR_KEY",
    "DAY_PAGE_LIMIT",
    "FIX_CURSOR_KEY",
    "STATUTE_LANGS",
    "build_source",
    "start_tasks",
]

API_BASE = "https://opendata.finlex.fi/finlex/avoindata/v1"

CURSOR_KEY = "finlex_sd_last_date"
FIX_CURSOR_KEY = "finlex_sd_fix_watermark"

#: Server-enforced page size: limit > 10 answers HTTP 400 ("limit must be
#: less than or equal to 10"), probed 2026-09-13.
DAY_PAGE_LIMIT = 10

#: Language tails a manifestation URI can carry on the statute layer.
STATUTE_LANGS = ("fin", "swe")


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country fin --source finlex window=2025-02-13:2025-02-15\n"
        "  python cli.py collect --country fin --source finlex sync=1\n"
        "  python cli.py collect --country fin --source finlex year=1917 max_items=4\n"
        "  python cli.py collect --country fin --source finlex year=1734:1916\n"
        "  python cli.py collect --country fin --source finlex fix=1\n"
        "  python cli.py status --country fin --source finlex"
    )


def _parse_date(raw: str, label: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None


def _parse_langs(raw: str) -> str:
    langs = ",".join(p.strip() for p in raw.split(",") if p.strip())
    unknown = [p for p in langs.split(",") if p and p not in STATUTE_LANGS]
    if unknown:
        raise _fail(f"langs must be a comma list of {list(STATUTE_LANGS)} (got {raw!r})")
    return langs


def _positive_int(params: dict[str, Any], key: str) -> str | None:
    raw = str(params.get(key, "")).strip()
    if not raw:
        return None
    if not raw.isdigit() or int(raw) < 1:
        raise _fail(f"{key} must be a positive integer (got {raw!r})")
    return raw


def _mode(params: dict[str, Any]) -> dict[str, str]:
    """Sweep options flowing down the chains (part of task identity —
    widening them later means new task ids, never a rebuild).

    Language scope defaults to Finnish only (user ruling 2026-09-14:
    one language suffices, the Swedish twin can always be back-filled by
    re-running with langs=fin,swe — new task identity, zero rebuild).
    """
    return {
        "langs": _parse_langs(str(params.get("langs", "fin"))),
        "types": ",".join(
            p.strip() for p in str(params.get("types", "")).split(",") if p.strip()
        ),
    }


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    mode = _mode(params)
    max_items = _positive_int(params, "max_items")
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")
    is_fix = str(params.get("fix", "")).strip() in ("1", "true", "yes")
    year_span = str(params.get("year", "")).strip()
    window = str(params.get("window", "")).strip()

    entries = [flag for flag in (window, is_sync, year_span, is_fix) if flag]
    if len(entries) != 1:
        raise _fail(
            "give exactly one entry: window=FROM:TO | sync=1 | year=Y[:Z] | fix=1"
        )

    seeds: list[TaskSeed] = []

    if window:
        from_str, sep, to_str = window.partition(":")
        if not sep or not from_str or not to_str:
            raise _fail(f"window must look like FROM:TO (got {window!r})")
        from_date = _parse_date(from_str.strip(), "window FROM")
        to_date = _parse_date(to_str.strip(), "window TO")
        if from_date > to_date:
            raise _fail(f"window start {from_date} is after its end {to_date}")
        seed_params: dict[str, Any] = {**mode, "date": from_date.isoformat(),
                                       "to_date": to_date.isoformat()}
        if max_items:
            seed_params["max_items"] = max_items
        seeds.append(TaskSeed(type="sd_day", params=seed_params))
        return seeds

    if is_sync:
        kv = params.get("_kv", {})
        cursor = kv.get(CURSOR_KEY)
        if not cursor:
            raise _fail("sync=1 needs a previous sweep; run window=… or year=… first")
        from_date = date.fromisoformat(str(cursor)) + timedelta(days=1)
        # Never claim *today*: a same-day statute can still enter the open
        # data later in the day, which would answer the same empty array as
        # a genuine no-issue day (ESP/FRA late-publication precaution).
        to_date = datetime.now(UTC).date() - timedelta(days=1)
        if from_date > to_date:
            return []  # already in sync
        seed_params_s: dict[str, Any] = {**mode, "date": from_date.isoformat(),
                                         "to_date": to_date.isoformat()}
        seeds.append(TaskSeed(type="sd_day", params=seed_params_s))
        return seeds

    if year_span:
        years: list[str] = []
        from_str, sep, to_str = year_span.partition(":")
        try:
            start_year = int(from_str)
            end_year = int(to_str) if sep else start_year
        except ValueError:
            raise _fail(f"year must look like Y or Y:Z with integer years (got {year_span!r})") from None
        if start_year > end_year:
            raise _fail(f"year start {start_year} is after its end {end_year}")
        years = [str(y) for y in range(start_year, end_year + 1)]
        for year in years:
            seed_params_y: dict[str, Any] = {**mode, "year": year}
            if max_items:
                seed_params_y["max_items"] = max_items
            seeds.append(TaskSeed(type="sd_year_page", params=seed_params_y))
        return seeds

    # fix=1: change feed from the watermark (explicit since= override).
    since = str(params.get("since", "")).strip()
    if not since:
        kv = params.get("_kv", {})
        since = str(kv.get(FIX_CURSOR_KEY) or "")
        if not since:
            raise _fail(
                "fix=1 needs a previous sweep (or give since=ISO_DATETIME); the "
                "watermark is set by a completed fix sweep"
            )
    try:
        parsed_since = datetime.fromisoformat(since)
    except ValueError:
        raise _fail(f"since must be an ISO datetime (got {since!r})") from None
    if parsed_since.tzinfo is None:
        # The API rejects timezone-less timestamps with HTTP 400 (probed
        # 2026-09-14: "2026-01-01T00:00:00" → 400, "…Z" → 200).
        raise _fail(f"since must carry a timezone (e.g. {since}Z, got {since!r})")
    mark_ts = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    seed_params_f: dict[str, Any] = {**mode, "since": since, "mark_ts": mark_ts}
    if max_items:
        seed_params_f["max_items"] = max_items
    seeds.append(TaskSeed(type="sd_fix", params=seed_params_f))
    return seeds


#: One domain table (user ruling Q1 2026-09-13): a statute (work) spans two
#: language documents, and Finlex addresses both layers — gazette originals
#: and (future) consolidated texts — with the same unique (year, number), so
#: one table carries the work with room for the consolidated layer's fields
#: to be ADDED by the later subtask (domain tables are add-only).
DOMAIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS statutes (
    year TEXT NOT NULL,
    number TEXT NOT NULL,
    type_code TEXT,
    type_label TEXT,
    category_code TEXT,
    category_label TEXT,
    date_issued TEXT,
    date_published TEXT,
    eli TEXT,
    title_fi TEXT,
    title_sv TEXT,
    authority TEXT,
    list_status TEXT,
    date_produced TEXT,
    PRIMARY KEY (year, number)
);
"""


def build_source() -> SourceDefinition:
    from adapters.fin.sources.finlex.enum import (
        SdDayHandler,
        SdFixHandler,
        SdYearPageHandler,
    )
    from adapters.fin.sources.finlex.fetch import SdFetchHandler

    return SourceDefinition(
        name="finlex",
        start_tasks=start_tasks,
        task_types={
            "sd_day": SdDayHandler(),
            "sd_year_page": SdYearPageHandler(),
            "sd_fix": SdFixHandler(),
            "sd_fetch": SdFetchHandler(),
        },
        domain_schema=DOMAIN_SCHEMA,
        domain_tables=("statutes",),
        domain_keys={"statutes": ("year", "number")},
    )
