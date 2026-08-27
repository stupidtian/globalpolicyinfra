"""The bgbl source: task-type registry and seed generation.

Bundesgesetzblatt Teil I (federal laws and regulations), the frozen
1949-2022 archive at www.bgbl.de. Pure-HTTP source (no browser): the xaver
single-page app is driven through its JSON endpoints. Zero domain tables —
every entry is a gazette document, so ``documents`` is the whole ledger.

Task types (each = one module with ``build_request`` + ``parse``):

===============  =====================================================
type             what one task does
===============  =====================================================
bgbl_session     seed: GET start.xav — the response's Set-Cookie is kept
                 by the transport's cookie jar (section 6.3); spawns csrf
bgbl_csrf        GET start.xav?nocomm=final — reads this session's CSRF
                 token from the JSON body; spawns the toc walk
bgbl_toc         one toclevel page; walks root -> Teil -> year and spawns
                 one bgbl_issue per selected issue
bgbl_issue       one issue's Inhaltsverzeichnis table (a single text.xav
                 deep link) — every entry's metadata in one response;
                 spawns one bgbl_pdf per real gazette entry
bgbl_pdf         one PDF via media.xav (session-bound); file + document
===============  =====================================================

Params (key=value on the CLI)::

    part=1              only Teil I is collected (2 is rejected)
    year=2020           required, 1949-2022
    issues=1-2          "all" (default), a list "1,3", or a range "1-2"

Session semantics (plan Q1, 2026-08-27 ruling): the CSRF token is bound to
the transport session, which lives for one collect run — so the whole task
chain carries a per-run ``nonce``. Task ids therefore differ between runs:
a re-run re-executes the chain (documents upsert by doc_id, files are
overwritten — same outcome, re-downloaded bytes). Done-task skipping is
impossible for session-bound sources under the current contract; recorded
as a pilot finding.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "BASE_URL",
    "BOOK",
    "FIRST_YEAR",
    "LAST_YEAR",
    "TEIL_LABELS",
    "USER_AGENT",
    "build_source",
    "start_tasks",
]

BASE_URL = "https://www.bgbl.de/xaver/bgbl"
BOOK = "bgbl"
FIRST_YEAR = 1949
LAST_YEAR = 2022

#: Tree-node labels of the two parts (toclevel root response).
TEIL_LABELS: dict[str, str] = {
    "I": "Bundesgesetzblatt Teil I",
    "II": "Bundesgesetzblatt Teil II",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country deu --source bgbl part=1 year=2020 issues=1-2\n"
        "  python cli.py collect --country deu --source bgbl part=1 year=2020\n"
        "  python cli.py status --country deu --source bgbl"
    )


def _parse_issues(raw: str) -> list[int] | str:
    """"all" | "1,3" | "1-2" -> sorted issue numbers, or "all"."""
    raw = raw.strip()
    if raw.lower() == "all":
        return "all"
    numbers: set[int] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        lo_str, sep, hi_str = token.partition("-")
        try:
            lo = int(lo_str)
            hi = int(hi_str) if sep else lo
        except ValueError:
            raise _fail(f"issues token {token!r} is not a number or range") from None
        if lo < 1 or hi < lo:
            raise _fail(f"issues token {token!r} is not a valid ascending range")
        numbers.update(range(lo, hi + 1))
    if not numbers:
        raise _fail('issues must be "all", a list like 1,3 or a range like 1-2')
    return sorted(numbers)


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    part_raw = str(params.get("part", "1")).strip().upper()
    part = {"1": "I", "I": "I", "2": "II", "II": "II"}.get(part_raw)
    if part is None:
        raise _fail(f"part must be 1 or 2 (got {part_raw!r})")
    if part == "II":
        raise _fail(
            "part=2 (Teil II, international treaties) is out of scope for this source; "
            "only part=1 is collected — see docs/countries/deu-bgbl.md section 8"
        )

    year_raw = str(params.get("year", "")).strip()
    if not year_raw:
        raise _fail("year is required (1949-2022)")
    try:
        year = int(year_raw)
    except ValueError:
        raise _fail(f"year must be a number (got {year_raw!r})") from None
    if not FIRST_YEAR <= year <= LAST_YEAR:
        raise _fail(f"year {year} is outside the archive coverage {FIRST_YEAR}-{LAST_YEAR}")

    issues = _parse_issues(str(params.get("issues", "all")))

    nonce = datetime.now(UTC).isoformat(timespec="microseconds")
    return [
        TaskSeed(
            type="bgbl_session",
            params={"nonce": nonce, "part": part, "year": year, "issues": issues},
        )
    ]


def build_source() -> SourceDefinition:
    from adapters.deu.sources.bgbl.issue import BgblIssueHandler
    from adapters.deu.sources.bgbl.pdf import BgblPdfHandler
    from adapters.deu.sources.bgbl.session import BgblCsrfHandler, BgblSessionHandler
    from adapters.deu.sources.bgbl.toc import BgblTocHandler

    return SourceDefinition(
        name="bgbl",
        start_tasks=start_tasks,
        task_types={
            "bgbl_session": BgblSessionHandler(),
            "bgbl_csrf": BgblCsrfHandler(),
            "bgbl_toc": BgblTocHandler(),
            "bgbl_issue": BgblIssueHandler(),
            "bgbl_pdf": BgblPdfHandler(),
        },
    )
