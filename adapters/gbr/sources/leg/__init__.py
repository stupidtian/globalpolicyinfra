"""The leg source: legislation.gov.uk direct channel.

The National Archives operates legislation.gov.uk as an API over the
website itself (official data-reuse documentation: legislation.github.io/
data-documentation). Two task types cover the as-enacted layer::

    leg_list      seed: one page of the per-type-per-year Atom list
                  (/{type}/{year}/data.feed?page=N&results-count=100);
                  every in-scope entry yields one leg_enacted seeded with
                  the feed's atom:updated as its reopen signal; a
                  rel="next" feed link chains to the next page
    leg_enacted   one item's original as-enacted (ukpga) / as-made (uksi)
                  CLML document at /{type}/{year}/{number}/{version}/
                  data.xml; the whole XML is the document file, its
                  ukm:Metadata carries the bibliographic fields; 404 with
                  the site's known error-page shape means the item has no
                  XML version (PDF-only local/non-print instruments) and
                  is recorded as a legal empty on the items row

Access discipline (probed 2026-09-03; robots.txt): a self-identifying
User-Agent is mandatory (fair-use policy), crawl-delay is 5 seconds
(``collect --delay 5:7``), and only XML representations are fetched —
robots.txt disallows ``*/data.pdf`` and ``*/data.docx``.

Params (key=value on the CLI)::

    years=2000:2026   closed year range of enactment/registration
                      (required, or year=2023 for a single year)
    types=core        ukpga+uksi (default); or a comma list such as
                      ukpga,uksi,ukcm
    refresh={stamp}   re-walk the year lists with a changed task identity
"""

from __future__ import annotations

from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "NOT_FOUND_MARKERS",
    "PAGE_SIZE",
    "SITE",
    "USER_AGENT",
    "VERSION_WORDS",
    "build_source",
    "canonical_url",
    "item_key",
    "start_tasks",
]

SITE = "https://www.legislation.gov.uk"
PAGE_SIZE = 100  # results-count, accepted (probed 2026-09-03; default is 20)

#: Fair-use policy requires a self-identifying user agent with contact
#: details for non-browser clients.
USER_AGENT = (
    "GlobalPolicyInfra/0.1 (academic policy research; "
    "https://github.com/stupidtian/globalpolicyinfra)"
)

#: legislation type -> original-version keyword used in the URI. Probed:
#: Acts are "enacted", instruments are "made", created documents are
#: "created" (model/uris.md in the official docs).
VERSION_WORDS: dict[str, str] = {
    "ukpga": "enacted",
    "ukcm": "enacted",
    "ukla": "enacted",
    "uksi": "made",
    "ukci": "created",
    "ukmo": "created",
}

#: Cross-country doc_type (soft mapping; the site's own DocumentMainType
#: is always kept in meta — channel labels are not semantic labels).
_DOC_TYPES: dict[str, str] = {
    "ukpga": "STATUTE",
    "ukcm": "STATUTE",
    "ukla": "STATUTE",
    "uksi": "SECONDARY_LEGISLATION",
    "ukci": "SECONDARY_LEGISLATION",
    "ukmo": "SECONDARY_LEGISLATION",
}

#: Markers of the site's error page (probed 2026-09-03 on a PDF-only
#: item: HTTP 404, 12,293-byte HTML, ``<h1>Page Not Found</h1>`` and
#: ``body id="error"``). An unexpected 404 body escalates instead of
#: being swallowed.
NOT_FOUND_MARKERS = ("Page Not Found", 'id="error"')


def doc_type_of(item_type: str) -> str:
    return _DOC_TYPES.get(item_type, "OTHER")


def item_key(item_type: str, year: str, number: str) -> str:
    """Canonical key of one legislation item (its URI path)."""
    return f"{item_type}/{year}/{number}"


def canonical_url(item_type: str, year: str, number: str) -> str:
    """Rebuildable representation URL of the original-version CLML.

    doc_id hashes this, so it must be stable and canonical — always the
    https form with the pinned original-version keyword.
    """
    return f"{SITE}/{item_type}/{year}/{number}/{VERSION_WORDS[item_type]}/data.xml"


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country gbr --source leg years=2000:2026\n"
        "  python cli.py collect --country gbr --source leg year=2023 types=ukpga\n"
        "  python cli.py status --country gbr --source leg"
    )


def _resolve_types(raw: str) -> tuple[str, ...]:
    types: tuple[str, ...]
    if raw == "core":
        types = ("ukpga", "uksi")
    else:
        types = tuple(t.strip() for t in raw.split(",") if t.strip())
    if not types:
        raise _fail("types resolved to nothing (got {raw!r})")
    unknown = [t for t in types if t not in VERSION_WORDS]
    if unknown:
        raise _fail(f"unknown legislation types {unknown}; pick from {sorted(VERSION_WORDS)}")
    return types


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    types = _resolve_types(str(params.get("types", "core")).strip())
    types_spec = ",".join(types)

    years_raw = str(params.get("years", params.get("year", ""))).strip()
    if not years_raw:
        raise _fail("give years=FROM:TO (or year=YYYY for a single year)")
    from_raw, _sep, to_raw = years_raw.partition(":")
    to_raw = to_raw or from_raw
    try:
        year_from, year_to = int(from_raw), int(to_raw)
    except ValueError:
        raise _fail(f"years must be integers (got {years_raw!r})") from None
    if year_from > year_to:
        raise _fail(f"year range start {year_from} is after its end {year_to}")

    refresh = str(params.get("refresh", "")).strip()
    seeds: list[TaskSeed] = []
    for year in range(year_from, year_to + 1):
        for item_type in types:
            page_params: dict[str, Any] = {
                "type": item_type,
                "year": str(year),
                "types": types_spec,
                "page": 1,
            }
            if refresh:
                page_params["refresh"] = refresh
            seeds.append(TaskSeed(type="leg_list", params=page_params))
    return seeds


#: One row per legislation item (work level, FRBR). Columns beyond
#: ``raw_path`` are reserved for the lex bulk source (filled there,
#: never rewritten here) so both channels meet in one table without a
#: migration (section 6.4: domain schemas evolve additively only).
DOMAIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    item_key TEXT PRIMARY KEY,
    uri TEXT,
    title TEXT,
    native_type TEXT,
    year TEXT,
    number TEXT,
    enactment_date TEXT,
    laid_date TEXT,
    in_force_date TEXT,
    updated TEXT,
    xml_available INTEGER,
    n_provisions INTEGER,
    raw_path TEXT,
    status TEXT,
    valid_date TEXT,
    modified_date TEXT,
    extent TEXT,
    publisher TEXT,
    n_sections_seen INTEGER,
    lex_export_date TEXT
);
"""


def build_source() -> SourceDefinition:
    from adapters.gbr.sources.leg.enacted import LegEnactedHandler
    from adapters.gbr.sources.leg.listing import LegListHandler

    return SourceDefinition(
        name="leg",
        start_tasks=start_tasks,
        task_types={
            "leg_list": LegListHandler(),
            "leg_enacted": LegEnactedHandler(),
        },
        domain_schema=DOMAIN_SCHEMA,
        domain_tables=("items",),
        domain_keys={"items": ("item_key",)},
    )
