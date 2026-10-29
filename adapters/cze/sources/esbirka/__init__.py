"""The esbirka source: task-type registry, seed generation, shared helpers.

Sbírka zákonů (the Czech Collection of Laws) via e-Sbírka, the Ministry of
the Interior's electronic system — https://e-sbirka.gov.cz. Act 222/2016
Sb. section 1(2)/(3) and section 6: the Collection is the official journal,
kept in electronic form, published by the Ministry of the Interior; the
electronic form became the sole official one on 2024-01-01. Corpus 1918-2026
in one continuous numbered collection; the in-scope baseline is 1993+
(Czech independence — the 1918-1992 Czechoslovak era is out of bounds for
this source, enforced at seed validation).

Capture policy (plan Q1/Q2 rulings 2026-10-15; format revised the same
day by user ruling — no PDF): the document is the text a publication
event produced — the as-declared version addressed by the sentinel suffix
``/sb/{year}/{number}/0000-00-00`` (VYHLASENE; ``3000-01-06`` is the
current-consolidated sentinel, dated segments are point-in-time
consolidations — none followed). Everything the Collection numbers is
captured, constitutional-court findings and notices included (they hold
consecutive Collection numbers; filtering would break the time series).
The body is the informative package's XML member (probed: the alias
address's package is version-faithful — undated stem ``Sb_2026_1_IZ`` —
same fragment text the binding PDF is typeset from). Print-era originals
have no machine-readable text on the per-document channel (the package
renders the CURRENT consolidation for them; the original is a scan) —
they are captured metadata-only, their text reserved for a future
dump-based source (003+004 datasets cover 1918+; SPARQL refuses
real-shaped queries — probed, out). Version sequences are likewise native
but not collected (plan Q2).

Channels (probed 2026-10-15, no key / no session / no csrf; task-folder
probe/README.md is the evidence archive):

* register  POST https://e-sbirka.gov.cz/sbr-externi/chronologicke-rejstriky/
            dokumenty-sbirky-po-mesicich   body {"rok": YYYY}
            The whole year in one response, grouped by month, ALL collections
            mixed (sb / sm / ul0 / ul1 — filtered by the staleUrl prefix).
            Register year == publication-date year on every entry probed
            (1945/1994/2010/2026, zero spillover).
* detail    GET  …/sbr-externi/dokumenty-sbirky/{quote(staleUrl)}[+suffix]
            The staleUrl must be percent-encoded whole (the slash too).
            Act-level addresses resolve to the CURRENT version; capture
            always targets the versioned alias (sentinel suffix).
* download  GET  …/sbr-externi/stahni/informativni-zneni/{dokumentId}/ZIP
            → JSON job ticket {"pozadavekId", "id", "stavPozadavku"} →
            GET  …/souborove-sluzby/soubory/{id} → a ZIP holding the same
            text as PDF + XML + JSON + DOCX (probed 2026-10-15; the XML
            member — fragment tree with xhtml bodies, ordered by depth —
            is extracted as the document body). The binding-text channel
            serves PDF only and is deliberately not captured (user
            ruling); print-era scans are not captured either.

Task types (each = one module with ``build_request`` + ``parse``; the
one-request-per-task contract makes the async download two tasks, and the
INSERT-OR-IGNORE documents ledger makes the fully-assembled record a task
of its own):

===============  =====================================================
type             what one task does
===============  =====================================================
cze_list         one year's register (POST); spawns one cze_info per
                 in-window Collection entry; chains the next window
                 year; the FINAL year's completed walk advances the
                 cursor esbirka_last_date — the "confirmed consumed"
                 watermark (a capped walk withholds it)
cze_info         one act's dalsi-informace (type trio + approval date);
                 merges them into the register fields and spawns cze_doc
cze_doc          one act's detail root on the versioned alias — the
                 document itself: cross-checks the register row, emits
                 the complete documents record, spawns cze_odkazy
cze_odkazy       one act's download links on the versioned alias; the
                 pravneZavazneZneni block is the electronic-era signal —
                 present → spawn cze_fetch with the informativni
                 package's dokumentId; only overeneZneni (print era) →
                 expected empty: metadata-only, original is a scan (not
                 captured, user ruling), text reserved for a dump source
cze_fetch        one download job ticket; stavPozadavku != OK is a
                 transient retry; OK spawns cze_file with the file id
cze_file         the ZIP bytes; parse extracts the single ``*_IZ.xml``
                 member and stores it as the document's main file (the
                 ledger attaches it to the record cze_doc inserted)
===============  =====================================================

Params (key=value on the CLI)::

    window=2026-01-01:2026-01-31   closed publication-date range (required,
                                    or sync=1)
    sync=1                          from = day after the kv cursor
                                    esbirka_last_date, to = yesterday (the
                                    day's entries fill in during the day)
    max_docs=200                    cap on document spawns (stops the walk
                                    too: a trial window, not a partial crawl)
    collections=sb                  comma-separated Collection codes to
                                    capture (default sb; sm = international
                                    treaties, ul0/ul1 = the 1918-1948
                                    Úřední list — widening changes task
                                    identity, zero rebuild)
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote

from adapters.base import SourceDefinition, TaskSeed
from runtime.errors import TransientError

__all__ = [
    "ALIAS_VER",
    "API_BASE",
    "CURSOR_KEY",
    "FILE_BASE",
    "REGISTER_URL",
    "SITE_BASE",
    "api_doc_url",
    "body_path",
    "build_esbirka",
    "canonical_url",
    "file_url",
    "guard_waf",
    "map_doc_type",
    "number_segment",
    "stale_parts",
    "start_tasks",
    "utc_date",
    "versioned_stale",
]

API_BASE = "https://e-sbirka.gov.cz/sbr-externi"
FILE_BASE = "https://e-sbirka.gov.cz/souborove-sluzby"
SITE_BASE = "https://e-sbirka.gov.cz"
REGISTER_URL = f"{API_BASE}/chronologicke-rejstriky/dokumenty-sbirky-po-mesicich"
CURSOR_KEY = "esbirka_last_date"

#: Sentinel version segment of the as-declared text (probed 2026-10-15 on
#: both eras: 2016/222's alias download points at the 2016 original issue
#: scan, not the 2026 consolidation; the act-level address drifts to the
#: current version and is never used for capture).
ALIAS_VER = "0000-00-00"

#: The Collection codes the register mixes (probed vocabulary, 012 dump):
#: sb = Sbírka zákonů, sm = Sbírka mezinárodních smluv, ul0/ul1 = Úřední
#: list. The default scope is sb only (plan ruling 2026-10-15).
KNOWN_COLLECTIONS = ("sb", "sm", "ul0", "ul1", "ul2", "vcs")

#: Number forms (full-registry scan of the 002 dump): plain digits; a
#: single-letter PREFIX marking a parallel series ("n1/1960 Sb."
#: announcements 6,274 entries; "o1/2000 Sb." CNB measures 136 entries,
#: years 2000-2002 only — probed live when the 2000 register broke the
#: first backfill attempt); and one letter SUFFIX ("1333a/1947 Ú. l. I").
#: Zero (year, number) duplicates across the whole corpus.
_NUMBER_RE = re.compile(r"^[a-z]?\d+[a-z]?$")

#: Version segments: the as-declared sentinel, or a dated (point-in-time
#: consolidated) version as an ISO date — both sentinel forms 0000-00-00
#: and 3000-01-06 match the date shape (probed 2026-10-15).
_VERSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: podtypAktuKod -> cross-country doc_type (the Czech original always
#: rides in meta.podtyp_aktu; unmapped codes -> OTHER, re-labelling never
#: needs a re-crawl). Vocabulary probed 2026-10-15 (017 dump, 28 items).
_DOC_TYPES = {
    "ZAKON": "STATUTE",            # zákon
    "ZAKONUST": "STATUTE",         # ústavní zákon
    "OPATRSEN": "STATUTE",         # zákonné opatření Senátu (force of law)
    "NARIZENI": "REGULATION",      # nařízení vlády (and 1945 dekrety)
    "VYHLASKA": "DECREE",          # implementing ministerial decree
    "OPATRENI": "SECONDARY_LEGISLATION",
    "OZNAMENI": "ADMINISTRATIVE_NOTICE",
    "SDELENI": "ADMINISTRATIVE_NOTICE",
    "SDELENIUS": "ADMINISTRATIVE_NOTICE",
    "OZNREDAK": "ADMINISTRATIVE_NOTICE",  # Collection errata
}


def map_doc_type(podtyp: str | None) -> str:
    if not podtyp:
        return "OTHER"
    return _DOC_TYPES.get(podtyp.strip(), "OTHER")


def stale_parts(stale: str) -> tuple[str, str, str, str]:
    """/sb/2026/1[/0000-00-00] -> ("sb", "2026", "1", "0000-00-00").

    Accepts the act-level form (no version) and the versioned form; the
    version must be the as-declared sentinel or an 8-digit date. Anything
    else is a shape change and raises.
    """
    seg = stale.split("/")
    if len(seg) == 4:
        seg = [*seg, ALIAS_VER]
    if len(seg) != 5 or seg[0] != "":
        raise ValueError(f"staleUrl {stale!r} is not /sb/{{year}}/{{number}}[/{{ver}}]")
    coll, year, number, ver = seg[1], seg[2], seg[3], seg[4]
    if coll not in KNOWN_COLLECTIONS:
        raise ValueError(f"staleUrl {stale!r} has an unknown collection {coll!r}")
    if not (year.isdigit() and len(year) == 4):
        raise ValueError(f"staleUrl {stale!r} has no 4-digit year")
    if not _NUMBER_RE.match(number):
        raise ValueError(f"staleUrl {stale!r} has an unusable number {number!r}")
    if not _VERSION_RE.match(ver):
        raise ValueError(f"staleUrl {stale!r} has an unusable version {ver!r}")
    return coll, year, number, ver


def versioned_stale(coll: str, year: str, number: str) -> str:
    """The as-declared alias address of one act."""
    return f"/{coll}/{year}/{number}/{ALIAS_VER}"


def canonical_url(stale: str) -> str:
    """Stable, rebuildable URL of one version (doc_id hashes this) — the
    portal's own route form, percent-encoding-free, human-resolvable."""
    stale_parts(stale)
    return f"{SITE_BASE}{stale}"


