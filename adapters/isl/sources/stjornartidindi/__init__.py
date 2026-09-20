"""The stjornartidindi source: task-type registry and seed generation.

*Stjórnartíðindi*, the Official Journal of Iceland (published under the
Act on the Official Gazette and the Law Gazette, No. 15/2005; under the
Prime Minister's Office; the electronic edition is the legally effective
publication per Regulation No. 958/2005 — probed 2026-09-17, samples in
the task folder; see docs/countries/isl/stjornartidindi-zh.md). One flat
document-shaped source over the gazette's own API
(``api.stjornartidindi.is``, key-free, OpenAPI 3.0): A deild carries the
statutes, B deild the executive regulations (municipal items included in
the source, filtered out by the default state scope), C deild other
announcements. Three task types:

=================  =====================================================
type               what one task does
=================  =====================================================
stjornartidindi_   one slice of the lean listing
list               (``GET /api/v1/adverts-lean``): either a publication
                   date (``axis=pubdate``, ``dateFrom=dateTo={day}``) or
                   one (gazette volume year, deild) pair page
                   (``axis=year``). Rows carry id, publication number,
                   issuer, type and publication timestamp inline and
                   yield one advert seed each. A day/page beyond
                   ``pageSize`` (capped at 100 server-side) continues
                   via a same-type seed for the next page; the day
                   cursor advances only when the day's last page
                   completes. Clean empty answers are explained
                   (expected_empty); the cursor still advances for a
                   fully consumed pubdate slice.
stjornartidindi_   one advert (``GET /api/v1/adverts/{uuid}``): metadata
advert             plus the inline HTML body in the same response. The
                   body is stored verbatim as the primary ``doc.html``,
                   the raw detail response as the ``meta.json`` sibling.
                   A body that is missing or merely the digitisation
                   stub (1995-2000 sparse era: "C deild - Útgáfud.: …",
                   body text only in the PDF) seeds the pdf fallback.
stjornartidindi_   one PDF fetch (the advert's ``pdfUrl`` direct link)
pdf                — only ever seeded as the stub-era fallback.
=================  =====================================================

Params (key=value on the CLI)::

    window=2026-05-25:2026-05-29   closed publication-date range (or…)
    sync=1                          from = day after the kv cursor
                                    stjornartidindi_last_date, to =
                                    *yesterday* (the day's items may not
                                    be posted yet)
    years=2025:2025 deild=a-deild   gazette volume-year range; deild is
                                    a comma list (a-deild/b-deild/c-deild)
    scope=state                     which issuers to keep: state = all
                                    state-level issuers (default;
                                    municipal issuers filtered out), all
                                    = everything. The scope travels in
                                    the list-task params, so widening it
                                    later means new task identities and
                                    an automatic backfill — no ledger
                                    surgery.

Date semantics probed 2026-09-17: ``publicationDate`` is the real
publication date for live-era items (matches the site's "Útg" date) and
the system-entry date for retro-digitised ones (the 1995-2000 sparse era
and individual late-digitised items, e.g. C deild 97/2024 digitised
2025-10-14); ``createdDate`` distinguishes the two and travels in meta.
The volume-year filter axis is ``publicationNumber.year``, which is
reliable across all covered years (2001+ complete; 1995-2000 sparse).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "API_BASE",
    "CURSOR_KEY",
    "DEILDS",
    "MUNICIPAL_SUFFIXES",
    "SITE_BASE",
    "build_source",
    "is_municipal_issuer",
    "site_url_for",
    "start_tasks",
]

API_BASE = "https://api.stjornartidindi.is"
SITE_BASE = "https://island.is"

CURSOR_KEY = "stjornartidindi_last_date"

DEILDS: tuple[str, ...] = ("a-deild", "b-deild", "c-deild")

#: Municipal issuers. The suffix/prefix/word rules catch the regular
#: naming forms (including dissolved municipalities in historical
#: volumes); ``-þing`` is deliberately NOT a suffix (Alþingi, the
#: parliament, is a state body) so the four -þing municipalities and the
#: other irregular names ride on the explicit name list — the 62
#: municipalities of Iceland per Wikipedia "Municipalities of Iceland"
#: (2024, archived as probe 37), containment-matched so sub-entities
#: like the genitive "Velferðarsvið Reykjavíkur" also match via the
#: ``reykjavík`` stem. Trial-run lesson 2026-09-19: the first version
#: (three suffixes only) leaked Borgarbyggð / Norðurþing /
#: Velferðarsvið Reykjavíkur into the state scope.
MUNICIPAL_SUFFIXES: tuple[str, ...] = (
    "bær",
    "hreppur",
    "borg",
    "byggð",
    "kaupstaður",
    "sveit",
)

_MUNICIPAL_PREFIXES: tuple[str, ...] = ("sveitarfélag",)
_MUNICIPAL_WORDS: tuple[str, ...] = ("kaupstaður", "bæjarstjórn", "hreppsnefnd")

#: Irregular municipality names (no covered suffix) + genitive stems of
#: sub-entity forms. Derived from the official 62-municipality list.
MUNICIPAL_NAMES: tuple[str, ...] = (
    "reykjavíkurborg",
    "reykjavík",
    "kópavogsbær",
    "seltjarnarnesbær",
    "garðabær",
    "hafnarfjarðarkaupstaður",
    "hafnarfjörður",
    "mosfellsbær",
    "kjósarhreppur",
    "reykjanesbær",
    "grindavíkurbær",
    "suðurnesjabær",
    "vogar",
    "akranes",
    "skorradalshreppur",
    "hvalfjarðarsveit",
    "borgarbyggð",
    "grundarfjarðarbær",
    "eyja- og miklaholtshreppur",
    "snæfellsbær",
    "stykkishólmur",
    "dalabyggð",
    "bolungarvík",
    "ísafjarðarbær",
    "reykhólahreppur",
    "vesturbyggð",
    "súðavík",
    "árneshreppur",
    "kaldrananeshreppur",
    "strandabyggð",
    "húnaþing vestra",
    "skagaströnd",
    "húnabyggð",
    "skagafjörður",
    "akureyri",
    "norðurþing",
    "fjallabyggð",
    "dalvíkurbyggð",
    "eyjafjarðarsveit",
    "hörgársveit",
    "svalbarðsstrandarhreppur",
    "grýtubakkahreppur",
    "tjörneshreppur",
    "þingeyjarsveit",
    "langanesbyggð",
    "fjarðabyggð",
    "múlaþing",
    "vopnafjarðarhreppur",
    "fljótsdalshreppur",
    "hornafjörður",
    "vestmannaeyjar",
    "árborg",
    "mýrdalshreppur",
    "skaftárhreppur",
    "ásahreppur",
    "rangárþing eystra",
    "rangárþing ytra",
    "hrunamannahreppur",
    "hveragerði",
    "ölfus",
    "grímsnes- og grafningshreppur",
    "skeiða- og gnúpverjahreppur",
    "bláskógabyggð",
    "flóahreppur",
)

_MUNICIPAL_HAYSTACKS: tuple[str, ...] = (
    MUNICIPAL_NAMES
    + tuple(MUNICIPAL_SUFFIXES)
    + _MUNICIPAL_PREFIXES
    + _MUNICIPAL_WORDS
)


def is_municipal_issuer(issuer: str) -> bool:
    """True when the issuer names a municipality (or a municipal
    sub-entity; scope=state filters these out — brief boundary: no
    municipal regulations)."""
    lowered = issuer.strip().lower()
    return any(haystack in lowered for haystack in _MUNICIPAL_HAYSTACKS)


def site_url_for(advert_id: str) -> str:
    """The canonical, rebuildable site address of one advert (the RSS
    ``link`` shape; the API id is the same key the site addresses by)."""
    return f"{SITE_BASE}/stjornartidindi/nr/{advert_id}"


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country isl --source stjornartidindi window=2026-05-25:2026-05-29\n"
        "  python cli.py collect --country isl --source stjornartidindi sync=1\n"
        "  python cli.py collect --country isl --source stjornartidindi years=2025:2025 deild=a-deild\n"
        "  python cli.py collect --country isl --source stjornartidindi window=2026-05-25:2026-05-29 scope=all\n"
        "  python cli.py status --country isl --source stjornartidindi"
    )


def _parse_date(raw: str, label: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None


def _parse_scope(raw: str) -> str:
    scope = raw.strip().lower()
    if scope not in ("state", "all"):
        raise _fail("scope must be 'state' (state-level issuers only, default) or 'all'")
    return scope


def _parse_deilds(raw: str) -> list[str]:
    deilds = [d.strip().lower() for d in raw.split(",") if d.strip()]
    unknown = [d for d in deilds if d not in DEILDS]
    if not deilds or unknown:
        raise _fail(
            f"deild must be a comma list out of {'/'.join(DEILDS)} (got {raw!r})"
        )
    return deilds


def _pubdate_seeds(from_date: date, to_date: date, scope: str) -> list[TaskSeed]:
    seeds: list[TaskSeed] = []
    day = from_date
    while day <= to_date:
        seeds.append(
            TaskSeed(
                type="stjornartidindi_list",
                params={"axis": "pubdate", "date": day.isoformat(), "scope": scope},
            )
        )
        day += timedelta(days=1)
    return seeds


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")
    scope = _parse_scope(str(params.get("scope", "state")))

    if params.get("window"):
        window = str(params["window"])
        from_str, sep, to_str = window.partition(":")
        if not sep or not from_str or not to_str:
            raise _fail(f"window must look like FROM:TO (got {window!r})")
        from_date = _parse_date(from_str.strip(), "window FROM")
        to_date = _parse_date(to_str.strip(), "window TO")
        if from_date > to_date:
            raise _fail(f"window start {from_date} is after its end {to_date}")
        return _pubdate_seeds(from_date, to_date, scope)

    if params.get("years"):
        years_raw = str(params["years"])
        from_str, sep, to_str = years_raw.partition(":")
        if not sep or not from_str or not to_str:
            raise _fail(f"years must look like FROM:TO (got {years_raw!r})")
        try:
            from_year = int(from_str)
            to_year = int(to_str)
        except ValueError:
            raise _fail(f"years must be integers (got {years_raw!r})") from None
        if from_year > to_year:
            raise _fail(f"years start {from_year} is after its end {to_year}")
        deilds = (
            _parse_deilds(str(params["deild"]))
            if params.get("deild")
            else list(DEILDS)
        )
        seeds: list[TaskSeed] = []
        for year in range(from_year, to_year + 1):
            for deild in deilds:
                seeds.append(
                    TaskSeed(
                        type="stjornartidindi_list",
                        params={
                            "axis": "year",
                            "year": str(year),
                            "deild": deild,
                            "page": "1",
                            "scope": scope,
                        },
                    )
                )
        return seeds

    if is_sync:
        kv = params.get("_kv", {})
        cursor = kv.get(CURSOR_KEY)
        if not cursor:
            raise _fail("sync=1 needs a previous sweep; run an initial window=… first")
        from_date = date.fromisoformat(str(cursor)) + timedelta(days=1)
        # Never claim *today*: the day's items may not be posted yet, and
        # "not yet posted" answers like a clean empty day.
        to_date = datetime.now(UTC).date() - timedelta(days=1)
        if from_date > to_date:
            return []  # already in sync — nothing due
        return _pubdate_seeds(from_date, to_date, scope)

    raise _fail("give window=FROM:TO, or years=FROM:TO [deild=…], or sync=1")


def build_source() -> SourceDefinition:
    from adapters.isl.sources.stjornartidindi.advert import AdvertHandler
    from adapters.isl.sources.stjornartidindi.list import ListHandler
    from adapters.isl.sources.stjornartidindi.pdf import PdfHandler

    return SourceDefinition(
        name="stjornartidindi",
        start_tasks=start_tasks,
        task_types={
            "stjornartidindi_list": ListHandler(),
            "stjornartidindi_advert": AdvertHandler(),
            "stjornartidindi_pdf": PdfHandler(),
        },
        parallel_safe=True,  # key-free stateless API, no cookies (probed 2026-09-17)
    )
