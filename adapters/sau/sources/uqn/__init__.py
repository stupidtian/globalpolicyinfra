"""The uqn source: task-type registry and seed generation.

Umm al-Qura (جريدة أم القرى), the official gazette of Saudi Arabia, at
uqn.gov.sa — publisher: Ministry of Media (وزارة الإعلام). Item-level
collection covers the official section since the January 2026 site
rebuild; per-issue PDFs are collected for every date that yielded items
(see docs/countries/sau/uqn-zh.md). Flat document path: zero domain
tables, ``documents`` is the whole ledger.

Task types (each = one module with ``build_request`` + ``parse``):

=================  =====================================================
type               what one task does
=================  =====================================================
uqn_sitemap_month  one calendar month: GET the monthly sitemap; every
                   in-scope item URL (official-section decisions, plus
                   advertisements when ``sections`` asks for them)
                   yields one uqn_item. Sitemap files for months before
                   the last regen carry a frozen all-archive block —
                   duplicates across months are absorbed by task
                   identity, so the union-over-months design is safe.
                   A fully consumed month that has *ended* moves the
                   ``uqn_last_month`` cursor (the current month never
                   advances: it is re-walked on every sync).
uqn_item           one gazette entry: GET the item page, parse its
                   embedded JSON-LD (NewsArticle: native headline +
                   Gregorian publication date; BreadcrumbList: the
                   section that maps to doc_type) and store the page
                   HTML verbatim. Also seeds one uqn_issue for the
                   publication date.
uqn_issue          one calendar date: GET the digital-issue page and
                   extract the issue PDF part links. The page silently
                   falls back to the *latest* issue for date-less days,
                   so the date embedded in the PDF filename is checked
                   against the requested date — a mismatch is a
                   legitimate no-issue day, not an error.
uqn_issue_part     one issue PDF part: GET the cdn link and store the
                   PDF verbatim as its own document (an issue may
                   consist of several parts, and part numbering does
                   not necessarily start at 1 — observed: the 2026-10-09
                   issue lists only part 2).
=================  =====================================================

Params (key=value on the CLI)::

    window=2026-09:2026-10   closed month range (required, or sync=1)
    sync=1                   from = month after the kv cursor
                             uqn_last_month, to = the current month
                             (the current month is always re-walked so
                             late-listed items are picked up)
    sections=decisions       gazette sections to keep, comma separated
                             (default "decisions"; add "advertisements")
    refresh=1                re-walk: the refresh stamp rides in the
                             month task params, changing task identity —
                             downstream item tasks are done-skipped, so
                             the cost is one sitemap request per month
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "CURSOR_KEY",
    "NEW_ERA_FIRST_MONTH",
    "SITE",
    "build_source",
    "start_tasks",
]

SITE = "https://www.uqn.gov.sa"

#: Months before this carry no per-month item data (the pre-2026 sitemap
#: files hold a frozen all-archive snapshot, and old-era pages carry no
#: inline text — issue-PDF backfill of 2012–2025 is a separate project).
NEW_ERA_FIRST_MONTH = date(2026, 1, 1)

CURSOR_KEY = "uqn_last_month"

_VALID_SECTIONS = ("decisions", "advertisements")


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country sau --source uqn window=2026-09:2026-10\n"
        "  python cli.py collect --country sau --source uqn sync=1\n"
        "  python cli.py collect --country sau --source uqn window=2026-09:2026-10"
        " sections=decisions,advertisements\n"
        "  python cli.py collect --country sau --source uqn window=2026-09:2026-10 refresh=1\n"
        "  python cli.py status --country sau --source uqn"
    )


def _parse_month(raw: str, label: str) -> date:
    """``YYYY-MM`` -> the date of the month's first day."""
    try:
        y, m = raw.strip().split("-")
        return date(int(y), int(m), 1)
    except ValueError:
        raise _fail(f"{label} must be a month YYYY-MM (got {raw!r})") from None


def _month_key(month: date) -> str:
    return f"{month.year:04d}-{month.month:02d}"


def _parse_sections(raw: str) -> str:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts or any(p not in _VALID_SECTIONS for p in parts):
        raise _fail(
            "sections must be a comma-separated list drawn from: "
            + ", ".join(_VALID_SECTIONS)
        )
    seen: list[str] = []
    for p in _VALID_SECTIONS:
        if p in parts:
            seen.append(p)
    return ",".join(seen)


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")
    sections = _parse_sections(str(params.get("sections", "decisions")))

    if params.get("window"):
        from_str, sep, to_str = str(params["window"]).partition(":")
        if not sep or not from_str or not to_str:
            raise _fail(f"window must look like YYYY-MM:YYYY-MM (got {params['window']!r})")
        from_month = _parse_month(from_str, "window FROM")
        to_month = _parse_month(to_str, "window TO")
        if from_month > to_month:
            raise _fail(f"window start {from_month:%Y-%m} is after its end {to_month:%Y-%m}")
        if from_month < NEW_ERA_FIRST_MONTH:
            raise _fail(
                f"window FROM {from_month:%Y-%m} precedes {NEW_ERA_FIRST_MONTH:%Y-%m}: "
                "months before the 2026 site rebuild carry no per-month item data "
                "(2012–2025 issue-PDF backfill is a separate project)"
            )
    elif is_sync:
        kv = params.get("_kv", {})
        cursor = kv.get(CURSOR_KEY)
        if not cursor:
            raise _fail("sync=1 needs a previous sweep; run an initial window=… first")
        from_month = _add_months(_parse_month(str(cursor), CURSOR_KEY), 1)
        to_month = datetime.now(UTC).date().replace(day=1)
        if from_month > to_month:
            return []  # already in sync — nothing due
    else:
        raise _fail("give window=YYYY-MM:YYYY-MM or sync=1")

    refresh = str(params.get("refresh", "")).strip() in ("1", "true", "yes")
    refresh_stamp = datetime.now(UTC).isoformat(timespec="seconds") if refresh else None

    seeds: list[TaskSeed] = []
    month = from_month
    while month <= to_month:
        task_params: dict[str, Any] = {"month": _month_key(month), "sections": sections}
        if refresh_stamp is not None:
            task_params["refresh"] = refresh_stamp
        seeds.append(TaskSeed(type="uqn_sitemap_month", params=task_params))
        month = _add_months(month, 1)
    return seeds


def _add_months(month: date, count: int) -> date:
    """First day of the month ``count`` months away (timedelta can't step months)."""
    total = month.month - 1 + count
    return date(month.year + total // 12, total % 12 + 1, 1)


def build_source() -> SourceDefinition:
    from adapters.sau.sources.uqn.issue import UqnIssueHandler, UqnIssuePartHandler
    from adapters.sau.sources.uqn.item import UqnItemHandler
    from adapters.sau.sources.uqn.sitemap_month import UqnSitemapMonthHandler

    return SourceDefinition(
        name="uqn",
        start_tasks=start_tasks,
        task_types={
            "uqn_sitemap_month": UqnSitemapMonthHandler(),
            "uqn_item": UqnItemHandler(),
            "uqn_issue": UqnIssueHandler(),
            "uqn_issue_part": UqnIssuePartHandler(),
        },
        # Stateless GETs end to end: no login, no cookies, no csrf; the ts
        # parameter on cdn links is a cache buster, not a signature (probed
        # 2026-10-10: absent and altered ts both answer 200). Politeness is
        # the global rate gate's job.
        parallel_safe=True,
    )