def api_doc_url(stale: str, suffix: str = "") -> str:
    """API address of one document's sub-resource. The staleUrl is
    percent-encoded WHOLE (slash included) — the SPA's own client does
    ``encodeURIComponent`` and the API routes on the encoded form
    (probed 2026-10-15: plain slashes 404)."""
    stale_parts(stale)
    return f"{API_BASE}/dokumenty-sbirky/{quote(stale, safe='')}{suffix}"


def file_url(file_id: str) -> str:
    return f"{FILE_BASE}/soubory/{file_id}"


def number_segment(number: str) -> str:
    """Folder/filename segment for an act number: zero-padded digits for
    plain numbers, the announcement token verbatim (separate namespace)."""
    return f"{int(number):03d}" if number.isdigit() else number


def body_path(stale: str) -> str:
    """Raw-folder path of the as-declared XML body below the country root.

    The collection code is a path layer: sb and sm re-use the same number
    space per year, so widening the collections param must never make two
    documents fight over one folder.
    """
    coll, year, number, _ver = stale_parts(stale)
    seg = number_segment(number)
    return f"01_raw/esbirka/{coll}/{year}/{seg}/{coll}_{year}_{seg}_vyhlasene.xml"


def utc_date() -> date:
    return datetime.now(UTC).date()


