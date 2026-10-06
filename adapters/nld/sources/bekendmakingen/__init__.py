"""The bekendmakingen source: task-type registry, seed generation, shared helpers.

Staatsblad van het Koninkrijk der Nederlanden, the Dutch state gazette —
the statutory publication medium for national Wetten (statutes), AMvB
(Algemene Maatregel van Bestuur, general administrative orders) and
Koninklijk Besluit (royal decrees). One publication = one document,
collected from the official SRU 2.0 search API of the Officiële
Bekendmakingen platform (see docs/countries/nld/bekendmakingen-zh.md).
Flat document path: zero domain tables, ``documents`` is the whole ledger.

Channels (probed 2026-09-29, no key / no session / no robots restriction
on the API; the platform's documented bulk-access route):

* day   GET https://repository.overheid.nl/sru
              ?operation=searchRetrieve&version=2.0
              &query=c.product-area=="officielepublicaties"
                     AND c.content-area=="officielepublicaties/stb/{year}"
                     AND dt.issued=="{YYYY-MM-DD}"
              &maximumRecords=100 [&startRecord=N]
        Always answers HTTP 200; a no-publication day is numberOfRecords=0
        (not a 404 — unlike BOE, no accept_not_found declaration needed).
        Each record carries full Dublin-Core metadata (identifier, title,
        type, creator, issued, ondertekening, dossier) plus every
        manifestation URL (xml/html/pdf/odt/metadata) — metadata travels
        to the item task in its params, so no second metadata request.
* item  GET the record's own xml-manifestation URL (repository.overheid.nl
        /frbr/officielepublicaties/…/xml/{id}.xml) — the full text inline.
        Issue numbers are NOT contiguous (stb-2026: 290 exists, 294–296
        do not, while the year holds 298 records): enumeration must run
        through the API, never constructed URLs.

Coverage (probed 2026-09-29): the SRU index holds Staatsblad from 1951
(1956 and 1959 are digitisation gaps, verified twice); full-text XML from
1995 — earlier records carry pdf+metadata manifestations only and register
as metadata-only documents (pdf_url in meta), the same shape ESP uses for
its scan era.

Two XML body generations coexist (~2014 split): modern records root
``officiele-publicatie`` (op-xsd-2014), older ones ``staatsbl`` (SDU DTD).
Item parsing accepts both roots and only verifies the shape: document
metadata comes from the SRU record, never from the body, so the schema
split does not touch the ledger fields.

Task types (each = one module with ``build_request`` + ``parse``):

===============  =====================================================
type             what one task does
===============  =====================================================
bek_day          one (date, blad) page of SRU results; every record with
                 an xml manifestation yields one bek_item (metadata in
                 params); records without one (scan era) register a
                 metadata-only document right here; chains to the next
                 page via ``start_record`` when numberOfRecords demands
                 it; a zero-record day is an explained empty; the
                 ``bek_last_date`` cursor moves on full consumption
bek_item         one publication's full-text XML; registers the document
                 and stores the response bytes verbatim as doc.xml
bek_year         one (year, blad) sweep of the whole content-area year,
                 no date filter, paged, no cursor — the backfill/sweep
                 axis that catches what the day axis structurally
                 cannot see: cross-year verbeterbladen (a corrected
                 reprint of a 2007 sheet is issued January 2008 but
                 lives in content-area stb/2007; found in the 2000-2025
                 backfill, 2026-09-30). Converges with bek_day at the
                 identity layer — same identifier, done tasks skip
bekendmakingen_clean   one document -> deterministic plain text
                 (framework-cleaning): local read of doc.xml, rendered
                 with the shared SDU/op-xsd block vocabulary
                 (clean.py; declared via SourceDefinition.clean,
                 version 1, targets bek_item)
===============  =====================================================

Params (key=value on the CLI)::

    window=2026-09-21:2026-09-25   closed date range (required, or sync=1)
    sync=1                          from = day after the kv cursor
                                    bek_last_date, to = *yesterday* (the
                                    day's publications are generated in
                                    the morning; a pre-publication query
                                    answers the same 0 records as a
                                    no-publication day, so sync never
                                    claims today)
    years=2007                      sweep axis: whole content-area years
                                    (years=2000:2025 for a range); no
                                    cursor involvement, overlap with the
                                    day axis is free at the identity layer
    blad=stb                        which publication(s) to keep, comma
                                    separated (default stb; e.g. stb,stcrt
                                    adds the Staatscourant — ~31,600
                                    records/year in 2026, mostly notices)
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "BLAD_DEFAULT",
    "CURSOR_KEY",
    "PAGE_SIZE",
    "SRU_BASE",
    "build_bekendmakingen",
    "canonical_doc_url",
    "map_doc_type",
    "raw_path",
    "start_tasks",
]

SRU_BASE = "https://repository.overheid.nl/sru"
#: One searchRetrieve page; per-day Staatsblad counts are single digits
#: (2026-09-21..25 probed: 4/0/6/3/6) — this is a guard rail, not the norm.
PAGE_SIZE = 100
#: Publication kept by default: Staatsblad (the state gazette).content-area
#: prefixes live at officielepublicaties/{blad}/{year}.
BLAD_DEFAULT = "stb"

CURSOR_KEY = "bek_last_date"

#: dcterms:type native words -> controlled doc_type (native word always kept
#: in meta as native_type; cross-country typology is analysis-side).
_TYPE_TO_DOC_TYPE: dict[str, str] = {
    "wet": "STATUTE",
    "rijkswet": "STATUTE",
    "amvb": "DECREE",
    "rijksamvb": "DECREE",
    "koninklijk besluit": "DECREE",
    "klein koninklijk besluit": "DECREE",
}


def map_doc_type(native_type: str) -> str:
    return _TYPE_TO_DOC_TYPE.get(native_type.strip().lower(), "OTHER")


def canonical_doc_url(identifier: str) -> str:
    """Rebuildable permanent URL of one publication's landing page.

    The platform guarantees permanent links for official publications
    (unlike parliamentary documents); the doc_id hashes this URL.
    """
    return f"https://zoek.officielebekendmakingen.nl/{identifier}.html"


def raw_path(identifier: str) -> str:
    """Raw-folder path of the main file below the country root.

    One folder per publication identifier, sharded by year to keep
    directories small (~300-900 items/year for Staatsblad).
    """
    year = _identifier_year(identifier)
    return f"01_raw/bekendmakingen/{year}/{identifier}/doc.xml"


def _identifier_year(identifier: str) -> str:
    """'stb-2026-281' -> '2026'; validates the {blad}-YYYY-{no}[-{suffix}] shape.

    The serial may carry a verbeterblad marker two ways (both observed in
    the 2000-2025 backfill, 2026-09-30): dash-separated ``-v1``/``-n1``/
    ``-b1…`` as a fourth segment, or glued to the number itself
    (``stb-2007-562v1``). The full identifier, suffix included, names the
    folder.
    """
    parts = identifier.split("-")
    serial_ok = len(parts) >= 3 and re.fullmatch(r"\d+(v\d+)?", parts[2]) is not None
    if (
        len(parts) not in (3, 4)
        or len(parts[1]) != 4
        or not parts[1].isdigit()
        or not serial_ok
        or (len(parts) == 4 and not parts[3].isalnum())
    ):
        raise ValueError(
            f"identifier {identifier!r} is not {{blad}}-{{YYYY}}-{{no}}[-{{suffix}}] "
            "— shape change"
        )
    return parts[1]


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country nld --source bekendmakingen window=2026-09-21:2026-09-25\n"
        "  python cli.py collect --country nld --source bekendmakingen sync=1\n"
        "  python cli.py collect --country nld --source bekendmakingen years=2000:2025\n"
        "  python cli.py collect --country nld --source bekendmakingen window=2026-09-21:2026-09-25 blad=stb,stcrt\n"
        "  python cli.py status --country nld --source bekendmakingen"
    )


def _parse_date(raw: str, label: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None


def _parse_year(raw: str, label: str) -> int:
    raw = raw.strip()
    if not raw.isdigit() or len(raw) != 4:
        raise _fail(f"{label} must be a 4-digit year (got {raw!r})")
    return int(raw)


def _parse_blad(raw: str) -> list[str]:
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    if not parts:
        raise _fail("blad must be a comma-separated list of publication codes (e.g. stb)")
    if any(not p.isalnum() for p in parts):
        raise _fail(f"blad codes must be alphanumeric (got {raw!r})")
    return parts


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")
    blad = ",".join(_parse_blad(str(params.get("blad", BLAD_DEFAULT))))

    if params.get("years"):
        # Sweep axis (bek_year): whole content-area years, no date filter —
        # catches cross-year verbeterbladen the day axis cannot see. No
        # cursor involvement; identity-layer dedupe makes overlaps free.
        years_raw = str(params["years"])
        from_raw, sep, to_raw = years_raw.partition(":")
        if not sep:
            to_raw = from_raw
        from_year = _parse_year(from_raw, "years FROM")
        to_year = _parse_year(to_raw, "years TO")
        if from_year > to_year:
            raise _fail(f"years start {from_year} is after its end {to_year}")
        seeds: list[TaskSeed] = []
        for year in range(from_year, to_year + 1):
            for b in blad.split(","):
                seeds.append(
                    TaskSeed(
                        type="bek_year",
                        params={"year": str(year), "blad": b, "start_record": 1},
                    )
                )
        return seeds

    if params.get("window"):
        window = str(params["window"])
        from_str, sep, to_str = window.partition(":")
        if not sep or not from_str or not to_str:
            raise _fail(f"window must look like FROM:TO (got {window!r})")
        from_date = _parse_date(from_str.strip(), "window FROM")
        to_date = _parse_date(to_str.strip(), "window TO")
        if from_date > to_date:
            raise _fail(f"window start {from_date} is after its end {to_date}")
    elif is_sync:
        kv = params.get("_kv", {})
        cursor = kv.get(CURSOR_KEY)
        if not cursor:
            raise _fail("sync=1 needs a previous sweep; run an initial window=… first")
        from_date = date.fromisoformat(cursor) + timedelta(days=1)
        # Never claim *today*: publications are generated in the morning and
        # a pre-publication query answers the same 0 records as a
        # no-publication day — indistinguishable, so don't ask.
        to_date = datetime.now(UTC).date() - timedelta(days=1)
        if from_date > to_date:
            return []  # already in sync — nothing due
    else:
        raise _fail("give window=FROM:TO or sync=1")

    day_seeds: list[TaskSeed] = []
    day = from_date
    while day <= to_date:
        for b in blad.split(","):
            day_seeds.append(
                TaskSeed(
                    type="bek_day",
                    params={
                        "date": day.isoformat(),
                        "blad": b,
                        "start_record": 1,
                    },
                )
            )
        day += timedelta(days=1)
    return day_seeds


def build_bekendmakingen() -> SourceDefinition:
    from adapters.base import CleanDefinition
    from adapters.nld.sources.bekendmakingen.clean import (
        CLEAN_VERSION,
        BekendmakingenCleanHandler,
    )
    from adapters.nld.sources.bekendmakingen.day import (
        BekDayHandler,
        BekYearHandler,
    )
    from adapters.nld.sources.bekendmakingen.item import BekItemHandler

    return SourceDefinition(
        name="bekendmakingen",
        start_tasks=start_tasks,
        task_types={
            "bek_day": BekDayHandler(),
            "bek_year": BekYearHandler(),
            "bek_item": BekItemHandler(),
            "bekendmakingen_clean": BekendmakingenCleanHandler(),
        },
        clean=CleanDefinition(
            task_type="bekendmakingen_clean",
            version=CLEAN_VERSION,
            targets=("bek_item",),
        ),
        parallel_safe=True,
    )
