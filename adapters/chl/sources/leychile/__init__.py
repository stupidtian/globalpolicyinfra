"""The leychile source: task-type registry, seed generation, shared parsing.

Ley Chile (https://www.leychile.cl, run by the Biblioteca del Congreso
Nacional de Chile) — the whole normative corpus of Chile: laws, decree-laws,
DFLs, decrees, resolutions, circulars, court rules, treaties, 1850 to today
(415,344 normas as of 2026-09-20, repealed ones included by default).

Three plain-GET JSON endpoints under ``nuevo.leychile.cl/servicios``
(probed 2026-09-20, see docs/countries/chl/leychile-zh.md section 9).
No API key, no cookies, no csrf, no browser — but a User-Agent *blocklist*
(curl/* gets 401; python-requests and browser UAs pass), which the
framework's default Chrome UA clears with zero adapter-side headers.

Versioning (the lineage backbone): a norma's identity is ``idNorma``
(stable across amendments); every amendment creates a new version whose
identity is ``(idNorma, vigenteDesde)`` — the date that version took
effect. The body endpoint accepts either the numeric version id or that
date (both probed byte-identical in effect); the date form is canonical
because the version timeline only exposes dates. Version kinds:
``Texto Original`` (as promulgated), ``Intermedio`` (consolidated state
after each amendment), ``Última Versión`` (current), ``Única`` (never
amended — exactly one version, so the timeline request is skipped; row
TIPOVERSION '3' vs '2' tells them apart).

Task types (each = one module with ``build_request`` + ``parse``):

===============  =====================================================
type             what one task does
===============  =====================================================
chl_list         one year-window page of the register (50 rows);
                 upserts every row into ``normas`` (the register and its
                 time series stand on the list layer alone) and spawns
                 one anchor ``chl_body`` per norma; with walk=1 a full
                 page spawns pg+1 (an empty page stops the chain)
chl_body         one version's full text + 31-field metadata; document +
                 raw JSON file; an anchor of an amended norma (row
                 TIPOVERSION != '3') also spawns ``chl_versions``
chl_versions     one norma's version timeline (original + intermediates
                 + latest, each with validity range and the amending
                 norms); rewrites the norma's ``norma_versions`` row
                 group and spawns ``chl_body`` per historical version
===============  =====================================================

Params (key=value on the CLI)::

    years=2024 | 1990,2010 | 1850-2026 | all   required year windows
    pages=1-2        optional register-page range per year
    max_normas=5     optional cap on chl_body spawns per list page
    refresh=<ISO>    repeatable discovery (reopens done list tasks)
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "API_BASE",
    "CANONICAL_BASE",
    "FIRST_YEAR",
    "PAGE_SIZE",
    "build_source",
    "canonical_norma_url",
    "list_params",
    "map_doc_type",
    "spanish_date_to_iso",
    "start_tasks",
]

API_BASE = "https://nuevo.leychile.cl/servicios"
CANONICAL_BASE = "https://www.bcn.cl/leychile/navegar"
PAGE_SIZE = 50
#: Oldest year with any norma in the corpus (probed 2026-09-20: 1850 has
#: 1 item, 1810 has 0). ``years=all`` walks from here to the current year.
FIRST_YEAR = 1850

#: Spanish month abbreviations Ley Chile uses in list-row dates
#: ('31-DIC-2024'); body metadata dates are already ISO.
_MONTHS = {
    "ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12,
}

#: Type abbreviation -> soft doc_type (native abbr always kept in
#: meta.type_abbr / normas.type_abbr; cross-country merges are an
#: analysis-stage asset, never done here). DL counts as STATUTE and DFL
#: as DECREE per user ruling 2026-09-20 (Chilean hierarchy: decree-laws
#: are legislative products, DFLs are executive delegated legislation).
_TYPE_MAP = {
    "CTR": "CONSTITUTION",
    "LEY": "STATUTE",
    "DL": "STATUTE",
    "COD": "STATUTE",
    "DFL": "DECREE",
    "DTO": "DECREE",
    "RES": "SECONDARY_LEGISLATION",
    "CIR": "SECONDARY_LEGISLATION",
    "INS": "SECONDARY_LEGISLATION",
    "AA": "RULE",
}


def map_doc_type(abbr: str) -> str:
    """Norma type abbreviation -> soft doc_type (Spanish original travels
    in meta.type_abbr)."""
    return _TYPE_MAP.get(abbr.strip().upper(), "OTHER")


def spanish_date_to_iso(text: str) -> str | None:
    """'31-DIC-2024' -> '2024-12-31' (list-row date format); None if the
    text does not carry that shape."""
    match = re.fullmatch(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", (text or "").strip())
    if match is None:
        return None
    day, abbr, year = match.groups()
    month = _MONTHS.get(abbr.upper())
    if month is None:
        return None
    try:
        return date(int(year), month, int(day)).isoformat()
    except ValueError:
        return None


def list_params(year: int, pg: int) -> dict[str, str]:
    """buscarjson form fields exactly as the site's own search posts them
    (probed 2026-09-20). ``fc_pb`` must stay year-granular — day-level
    values make the server answer 500; requests' default encoding turns
    the spaces of '2024 TO 2024' into the literal '+' the API requires."""
    return {
        "itemsporpagina": str(PAGE_SIZE),
        "npagina": str(pg),
        "tipoviene": "1",
        "fc_de": "",
        "fc_ra": "",
        "seleccionado": "0",
        "fc_rp": "",
        "totalitems": "",
        "orden": "2",
        "fc_pb": f"{year} TO {year}",
        "fc_pr": "",
        "exacta": "0",
        "cadena": "",
        "fc_tn": "",
    }


def canonical_norma_url(id_norma: str, vigente_desde: str) -> str:
    """Stable, rebuildable URL of one version (doc_id hashes this)."""
    return f"{CANONICAL_BASE}?idNorma={id_norma}&idVersion={vigente_desde}"


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country chl --source leychile years=2024\n"
        "  python cli.py collect --country chl --source leychile years=2024 pages=1 max_normas=3\n"
        "  python cli.py collect --country chl --source leychile years=1850-2026\n"
        "  python cli.py status --country chl --source leychile"
    )


def _parse_pages(raw: str) -> list[int] | None:
    """"1" | "1,3" | "1-2" -> sorted page numbers; None = all pages."""
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
            raise _fail(f"pages token {token!r} is not a number or range") from None
        if lo < 1 or hi < lo:
            raise _fail(f"pages token {token!r} is not a valid ascending range")
        numbers.update(range(lo, hi + 1))
    if not numbers:
        raise _fail('pages must be a list like 1,3 or a range like 1-2 (omit = all pages)')
    return sorted(numbers)


def _parse_years(raw: str) -> list[int]:
    """"2024" | "1990,2010" | "1850-2026" | "all" -> sorted years."""
    raw = raw.strip()
    if raw.lower() == "all":
        # Unpacking, not list(): importing the sibling list.py module
        # binds `list` to that module in this package's namespace (same
        # trap the kor pack dodges by never calling list() here).
        return [*range(FIRST_YEAR, datetime.now(UTC).date().year + 1)]
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
            raise _fail(f"years token {token!r} is not a number or range") from None
        if lo < 1000 or hi < lo:
            raise _fail(f"years token {token!r} is not a valid ascending range")
        years.update(range(lo, hi + 1))
    if not years:
        raise _fail('years is required: "2024", "1990,2010", "1850-2026" or "all"')
    return sorted(years)


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    raw_years = str(params.get("years", "")).strip()
    if not raw_years:
        raise _fail("years is required")
    years = _parse_years(raw_years)

    pages: list[int] | None = None
    raw_pages = str(params.get("pages", "")).strip()
    if raw_pages:
        pages = _parse_pages(raw_pages)

    max_normas: int | None = None
    raw_max = str(params.get("max_normas", "")).strip()
    if raw_max:
        try:
            max_normas = int(raw_max)
        except ValueError:
            raise _fail(f"max_normas must be a positive integer (got {raw_max!r})") from None
        if max_normas < 1:
            raise _fail(f"max_normas must be a positive integer (got {raw_max!r})")

    # Repeatable discovery (same family as KOR refresh): refresh=<timestamp>
    # reopens already-done register pages so a later run finds new normas
    # and new amendments; done body/versions tasks stay skipped.
    refresh = str(params.get("refresh", "")).strip()
    if refresh and not re.fullmatch(r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?)?", refresh):
        raise _fail("refresh must be an ISO timestamp, e.g. 2026-09-21T09:00")

    seeds: list[TaskSeed] = []
    for year in years:
        if pages is None:
            seeds.append(
                TaskSeed(type="chl_list", params={"year": year, "pg": 1, "walk": 1}, signal=refresh or None)
            )
        else:
            seeds.extend(
                TaskSeed(type="chl_list", params={"year": year, "pg": pg}, signal=refresh or None)
                for pg in pages
            )
    if max_normas is not None:
        seeds = [
            TaskSeed(
                type=seed.type,
                params={**seed.params, "max_normas": max_normas},
                signal=seed.signal,
            )
            for seed in seeds
        ]
    return seeds


#: The norma entity (section 6.4 judgment: a cross-document persistent
#: entity exists — one norma spans many version documents, exactly the
#: KOR ``laws`` case, one notch further: the timeline carries the native
#: amendment chain). ``normas`` is written by the list layer alone (the
#: register and its time series stand on ~8.3K list pages for the whole
#: corpus, independent of body-fetch progress); ``norma_versions`` is
#: rewritten as one group per timeline fetch.
DOMAIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS normas (
    id_norma TEXT PRIMARY KEY,
    norma_name TEXT NOT NULL,
    title TEXT,
    doc_type TEXT,
    type_abbr TEXT,
    organismo TEXT,
    numero TEXT,
    fecha_promulgacion TEXT,
    fecha_publicacion TEXT,
    fecha_derogacion TEXT,
    current_vigencia TEXT,
    tipo_version TEXT
);
CREATE TABLE IF NOT EXISTS norma_versions (
    id_norma TEXT NOT NULL,
    vigente_desde TEXT NOT NULL,
    tipo_version TEXT,
    vigente_hasta TEXT,
    modificatorias TEXT,
    PRIMARY KEY (id_norma, vigente_desde)
);
"""


def build_source() -> SourceDefinition:
    from adapters.chl.sources.leychile.body import ChlBodyHandler
    from adapters.chl.sources.leychile.list import ChlListHandler
    from adapters.chl.sources.leychile.versions import ChlVersionsHandler

    return SourceDefinition(
        name="leychile",
        start_tasks=start_tasks,
        task_types={
            "chl_list": ChlListHandler(),
            "chl_body": ChlBodyHandler(),
            "chl_versions": ChlVersionsHandler(),
        },
        domain_schema=DOMAIN_SCHEMA,
        domain_tables=("normas", "norma_versions"),
        domain_keys={
            "normas": ("id_norma",),
            "norma_versions": ("id_norma", "vigente_desde"),
        },
        # Stateless GETs, zero cookies (probed 2026-09-20) — safe on any
        # worker with any session (framework-concurrency ruling 1.4).
        parallel_safe=True,
    )