#: The portal's own temporary-unavailability page (probed 2026-10-24
#: backfill: HTTP 200 + a 9,729-byte HTML titled AdmPortal saying
#: "Služba je dočasně nedostupná" — "the service is temporarily
#: unavailable", signed "Tým e-Sbírka a e-Legislativa"). Transient by
#: the source's own words, whatever status code carries it.
_BLOCK_MARKER = b"AdmPortal"


def guard_block_page(content: bytes, label: str) -> None:
    """The temporary-unavailability page masquerading as a 200 — transient,
    the engine's backoff waits the maintenance window out."""
    if _BLOCK_MARKER in content[:4096]:
        raise TransientError(f"{label} served the portal's temporary-unavailability page")


def guard_waf(status_code: int, label: str) -> None:
    """403/429 from the portal's front door are self-healing rate/WAF
    blocks (probed 2026-10-15: an HTML block page on burst, lifting after
    ~60 s; backfill pre-flight hit it on consecutive register calls).
    Transient — the engine's minute-scale backoff rides them out; genuine
    per-document failures keep their loud shapes."""
    if status_code in (403, 429):
        raise TransientError(
            f"{label} got HTTP {status_code} (WAF/rate block — self-heals)"
        )


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country cze --source esbirka "
        "window=2026-01-01:2026-01-31\n"
        "  python cli.py collect --country cze --source esbirka sync=1\n"
        "  python cli.py status --country cze --source esbirka"
    )


