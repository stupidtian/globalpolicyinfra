"""The gongbao source: the State Council Gazette (国务院公报), www.gov.cn.

The legal publication venue of China's central government normative output
( Legislatisation Law 2023 §78: administrative regulations published here are
the *standard texts*; §97: ministerial rules appear here *or* in the issuing
ministry's own gazette — the gazette carries a selection of those). One issue
= one publication event; every article of the issue's table of contents is
collected unfiltered — what counts as "a policy" is a research-side semantic
call, not a collection-time one.

Fully static channel (probed 2026-10-02; samples in the task archive):
one JSON issue catalog (``/gongbao/gbgl.json`` — every issue of 2000–2026,
937 issues in one request), static per-issue TOC pages, static article pages
with the full text inline in ``#UCAP-CONTENT``. No key, no session, no
signature, no captcha; UTF-8 across both page generations (2000-era and
2026-era). Zero domain tables: the gazette has no registry semantics — no
stable cross-document entity, no version lineage (a regulation's successive
amendments are independent gazette articles with no back-links).

Task types (each = one module with ``build_request`` + ``parse``):

=================  =====================================================
type               what one task does
=================  =====================================================
gongbao_index      the whole-corpus issue catalog (ONE request);
                   spawns one gongbao_issue per issue after the
                   ``years`` filter and the ``max_issues`` guardrail
gongbao_issue      one issue's TOC page; spawns one gongbao_doc per
                   article entry; archives the TOC page itself
gongbao_doc        one article page: title, publication/effective/
                   adoption dates, issuing authority, document number;
                   document + file
gongbao_clean      strip one collected article page to plain text
                   (container rules, versioned)
=================  =====================================================

Params (key=value on the CLI)::

    years=2026        required: "2026", "2000-2026" or "2024,2026"
    max_issues=2      per-year cap on gongbao_issue spawns (newest first)
    refresh=<ISO ts>  reopen the index+issue walk to discover new issues
                      and articles; stored articles stay skipped (done-skip)
"""

from __future__ import annotations

import re
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "BASE_URL",
    "CATALOG_URL",
    "build_source",
    "canonical_article_url",
    "issue_folder",
    "issue_url",
    "normalize_space",
    "parse_years",
    "start_tasks",
]

BASE_URL = "https://www.gov.cn"
CATALOG_URL = f"{BASE_URL}/gongbao/gbgl.json"

_YEAR_KEY_RE = re.compile(r"^(\d{4})年$")
_ISSUE_URL_RE = re.compile(r"/gongbao/(.+/issue_\d+)/?$")


def canonical_article_url(path: str) -> str:
    """Stable, rebuildable URL of one article (doc_id hashes this)."""
    return f"{BASE_URL}/gongbao/{path.lstrip('/')}"


def issue_url(path: str) -> str:
    """Issue URL from the catalog's own path below ``/gongbao/`` — the
    catalog ``gname`` path is the sole addressing authority. Probed shapes
    (2026-10-02): ``2026/issue_13006`` (modern), ``2001/2006`` (legacy bare
    numbers, 8 years), ``201701/issue_1275`` (2007's whole year re-homed
    under a different first segment)."""
    return f"{BASE_URL}/gongbao/{path.strip('/')}/"


def issue_folder(path: str) -> str:
    """Raw-folder path below the country root — mirrors the source path."""
    return f"01_raw/gongbao/{path.strip('/')}"


def normalize_space(text: str) -> str:
    """Collapse CJK/ASCII whitespace runs (incl. ``\\u3000`` and ``<br/>``
    gaps) to single spaces — titles carry both generations' filler."""
    text = re.sub(r"<br\s*/?>", " ", text)
    return re.sub(r"[\s\u3000]+", " ", text).strip()


def parse_years(raw: str) -> set[int]:
    """"2026" | "2000-2026" | "2024,2026" -> set of years (raises SystemExit
    with usage on garbage; mirrors the kor pack's strictness)."""
    years: set[int] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        lo_str, sep, hi_str = token.partition("-")
        try:
            lo = int(lo_str)
            hi = int(hi_str) if sep else lo
        except ValueError:
            raise SystemExit(
                f"error: years token {token!r} is not a number or range"
            ) from None
        if lo < 1900 or hi < lo:
            raise SystemExit(
                f"error: years token {token!r} is not a valid ascending range"
            )
        years.update(range(lo, hi + 1))
    if not years:
        raise SystemExit(
            'error: years is required, e.g. years=2026 or years=2000-2026\n'
            "usage examples:\n"
            "  python cli.py collect --country chn --source gongbao years=2026 max_issues=1\n"
            "  python cli.py collect --country chn --source gongbao years=2000-2026\n"
            "  python cli.py status --country chn --source gongbao"
        )
    return years


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    years = parse_years(str(params.get("years", "")).strip())

    max_issues: int | None = None
    raw_max = str(params.get("max_issues", "")).strip()
    if raw_max:
        try:
            max_issues = int(raw_max)
        except ValueError:
            raise SystemExit(
                f"error: max_issues must be a positive integer (got {raw_max!r})"
            ) from None
        if max_issues < 1:
            raise SystemExit(
                f"error: max_issues must be a positive integer (got {raw_max!r})"
            )

    refresh = str(params.get("refresh", "")).strip()
    if refresh and not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?)?", refresh
    ):
        raise SystemExit("error: refresh must be an ISO timestamp, e.g. 2026-10-02T09:00")

    # One seed per selected year keeps per-year max_issues bookkeeping in the
    # params (the index handler caps spawns per year); the catalog itself is
    # one request per task — N years, N cheap requests, each independently
    # retryable and refresh-reopenable.
    seeds: list[TaskSeed] = []
    for year in sorted(years):
        seed_params: dict[str, Any] = {"year": str(year)}
        if max_issues is not None:
            seed_params["max_issues"] = max_issues
        seeds.append(
            TaskSeed(type="gongbao_index", params=seed_params, signal=refresh or None)
        )
    return seeds


def build_source() -> SourceDefinition:
    from adapters.base import CleanDefinition
    from adapters.chn.sources.gongbao.clean import CLEAN_VERSION, GongbaoCleanHandler
    from adapters.chn.sources.gongbao.document import GongbaoDocHandler
    from adapters.chn.sources.gongbao.index import GongbaoIndexHandler
    from adapters.chn.sources.gongbao.issue import GongbaoIssueHandler

    return SourceDefinition(
        name="gongbao",
        start_tasks=start_tasks,
        task_types={
            "gongbao_index": GongbaoIndexHandler(),
            "gongbao_issue": GongbaoIssueHandler(),
            "gongbao_doc": GongbaoDocHandler(),
            "gongbao_clean": GongbaoCleanHandler(),
        },
        # The gazette shape is one stable container across both page
        # generations (probed 2026-10-02 on 2000-era and 2026-era pages:
        # #UCAP-CONTENT carries the whole article). Version bumps re-clean.
        clean=CleanDefinition(
            task_type="gongbao_clean",
            version=CLEAN_VERSION,
            targets=("gongbao_doc",),
        ),
        # Gazette-shaped: no registry entity, no version lineage — zero
        # domain tables (the DEU BGBl / JPN kanpo family; section 6.4
        # criterion: no cross-document persistent entity exists).
        domain_schema="",
        domain_tables=(),
        # Stateless GETs end to end — no cookies, no tokens, no cross-task
        # transport state (probed 2026-10-02) — safe on any worker with any
        # session (framework-concurrency ruling 1.4).
        parallel_safe=True,
    )
