"""The kanpo source: task-type registry and seed generation.

官報 (Kanpo), the Japanese government gazette, published every weekday
8:30 JST (special extras may follow in the afternoon) on
www.kanpo.go.jp. Laws (法律) and cabinet orders (政令) appear only in the
号外 (extra) edition; ministerial ordinances and notices appear in both
本紙 (main) and 号外 — so all of h/g/t must be collected for a complete
series. Flat document path: zero domain tables, ``documents`` is the whole
ledger (see docs/countries/jpn/kanpo-zh.md).

The portal is plain static HTML + directly addressable PDFs — no API, no
session, no key (probed 2026-09-07). Two addressing regimes meet here:

- **Fresh** (publication date within ~88 days): the daily whole-index page
  ``/{YYYYMMDD}/{YYYYMMDD}.fullcontents.html`` lists every issue's entries
  — one request per day covers everything.
- **Archive** (older): the same page under ``/old/``, but only back to
  2024-01-01; deeper history is enumerated per month via
  ``/old/{YYYYMM}.html`` → per-issue TOC pages (``…0000f.html``), which go
  back to the online archive's start on 2003-07-15.

Task types (each = one module with ``build_request`` + ``parse``):

===============  =====================================================
type             what one task does
===============  =====================================================
kanpo_day        one gazette day: GET the date-addressed whole-index
                 page (namespace decided at seed time by date age);
                 every in-scope entry yields one kanpo_doc. Weekends /
                 holidays answer 404 with a fixed tiny error page —
                 declared as data (``accept_not_found``), verified
                 against that known shape, recorded as an explained
                 empty. Empty or not, a fully consumed day moves the
                 ``kanpo_last_date`` cursor.
kanpo_month      one archive month: GET ``/old/{YYYYMM}.html``, harvest
                 the per-issue TOC links (date + issue code + number all
                 derived from the href); each in-scope issue yields one
                 kanpo_issue. A month beyond the archive answers 404 —
                 declared as data (the archive starts 2003-07-15).
kanpo_issue      one issue's TOC page: same section/entry walk as the
                 day page. Pre-2025-04-01 archive TOCs carry *linkless*
                 entries for content the portal never retained — only
                 linked entries are collectable; linkless ones are
                 counted, not fetched.
kanpo_doc        one entry: GET the entry PDF (address constructed from
                 the TOC link — ``{issue}/pdf/{base}.pdf``; the wrapper
                 page and its iframe are pure UI). Registers the
                 document and stores the bytes verbatim.
===============  =====================================================

Params (key=value on the CLI)::

    window=2026-09-01:2026-09-06  closed date range (required, or
                                   sync=1, or months=…)
    sync=1                           from = day after the kv cursor
                                     kanpo_last_date, to = *yesterday*
                                     (the gazette is published 8:30 JST
                                     and a special extra may follow in
                                     the afternoon — a day is only
                                     final once it is over)
    months=2003-07:2023-12          archive backfill entry: per-month
                                     enumeration via the month pages
    types=h,g,t                      issue letters to keep (default
                                     h,g,t = 本紙/号外/特別号外; c =
                                     政府調達 procurement is excluded
                                     by default, unknown letters are
                                     skipped)
    sections=law                     section scope: ``law`` = the
                                     法令等 family (法律/政令/府省庁令/
                                     規則/訓令/条約 — the set the online
                                     archive retains for *all* eras,
                                     probed 2026-09-07), ``all`` = every
                                     section, or a comma list of literal
                                     section names (e.g. ``法規的告示``).
                                     Scope travels in the day-task
                                     identity, so widening it later
                                     re-enumerates automatically.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "CURSOR_KEY",
    "FRESH_ROOT_DAYS",
    "LAW_SECTIONS",
    "SITE",
    "USER_AGENT",
    "build_source",
    "namespace_for",
    "start_tasks",
]

SITE = "https://www.kanpo.go.jp"

#: Polite-crawl identity (user decision 2026-09-08): honest research UA
#: pointing at the open-source repo — the portal's robots.txt closes the
#: dated trees for generic agents while its content licence (PDL 1.0)
#: allows reuse; slow, small and identifiable is the honest posture.
USER_AGENT = (
    "GPI-Research/1.0 (academic policy-data collection; "
    "https://github.com/stupidtian/globalpolicyinfra)"
)

CURSOR_KEY = "kanpo_last_date"

#: A date this fresh is served from the site root; older dates live only
#: under /old/. The site keeps ~89 days at the root (probed 2026-09-07:
#: day-89 present in both, day-90 root 404) — 88 leaves a day of margin.
FRESH_ROOT_DAYS = 88

#: The 法令等 family — exactly what the portal's online archive retains
#: for pre-2025-04-01 issues (官方「公開対象の記事について」, 2026-09-07),
#: so the default scope yields a series uniform from 2003-07-15 to today.
LAW_SECTIONS = frozenset(
    {
        "法律",
        "政令",
        "省令",
        "府令",
        "庁令",
        "内閣官房令",
        "内閣府令",
        "デジタル庁令",
        "内閣総理府令",
        "規則",
        "訓令",
        "条約",
        "詔書",
        "日本国憲法改正",
    }
)


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country jpn --source kanpo window=2026-09-01:2026-09-06\n"
        "  python cli.py collect --country jpn --source kanpo sync=1\n"
        "  python cli.py collect --country jpn --source kanpo months=2003-07:2003-12\n"
        "  python cli.py collect --country jpn --source kanpo window=2026-09-01:2026-09-06 sections=all\n"
        "  python cli.py status --country jpn --source kanpo"
    )


def _parse_date(raw: str, label: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None


def _parse_month(raw: str, label: str) -> tuple[int, int]:
    try:
        year, month = raw.split("-")
        ym = (int(year), int(month))
    except (ValueError, TypeError):
        raise _fail(f"{label} must look like YYYY-MM (got {raw!r})") from None
    if not 1 <= ym[1] <= 12:
        raise _fail(f"{label} month must be 01-12 (got {raw!r})")
    return ym


def parse_types(raw: str) -> str:
    """Validate the issue-letter list (comma separated, single letters)."""
    letters = [p.strip() for p in raw.split(",") if p.strip()]
    if not letters or any(not (len(l) == 1 and "a" <= l <= "z") for l in letters):
        raise _fail(f"types must be comma-separated single letters, e.g. h,g,t (got {raw!r})")
    return ",".join(letters)


def parse_sections(raw: str) -> str:
    """Validate the section scope: ``law`` | ``all`` | literal names."""
    value = raw.strip()
    if not value:
        raise _fail("sections must be law, all, or a comma list of section names")
    return value


def namespace_for(day: date, today: date) -> str:
    """Which URL namespace serves ``day``: the transient site root keeps
    the newest ~89 days; the permanent ``/old/`` archive everything."""
    return "root" if day >= today - timedelta(days=FRESH_ROOT_DAYS) else "old"


def _months_between(from_ym: tuple[int, int], to_ym: tuple[int, int]) -> list[str]:
    months: list[str] = []
    year, month = from_ym
    while (year, month) <= to_ym:
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return months


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    types = parse_types(str(params.get("types", "h,g,t")))
    sections = parse_sections(str(params.get("sections", "law")))
    injected = params.get("_today")  # test seam; the engine never passes it
    today = injected if isinstance(injected, date) else datetime.now(UTC).date()

    modes = [m for m in ("window", "sync", "months") if params.get(m)]
    if len(modes) != 1:
        raise _fail("give exactly one of window=FROM:TO, sync=1 or months=YYYY-MM:YYYY-MM")

    seeds: list[TaskSeed] = []
    if params.get("window"):
        window = str(params["window"])
        from_str, sep, to_str = window.partition(":")
        if not sep or not from_str or not to_str:
            raise _fail(f"window must look like FROM:TO (got {window!r})")
        from_date = _parse_date(from_str.strip(), "window FROM")
        to_date = _parse_date(to_str.strip(), "window TO")
        if from_date > to_date:
            raise _fail(f"window start {from_date} is after its end {to_date}")
        day = from_date
        while day <= to_date:
            seeds.append(
                TaskSeed(
                    type="kanpo_day",
                    params={
                        "date": day.isoformat(),
                        "ns": namespace_for(day, today),
                        "types": types,
                        "sections": sections,
                    },
                )
            )
            day += timedelta(days=1)
    elif params.get("months"):
        span = str(params["months"])
        from_str, sep, to_str = span.partition(":")
        if not sep or not from_str or not to_str:
            raise _fail(f"months must look like YYYY-MM:YYYY-MM (got {span!r})")
        months = _months_between(
            _parse_month(from_str.strip(), "months FROM"),
            _parse_month(to_str.strip(), "months TO"),
        )
        for ym in months:
            seeds.append(
                TaskSeed(
                    type="kanpo_month",
                    params={"ym": ym, "types": types, "sections": sections},
                )
            )
    else:
        is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")
        if not is_sync:
            raise _fail("give window=FROM:TO, sync=1 or months=YYYY-MM:YYYY-MM")
        kv = params.get("_kv", {})
        cursor = kv.get(CURSOR_KEY)
        if not cursor:
            raise _fail("sync=1 needs a previous sweep; run an initial window=… first")
        from_date = date.fromisoformat(cursor) + timedelta(days=1)
        # Never claim *today*: the gazette is published 8:30 JST and a
        # special extra may be added in the afternoon — a day is only
        # final once it is over.
        to_date = today - timedelta(days=1)
        if from_date > to_date:
            return []  # already in sync — nothing due
        day = from_date
        while day <= to_date:
            seeds.append(
                TaskSeed(
                    type="kanpo_day",
                    params={
                        "date": day.isoformat(),
                        "ns": namespace_for(day, today),
                        "types": types,
                        "sections": sections,
                    },
                )
            )
            day += timedelta(days=1)
    return seeds


def build_source() -> SourceDefinition:
    from adapters.jpn.sources.kanpo.document import KanpoDocHandler
    from adapters.jpn.sources.kanpo.enumerate import (
        KanpoDayHandler,
        KanpoIssueHandler,
        KanpoMonthHandler,
    )

    return SourceDefinition(
        name="kanpo",
        start_tasks=start_tasks,
        task_types={
            "kanpo_day": KanpoDayHandler(),
            "kanpo_month": KanpoMonthHandler(),
            "kanpo_issue": KanpoIssueHandler(),
            "kanpo_doc": KanpoDocHandler(),
        },
    )
