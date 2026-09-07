"""The ebgbl source: task-type registry and seed generation.

Elektronisches Bundesgesetzblatt (electronic Federal Gazette) — every
Verkündung published from 2023-01-01 at www.recht.bund.de. The paper era
(1949-2022) belongs to the sibling ``bgbl`` source; the two split by year
and point at each other on out-of-range input.

Zero session, zero key: every endpoint is a plain GET. The site's own
"Datenabruf" page documents programmatic access (ELI polling for new
publications, stable file-URL rules).

Task types (each = one module with ``build_request`` + ``parse``):

===============  =====================================================
type             what one task does
===============  =====================================================
ebgbl_sitemap    seed: one request fetches the complete index of
                 Verkündungen; spawns one ebgbl_entry per selected entry
ebgbl_entry      one entry page: metadata block + download area → one
                 ebgbl_pdf per file (Regelungstext + optional Anlagen)
ebgbl_pdf        one PDF via its official direct URL → file + document
===============  =====================================================

Params (key=value on the CLI)::

    part=1          only Teil I is collected (2 is rejected)
    year=2023       required, 2023 or later (1949-2022 belongs to bgbl)
    nrs=1-3         "all" (default), a range "1-3" (digits only, so no
                    suffixed numbers), or an exact list "1,3,3a"
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "BASE_URL",
    "FIRST_YEAR",
    "SITEMAP_URL",
    "USER_AGENT",
    "build_source",
    "start_tasks",
]

BASE_URL = "https://www.recht.bund.de"
SITEMAP_URL = f"{BASE_URL}/XMLSitemaps/Sitemap_Verkuendungen.xml"
FIRST_YEAR = 2023

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

#: A BGBl number is arabic digits with an optional letter suffix ("101a").
_NR_TOKEN_RE = re.compile(r"^(\d+)([a-zA-Z]?)$")


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country deu --source ebgbl part=1 year=2023 nrs=1-3\n"
        "  python cli.py collect --country deu --source ebgbl part=1 year=2024 --delay 3:5\n"
        "  python cli.py status --country deu --source ebgbl"
    )


def _parse_nrs(raw: str) -> list[str] | str:
    """"all" | "1-3" | "1,3,3a" -> number tokens ("3a" stays verbatim), or "all"."""
    raw = raw.strip()
    if raw.lower() == "all":
        return "all"
    tokens: list[str] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        lo_str, sep, hi_str = token.partition("-")
        if sep:  # a range: digits only, suffixed numbers must be listed
            if not (lo_str.isdigit() and hi_str.isdigit()):
                raise _fail(
                    f"nrs range {token!r} must be plain numbers; suffixed numbers "
                    "like 3a go in a list (e.g. nrs=1,3,3a)"
                )
            lo, hi = int(lo_str), int(hi_str)
            if lo < 1 or hi < lo:
                raise _fail(f"nrs range {token!r} is not a valid ascending range")
            tokens.extend(str(n) for n in range(lo, hi + 1))
        else:
            if not _NR_TOKEN_RE.match(token):
                raise _fail(f"nrs token {token!r} is not a number (letter suffix allowed: 3a)")
            tokens.append(token)
    if not tokens:
        raise _fail('nrs must be "all", a range like 1-3, or a list like 1,3,3a')
    return list(dict.fromkeys(tokens))


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    part_raw = str(params.get("part", "1")).strip().upper()
    part = {"1": "1", "I": "1", "2": "2", "II": "2"}.get(part_raw)
    if part is None:
        raise _fail(f"part must be 1 or 2 (got {part_raw!r})")
    if part == "2":
        raise _fail(
            "part=2 (Teil II, international treaties) is out of scope for this source; "
            "only part=1 is collected — see docs/countries/deu/ebgbl-zh.md section 8"
        )

    year_raw = str(params.get("year", "")).strip()
    if not year_raw:
        raise _fail("year is required (2023 or later)")
    try:
        year = int(year_raw)
    except ValueError:
        raise _fail(f"year must be a number (got {year_raw!r})") from None
    if year < FIRST_YEAR:
        raise _fail(
            f"year {year} belongs to the paper-era archive; use --source bgbl "
            f"(covers 1949-2022) — see docs/countries/deu/bgbl-zh.md"
        )

    nrs = _parse_nrs(str(params.get("nrs", "all")))
    # Live source: the day's date as reopen signal — a later run re-pulls the
    # sitemap (discovering new Verkündungen), a same-day run stays skipped.
    signal = datetime.now(UTC).date().isoformat()
    return [
        TaskSeed(
            type="ebgbl_sitemap",
            params={"part": part, "year": year, "nrs": nrs},
            signal=signal,
        )
    ]


def build_source() -> SourceDefinition:
    from adapters.deu.sources.ebgbl.entry import EbgblEntryHandler
    from adapters.deu.sources.ebgbl.pdf import EbgblPdfHandler
    from adapters.deu.sources.ebgbl.sitemap import EbgblSitemapHandler

    return SourceDefinition(
        name="ebgbl",
        start_tasks=start_tasks,
        task_types={
            "ebgbl_sitemap": EbgblSitemapHandler(),
            "ebgbl_entry": EbgblEntryHandler(),
            "ebgbl_pdf": EbgblPdfHandler(),
        },
    )