def _parse_date(raw: str, label: str) -> str:
    try:
        date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None
    return raw


#: Publication years below this are the Czechoslovak era — out of bounds
#: for this source (brief 2026-10-10 section 4; crossing later = a new
#: task identity via a wider window, zero rebuild).
FROM_YEAR_FLOOR = 1993


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")

    if params.get("window"):
        window = str(params["window"])
        from_str, sep, to_str = window.partition(":")
        if not sep or not from_str or not to_str:
            raise _fail(f"window must look like FROM:TO (got {window!r})")
        from_str = _parse_date(from_str.strip(), "window FROM")
        to_str = _parse_date(to_str.strip(), "window TO")
    elif is_sync:
        kv = params.get("_kv", {})
        cursor = kv.get(CURSOR_KEY)
        if not cursor:
            raise _fail("sync=1 needs a previous sweep; run an initial window=… first")
        from_str = (date.fromisoformat(str(cursor)) + timedelta(days=1)).isoformat()
        # To yesterday, not today: the day's entries fill in during the day,
        # and a half-filled today must not become a "consumed" watermark.
        to_str = (utc_date() - timedelta(days=1)).isoformat()
    else:
        raise _fail("give window=FROM:TO or sync=1")

    if from_str > to_str:
        raise _fail(f"window start {from_str} is after its end {to_str}")
    if int(from_str[:4]) < FROM_YEAR_FLOOR:
        raise _fail(
            f"window FROM {from_str} is in the Czechoslovak era (pre-{FROM_YEAR_FLOOR}); "
            "that span is out of bounds for this source — see the task brief"
        )

    collections = [c.strip() for c in str(params.get("collections", "sb")).split(",") if c.strip()]
    if not collections or any(c not in KNOWN_COLLECTIONS for c in collections):
        raise _fail(
            "collections must be a comma-separated list of "
            f"{', '.join(KNOWN_COLLECTIONS[:4])} (got {params.get('collections')!r})"
        )

    seed_params: dict[str, Any] = {
        "rok": int(from_str[:4]),
        "from": from_str,
        "to": to_str,
        "collections": collections,
    }
    raw_max = str(params.get("max_docs", "")).strip()
    if raw_max:
        if not raw_max.isdigit() or int(raw_max) < 1:
            raise _fail(f"max_docs must be a positive integer (got {raw_max!r})")
        seed_params["max_docs"] = int(raw_max)
    return [TaskSeed(type="cze_list", params=seed_params)]


def build_esbirka() -> SourceDefinition:
    from adapters.cze.sources.esbirka.detail import (
        CzeDocHandler,
        CzeInfoHandler,
        CzeOdkazyHandler,
    )
    from adapters.cze.sources.esbirka.fetcher import CzeFetchHandler, CzeFileHandler
    from adapters.cze.sources.esbirka.register import CzeListHandler

    return SourceDefinition(
        name="esbirka",
        start_tasks=start_tasks,
        task_types={
            "cze_list": CzeListHandler(),
            "cze_info": CzeInfoHandler(),
            "cze_doc": CzeDocHandler(),
            "cze_odkazy": CzeOdkazyHandler(),
            "cze_fetch": CzeFetchHandler(),
            "cze_file": CzeFileHandler(),
        },
        # Every request is stateless (no cookies, no tokens — the async
        # download is two plain GETs); probed 2026-10-15.
        parallel_safe=True,
    )
