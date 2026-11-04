"""The nn source: task-type registry and seed generation.

Narodne novine (narodne-novine.nn.hr, the "NN Tražilica" platform) is
Croatia's official gazette, published by the state-majority company
Narodne novine d.d. under the publication duty of Article 90 of the
Constitution (institutional landscape verified 2026-11-01 against the
publisher's own site and legislative texts; samples in the task folder;
see docs/countries/hrv/nn-zh.md). The corpus is the Službeni dio (official
part) series, 1990-present, addressed by ELI paths — a gazette-shaped flat
source (zero domain tables) like DEU BGBl / FRA JORF / ESP BOE. Three task
types:

=================  =====================================================
type               what one task does
=================  =====================================================
nn_index           one year's inventory CSV
                   (``GET /get_index_file.aspx?year={Y}&type=csv``, the
                   source's own "Popis svih propisa" export: issue,
                   global ordinal, title, native type, subtype,
                   amendment/repeal relation marker, issuer, ELI link).
                   Each kept row yields one ``nn_doc`` seed. The year is
                   the only enumeration axis — there is no date cursor.
nn_doc             one gazette item: ``GET /eli/sluzbeni/{Y}/{issue}/
                   {ordinal}`` (301 -> the item HTML page). The page
                   carries the detailsTable metadata block (part, type,
                   issue, global ordinal, printed page, issuer,
                   publication date, ELI) and — 1990-2022 — the full
                   text inline. When the text is not yet entered
                   (2023+ items publish the PDF first and back-fill the
                   HTML with a lag), the page's pdf-view iframe points
                   at the per-item PDF and the task hands over to
                   ``nn_pdf`` instead of registering a stub document.
nn_pdf             the per-item PDF (2023+ only) as the full-text
                   carrier: registers the document with the PDF as the
                   primary file and the HTML page (written by the
                   ``nn_doc`` task) recorded in meta.files.
=================  =====================================================

Params (key=value on the CLI)::

    year=2026                      single year (or years=A:B range, or
                                   sync=1 for the current year)
    issues=122:124                 optional within-year issue window;
                                   filtering to zero rows is a loud error
    scope=policy                   policy (default) = rows whose issuer is
                                   a court or the judicial council stay out;
                                   all = everything
    sync=1                         refresh the current year under a fresh
                                   task identity (refresh mode, section 6.5)

Body-carrier eras (probed 2026-11-01): 1990-2022 the item page HTML
carries the full text (older years are the platform's own OCR layer);
2023+ the text lives in the per-item PDF and the HTML body is back-filled
with a lag — either way the first visit records a complete text, so done
tasks are never reopened for the back-fill. The boundary is exact: the
per-item PDF answers 200 from NN 1/2023 onward and 302->404 for the last
2022 issue.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "API_BASE",
    "FIRST_YEAR",
    "SITE_BASE",
    "article_pdf_url_for",
    "build_source",
    "is_court_issuer",
    "site_url_for",
    "start_tasks",
]

API_BASE = "https://narodne-novine.nn.hr"
SITE_BASE = "https://narodne-novine.nn.hr"

#: First year of the digital archive (sitemap, year CSV and the search
#: UI's year list all start at 1990 — probed 2026-11-01).
FIRST_YEAR = 1990

_INDEX_PATH = "/get_index_file.aspx"

#: Court issuers by whole word: "sud" (court — Ustavni sud, Visoki
#: upravni sud, ... ) and "sudbeno" (judicial — Državno sudbeno vijeće,
#: the judicial council whose acts are appointments, not case law but not
#: government policy either). Substring matching would be wrong
#: ("sudbeno" contains "sud"); token matching keeps e.g. "Državni zavod
#: za intelektualno vlasništvo" (a state office, kept) out of the filter.
_COURT_TOKENS = ("sud", "sudbeno")
_TOKEN_RE = re.compile(r"[a-zčćžšđ]+")


def is_court_issuer(issuer: str) -> bool:
    """True when the issuer names a court or the judicial council
    (scope=policy filters these rows out — the corpus is government
    policy and regulation; user ruling 2026-11-01)."""
    tokens = set(_TOKEN_RE.findall(issuer.casefold()))
    return any(token in tokens for token in _COURT_TOKENS)


def site_url_for(year: int, issue: int, ordinal: int) -> str:
    """The canonical, rebuildable ELI address of one gazette item (the
    form the source's own inventory CSV writes into its link column and
    the item page echoes in its ELI field)."""
    return f"{SITE_BASE}/eli/sluzbeni/{year}/{issue}/{ordinal}"


def article_pdf_url_for(year: int, issue: int, ordinal: int) -> str:
    """The per-item PDF address (2023+; the item page's pdf-view iframe
    src is exactly this form)."""
    return f"{site_url_for(year, issue, ordinal)}/pdf"


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country hrv --source nn year=2026\n"
        "  python cli.py collect --country hrv --source nn year=2026 issues=122:124\n"
        "  python cli.py collect --country hrv --source nn years=1990:1999\n"
        "  python cli.py collect --country hrv --source nn sync=1\n"
        "  python cli.py collect --country hrv --source nn year=2026 scope=all\n"
        "  python cli.py status --country hrv --source nn\n"
        "  (incremental: sync=1 re-walks the current year's inventory; done items skip)"
    )


def _parse_year(raw: Any, what: str) -> int:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise _fail(f"{what} must be an integer year (got {raw!r})") from None
    current = datetime.now(UTC).year
    if not FIRST_YEAR <= value <= current:
        raise _fail(
            f"{what} must be within the platform's archive "
            f"({FIRST_YEAR}..{current}, got {value})"
        )
    return value


def _parse_ordinal_pair(raw: str, what: str) -> tuple[int, int]:
    """``A:B`` closed range shared by years= and issues=."""
    from_str, sep, to_str = raw.partition(":")
    if not sep:
        raise _fail(f"{what} must look like A:B (got {raw!r})")
    try:
        start, end = int(from_str.strip()), int(to_str.strip())
    except ValueError:
        raise _fail(f"{what} must look like A:B (got {raw!r})") from None
    if end < start:
        raise _fail(f"{what}: start {start} is after its end {end}")
    return start, end


def _parse_issues(raw: Any) -> str:
    issues = str(raw).strip()
    if not issues:
        raise _fail("issues must look like A:B (got an empty value)")
    start, end = _parse_ordinal_pair(issues, "issues")
    return f"{start}:{end}"


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    scope = str(params.get("scope", "policy")).strip().lower()
    if scope not in ("policy", "all"):
        raise _fail("scope must be 'policy' (courts out, default) or 'all'")

    refresh = str(params.get("refresh", "")).strip()
    if params.get("sync"):
        years = [datetime.now(UTC).year]
        refresh = refresh or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    elif params.get("year") is not None:
        years = [_parse_year(params["year"], "year")]
    elif params.get("years") is not None:
        start, end = _parse_ordinal_pair(str(params["years"]).strip(), "years")
        current = datetime.now(UTC).year
        if start < FIRST_YEAR or end > current:
            raise _fail(f"years must be within {FIRST_YEAR}..{current}")
        years = list(range(start, end + 1))
    else:
        raise _fail("give year=, years=A:B, or sync=1")

    issues = _parse_issues(params["issues"]) if params.get("issues") is not None else ""

    seeds = []
    for year in years:
        index_params: dict[str, Any] = {"year": year, "scope": scope}
        if issues:
            index_params["issues"] = issues
        if refresh:
            index_params["refresh"] = refresh
        seeds.append(TaskSeed(type="nn_index", params=index_params))
    return seeds


def build_source() -> SourceDefinition:
    from adapters.hrv.sources.nn.doc import DocHandler
    from adapters.hrv.sources.nn.index import IndexHandler
    from adapters.hrv.sources.nn.pdf import PdfHandler

    return SourceDefinition(
        name="nn",
        start_tasks=start_tasks,
        task_types={
            "nn_index": IndexHandler(),
            "nn_doc": DocHandler(),
            "nn_pdf": PdfHandler(),
        },
        parallel_safe=True,  # key-free stateless GETs, no session dependency (probed 2026-11-01)
    )
