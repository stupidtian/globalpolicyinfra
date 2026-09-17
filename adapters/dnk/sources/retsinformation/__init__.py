"""The retsinformation source: task-type registry and seed generation.

Retsinformation.dk — the official Danish legal database run by
Civilstyrelsen (Agency for Governmental Services). Three probed channels
(all key-less, samples in the repository task archive):

- ``/api/documentsearch`` (legacy but live): rows sorted by publication
  date descending; the ``retsinfoLink`` prefix IS the publication medium
  (``/eli/lta/`` = Lovtidende A, ``/eli/ltb/`` = Lovtidende B,
  ``/eli/retsinfo/`` = online-register only). Hard page cap 99
  (99 x 100 = 9,900 rows, back to 2024-04-26 probed 2026-09-15) — recent
  windows only.
- ELI sitemap: ~21 pages x 10,000 canonical URLs covering 1665-2026; the
  backfill enumeration entry (years filter applied client-side).
- Harvest API ``api.retsinformation.dk/v1/Documents``: official daily
  change feed (new / content-changed / metadata-changed / removed), last
  10 days, one call per 10 seconds — refresh channel only.

Content: GET ``{canonical}/xml`` returns the official LexDania XML
(full text from ~2008; earlier documents are metadata-only stubs whose
full text lives behind POST ``/api/document/{eli}`` — framework method
support added 2026-09-16). The POST response metadata also resolves
accession numbers to canonical paths for the refresh channel.

Domain tables (section 6.4 evidence: cross-document persistent entities):
``laws`` — one row per law lineage anchored by the timeline endpoint's
earliest (or isMainLaw) member, mirrors KOR's laws table with AUS-style
current-pointer columns; ``doc_texts`` — registers the sibling full-text
HTML file for stub-era documents (write_batch ignores a second
documents-row insert, so sibling files go through a domain table per the
section 6.7 "every path in the ledger" rule).

Task types (each = one module with ``build_request`` + ``parse``):

================  =====================================================
type              what one task does
================  =====================================================
rt_window         one search-page walk step: filter rows to the
                  window's gazette media, emit rt_timeline (LOV/LBK)
                  or rt_doc; chaining pages stop at the cap or below
                  the window start; the terminal page advances the
                  rt_last_date cursor
rt_timeline       one law lineage: GET the version timeline, anchor
                  the laws row, store timeline.json, chain rt_doc
                  with the law key (entity_ref known at registration)
rt_doc            one document: GET the official XML; registers the
                  document (primary file doc.xml); a stub (no
                  DokumentIndhold) chains rt_text for the full text
rt_text           the POST channel: documentHtml sibling text for
                  stub-era docs (doc_texts row), and canonical-path
                  resolution for harvest-originated refresh items
rt_harvest        one harvest day: change feed -> rt_text resolve
                  chains (10 s spacing is a run-time --delay concern)
rt_sitemap        sitemap backfill enumeration: index -> pages -> year
                  and media filtered rt_doc seeds (no dates in URLs:
                  stub-era doc_ids date as 00000000, real dates land
                  in meta/meta.DiesSigni and doc_texts)
================  =====================================================

Params (key=value on the CLI)::

    window=2026-09-11:2026-09-15   publication-date range (or sync=1)
    sync=1                          from = day after the rt_last_date
                                    cursor, to = yesterday
    years=1998:2002                 sitemap backfill entry (or window)
    scope=lta,ltb                   gazette media (default lta,ltb;
                                    retsinfo/ft/fob stay out)
    timeline=1                      version lineage for LOV/LBK (default 1)
    harvest=1                       refresh sweep (default off), plus
                                    harvest_days=N (default 1, cap 10)
    max_docs=N                      per-walk-page seed cap (test guard)
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "API_BASE",
    "CURSOR_KEY",
    "DEFAULT_SCOPE",
    "HARVEST_BASE",
    "SITEMAP_INDEX",
    "TIMELINE_CODES",
    "build_source",
    "map_doc_type",
    "parse_dk_date",
    "split_eli",
    "start_tasks",
]

API_BASE = "https://www.retsinformation.dk"
HARVEST_BASE = "https://api.retsinformation.dk"
SITEMAP_INDEX = "https://retsinformation.dk/sitemap.xml"

CURSOR_KEY = "rt_last_date"
DEFAULT_SCOPE = "lta,ltb"

#: documentTypeId values 10 (acts) / 30 (consolidated orders) are the only
#: ones the timeline endpoint serves (bundle gating, probed 2026-09-15).
TIMELINE_CODES = frozenset({"LOVH", "LBKH"})

#: harvest documentType.id -> ELI code (routing-data, probed 2026-09-15).
ID_TO_CODE: dict[int, str] = {
    10: "LOVH", 20: "LOVC", 30: "LBKH", 40: "DSKH", 50: "FIN", 60: "BEKH",
    70: "BKR", 80: "BEKC", 90: "BEKI", 100: "ANDH", 110: "ANDC", 120: "ANDI",
    130: "ABR", 140: "CIR1H", 150: "CIRH", 160: "CIR1C", 170: "CIRC",
    180: "VEJ", 190: "LVL", 200: "SKR", 210: "CIS", 220: "BKI", 230: "AFG",
    240: "KEN", 250: "UDT", 260: "DOM", 270: "ANGI", 280: "BKI", 290: "ADI",
    300: "FOUH", 310: "FOUÆ", 320: "ISPH", 330: "ISPÆ", 340: "EDPH",
    350: "EDPÆ", 360: "SF", 370: "BR", 380: "SF.L", 390: "SF.B", 400: "LSFL",
    410: "LSVL", 420: "BTLL", 430: "TBLL", 440: "BRLL", 450: "ÆF2L",
    460: "ÆF3L", 465: "RK", 470: "LF2L", 480: "BSFB", 490: "BSVB",
    500: "BTBB", 510: "BRBB", 520: "ÆF2B", 530: "LFL", 540: "BFB", 550: "AFT",
    560: "ANV", 570: "BET", 580: "BSK", 590: "BST", 600: "DIR", 610: "EBV",
    620: "FLO", 630: "FNO", 640: "FOR", 650: "FSK", 660: "FTG", 670: "HST",
    680: "INS", 690: "KAN", 700: "KND", 710: "KON", 720: "MED", 730: "NOR",
    740: "NOT", 750: "ORG", 760: "OVK", 770: "OVS", 780: "PJE", 790: "PKL",
    800: "PLA", 810: "PLN", 820: "PTN", 830: "RAP", 840: "RED", 850: "REG",
    860: "REM", 870: "RES", 880: "RGL", 890: "RGM", 900: "RIT", 910: "RSC",
    920: "RSU", 930: "RTL", 940: "STD", 950: "TBL", 960: "TRA", 970: "VDT",
    1480: "LTB", 1490: "STV", 1500: "AKTSTK", 1510: "ABK", 1520: "OPO",
    1530: "BTLT", 1540: "TBLT",
}

#: "Offentliggjort i" display value -> canonical ELI media segment
#: (verified against search retsinfoLink prefixes, 2026-09-15/16).
MEDIA_MAP: dict[str, str] = {
    "Lovtidende A": "lta",
    "Lovtidende B": "ltb",
    "Lovtidende C": "ltc",
    "Ministerialtidenden": "mt",
    "Retsinformation": "retsinfo",
}


def parse_dk_date(raw: str | None) -> str | None:
    """Danish display date ``DD/MM/YYYY`` -> ISO ``YYYY-MM-DD`` (or None)."""
    text = (raw or "").strip()
    try:
        day, month, year = text.split("/")
        return date(int(year), int(month), int(day)).isoformat()
    except (ValueError, TypeError):
        return None


def split_eli(eli: str) -> tuple[str, str, str, str]:
    """Canonical path -> ``(media, year, number, flattened)``.

    Supports the two probed in-scope forms: ``/eli/{media}/{year4}/{num…}``
    (Lovtidende A/B, retsinfo) and ``/eli/accn/{accn}`` (harvest hrefs).
    The long decision form ``/eli/afgoerelse/ken/2013/12/20`` is out of
    this pack's scope and rejected.
    """
    parts = eli.strip("/").split("/")
    if len(parts) < 3 or parts[0] != "eli":
        raise ValueError(f"not a supported ELI path: {eli!r}")
    media = parts[1]
    if media == "accn":
        if len(parts) != 3:
            raise ValueError(f"not a supported ELI path: {eli!r}")
        accn = parts[2]
        return media, "", accn, f"accn-{accn}"
    if len(parts) < 4 or len(parts[2]) != 4 or not parts[2].isdigit():
        raise ValueError(f"not a supported ELI path: {eli!r}")
    year = parts[2]
    number = "/".join(parts[3:])
    flat = f"{media}-{year}-{number.replace('/', '-')}"
    return media, year, number, flat


def map_doc_type(eli_code: str) -> str:
    """ELI code -> controlled doc_type; native code always kept in meta."""
    code = (eli_code or "").strip().lower()
    if code.startswith(("lov", "lbk", "fin", "dsk")):
        return "STATUTE"
    if code.startswith(("bek", "and", "abr")):
        return "SECONDARY_LEGISLATION"
    return "OTHER"


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country dnk --source retsinformation window=2026-09-11:2026-09-15\n"
        "  python cli.py collect --country dnk --source retsinformation sync=1\n"
        "  python cli.py collect --country dnk --source retsinformation years=1998:2002 max_docs=5\n"
        "  python cli.py collect --country dnk --source retsinformation harvest=1 harvest_days=3 --delay 10:12\n"
        "  python cli.py status --country dnk --source retsinformation"
    )


def _parse_date(raw: str, label: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None


def _parse_scope(raw: str) -> str:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise _fail("scope must be a comma-separated media list (e.g. lta,ltb)")
    return ",".join(parts)


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")
    scope = _parse_scope(str(params.get("scope", DEFAULT_SCOPE)))
    timeline_on = str(params.get("timeline", "1")).strip() in ("1", "true", "yes")
    max_docs = str(params["max_docs"]) if params.get("max_docs") else ""
    common: dict[str, str] = {"scope": scope, "timeline": "1" if timeline_on else "0"}
    if max_docs:
        common["max_docs"] = max_docs

    if params.get("window"):
        window = str(params["window"])
        from_str, sep, to_str = window.partition(":")
        if not sep or not from_str or not to_str:
            raise _fail(f"window must look like FROM:TO (got {window!r})")
        from_date = _parse_date(from_str.strip(), "window FROM")
        to_date = _parse_date(to_str.strip(), "window TO")
        if from_date > to_date:
            raise _fail(f"window start {from_date} is after its end {to_date}")
        return [
            TaskSeed(
                type="rt_window",
                params={
                    **common,
                    "from": from_date.isoformat(),
                    "to": to_date.isoformat(),
                    "page": "0",
                },
            )
        ]
    if is_sync:
        kv = params.get("_kv", {})
        cursor = kv.get(CURSOR_KEY)
        if not cursor:
            raise _fail("sync=1 needs a previous sweep; run an initial window=… first")
        from_date = date.fromisoformat(cursor) + timedelta(days=1)
        # Never claim *today*: the search index is live but a day's
        # publication set can still grow; yesterday is the safe horizon.
        to_date = datetime.now(UTC).date() - timedelta(days=1)
        if from_date > to_date:
            return []  # already in sync — nothing due
        return [
            TaskSeed(
                type="rt_window",
                params={
                    **common,
                    "from": from_date.isoformat(),
                    "to": to_date.isoformat(),
                    "page": "0",
                },
            )
        ]
    if params.get("years"):
        years = str(params["years"])
        lo, _, hi = years.partition(":")
        for label, value in (("years start", lo.strip()), ("years end", (hi or lo).strip())):
            if not (value.isdigit() and len(value) == 4):
                raise _fail(f"{label} must be a 4-digit year (got {value!r})")
        return [
            TaskSeed(type="rt_sitemap", params={**common, "years": years, "page": "0"})
        ]
    if str(params.get("harvest", "")).strip() in ("1", "true", "yes"):
        days_raw = str(params.get("harvest_days", "1"))
        try:
            days = int(days_raw)
        except ValueError:
            raise _fail(f"harvest_days must be an integer (got {days_raw!r})") from None
        if not 1 <= days <= 10:
            raise _fail("harvest_days must be 1..10 (the API serves 10 days)")
        yesterday = datetime.now(UTC).date() - timedelta(days=1)
        return [
            TaskSeed(
                type="rt_harvest",
                params={"date": (yesterday - timedelta(days=back)).isoformat(), "scope": scope},
            )
            for back in range(days - 1, -1, -1)
        ]
    raise _fail("give window=FROM:TO, sync=1, years=Y[:Z], or harvest=1")


def build_source() -> SourceDefinition:
    from adapters.dnk.sources.retsinformation.doc import RtDocHandler
    from adapters.dnk.sources.retsinformation.harvest import RtHarvestHandler
    from adapters.dnk.sources.retsinformation.sitemap import RtSitemapHandler
    from adapters.dnk.sources.retsinformation.text import RtTextHandler
    from adapters.dnk.sources.retsinformation.timeline import RtTimelineHandler
    from adapters.dnk.sources.retsinformation.window import RtWindowHandler

    return SourceDefinition(
        name="retsinformation",
        start_tasks=start_tasks,
        task_types={
            "rt_window": RtWindowHandler(),
            "rt_timeline": RtTimelineHandler(),
            "rt_doc": RtDocHandler(),
            "rt_text": RtTextHandler(),
            "rt_harvest": RtHarvestHandler(),
            "rt_sitemap": RtSitemapHandler(),
        },
        domain_schema="""
        CREATE TABLE IF NOT EXISTS laws (
            law_key TEXT PRIMARY KEY,
            law_name TEXT NOT NULL,
            ressort TEXT,
            current_href TEXT,
            current_signature_date TEXT,
            lineage_path TEXT
        );
        CREATE TABLE IF NOT EXISTS doc_texts (
            doc_id TEXT PRIMARY KEY,
            text_path TEXT NOT NULL,
            publication_date TEXT
        );
        """,
        domain_tables=("laws", "doc_texts"),
        domain_keys={"laws": ("law_key",), "doc_texts": ("doc_id",)},
    )
