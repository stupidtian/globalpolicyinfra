"""The uradnilist source: task-type registry and seed generation.

*Uradni list Republike Slovenije*, the official gazette of the Republic of
Slovenia, published continuously since 1991-01-18. Until 2026-02-28 the
gazette was published (print + electronic) by Uradni list d.o.o. on
uradni-list.si; under the ZOUL (Zakon o objavljanju v Uradnem listu RS,
adopted 2025-10-17) publication moved exclusively onto the PISRS portal
operated by the government legislation service (Služba Vlade RS za
zakonodajo) on 2026-03-01, and uradni-list.si is now a §33 archival site.
This source therefore reads everything from PISRS's free JSON/HTTP API
(probed 2026-10-12, samples in the task folder; see
docs/countries/svn/uradnilist-zh.md). Task types:

===============  =====================================================
type             what one task does
===============  =====================================================
ul_month         one calendar month intersecting the requested window:
                 GET the authoritative issue calendar
                 (``/api/uradni-list/izdaje-datumi``, every issue date
                 since 1991-01-18 in one response) and emit one
                 ``ul_date`` seed per real issue date inside the
                 month/bounds. Days without an issue are never enqueued
                 — the calendar is the enumeration backbone, not
                 day-by-day probing.
ul_date          one issue date: GET the day listing
                 (``/api/uradni-list/izdaje-seznam?datumObjave=…``,
                 a two-level issuer-grouped tree whose leaves carry
                 slug, title, PISRS act id, UL issue number and the
                 as-published PDF name). Registers one documents row
                 per act (state-level group by default; ``scope=all``
                 also keeps the municipal group) and emits carrier
                 tasks per era (see below). A fully consumed day
                 advances the cursor.
ul_html          one act's archival HTML page (pre-ZOUL dates only):
                 GET ``uradni-list.si/glasilo-uradni-list-rs/vsebina/
                 {slug}/{title-slug}?h=`` and store the page as the
                 act's primary file — the text carrier, directly
                 cleanable (whitelist ``div#divSection``). The archive
                 served 2000-2025 acts at a 32/32 hit rate in the
                 coverage probe (2026-10-12, state and municipal,
                 punctuation-heavy titles included); ZOUL-era acts are
                 not on the archive per the site's own notice.
ul_pdf           one as-published PDF: GET
                 ``/api/uradni-list/objava/{name}`` and store the
                 bytes verbatim under ``01_raw/uradnilist/{year}/…``.
                 Pre-ZOUL a whole-issue file shared by N acts is the
                 *secondary* carrier (stored once, path recorded in
                 each act's meta.ul_pdf_path — the HTML page carries
                 the doc_id); since ZOUL each act has its own PDF and
                 that PDF is the *primary* file (doc_id-carried).
uradnilist_clean strip one archival HTML page to plain text
                 (whitelist ``div#divSection``; local read, no
                 network).
===============  =====================================================

Params (key=value on the CLI)::

    window=2026-09-28:2026-10-09   closed date range (required, or sync=1)
    sync=1                          from = day after the kv cursor
                                    uradnilist_last_date, to = *yesterday*
                                    (today's issue may not be out yet)
    scope=state                     which issuer groups to keep: state =
                                    drzavniOrgani only (default; municipal
                                    ordinances filtered out at group level —
                                    no name heuristics), all = everything.
                                    The scope travels in the task params, so
                                    widening it later means new task
                                    identities and an automatic backfill.
    pdf=on                          whether pre-ZOUL acts also store the
                                    verbatim issue PDF as their second
                                    carrier (path in meta.ul_pdf_path):
                                    on = default (the official original is
                                    archived locally), off = HTML only
                                    (~2,900 requests and ~7 GB saved on a
                                    2000-2025 backfill; the PDF stays
                                    reachable at its canonical URL, always
                                    recorded in meta.ul_pdf_url). Post-ZOUL
                                    acts are PDF-primary regardless — the
                                    archive carries no HTML for them — so
                                    the knob does not touch that era.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "API_BASE",
    "ARCHIVE_BASE",
    "CURSOR_KEY",
    "SITE_BASE",
    "ZOUL_ELECTRONIC_ONLY",
    "archive_url_for",
    "build_source",
    "html_rel_path",
    "map_doc_type",
    "objava_url_for",
    "pdf_rel_path",
    "source_url_for",
    "start_tasks",
    "title_slug",
]

API_BASE = "https://pisrs.si/api"
SITE_BASE = "https://pisrs.si"
ARCHIVE_BASE = "https://www.uradni-list.si"

CURSOR_KEY = "uradnilist_last_date"

#: ZOUL boundary: from this date the gazette publishes exclusively on
#: PISRS (one act = one issue = one PDF) and the archival site carries
#: nothing (its own notice: issues after 2026-02-28 live on PISRS). Acts
#: published BEFORE this date have a per-act archival HTML page (the
#: primary text carrier); ISO strings compare correctly.
ZOUL_ELECTRONIC_ONLY = "2026-03-01"

#: PISRS act id -> controlled doc_type (soft mapping; the id prefix is the
#: native type code and always rides in meta.id_prefix). Probed against the
#: pregledPredpisa sitemaps (204k ids, 2026-10-12) and real listing titles:
#: ZAKO zakon, USTZ ustavni zakon, URED uredba, PRAV pravilnik, NAVO
#: navodilo, TARI tarifa, POSL poslovnik, KOLP kolektivna pogodba (probed:
#: a postal-services collective agreement), STAT statut, ODLO odlok, ODLU
#: odločba (probed: an individual administrative decision), SKLE sklep,
#: SKLU sklep vlade, ODRE odredba, UKAZ ukaz — all standard Slovenian legal
#: vocabulary. DRUG drugo, AKT (probed sample: an election call), ODLB
#: (probed sample: a municipal planning *program*, not a norm), RESO
#: (probed: a parliamentary strategic resolution) and NEZN (neznano) are
#: honest OTHERs; MP_* marks municipal acts (same suffix vocabulary).
#: Unseen prefixes map to OTHER, never guessed.
_PREFIX_DOC_TYPES: dict[str, str] = {
    "ZAKO": "STATUTE",
    "USTZ": "STATUTE",
    "URED": "REGULATION",
    "PRAV": "SECONDARY_LEGISLATION",
    "NAVO": "SECONDARY_LEGISLATION",
    "TARI": "SECONDARY_LEGISLATION",
    "POSL": "SECONDARY_LEGISLATION",
    "KOLP": "SECONDARY_LEGISLATION",
    "STAT": "SECONDARY_LEGISLATION",
    "ODLO": "DECREE",
    "ODLU": "DECREE",
    "SKLE": "DECREE",
    "SKLU": "DECREE",
    "ODRE": "ORDER",
    "UKAZ": "ORDER",
}

_ID_PREFIX_RE = re.compile(r"^(?:MP_)?([A-Z]+)")


def map_doc_type(pisrs_id: str) -> str:
    """Controlled doc_type for a PISRS act id (``ZAKO9575``, ``MP_PRAV9928``)."""
    match = _ID_PREFIX_RE.match(pisrs_id)
    prefix = match.group(1) if match else ""
    return _PREFIX_DOC_TYPES.get(prefix, "OTHER")


def source_url_for(pisrs_id: str) -> str:
    """The canonical, rebuildable per-act URL. Every probed act id — the
    1991 oldest and the 2026 newest alike — resolves here (sitemap
    coverage check, 2026-10-12), and no one-off parameter is involved."""
    return f"{SITE_BASE}/pregledPredpisa?id={pisrs_id}"


def objava_url_for(pdf_name: str) -> str:
    """The canonical as-published PDF address (issue-level in the bundled
    era, per-act since ZOUL 2026-03-01)."""
    return f"{API_BASE}/uradni-list/objava/{pdf_name}"


_SLUG_NON_WORD = re.compile(r"[^a-z0-9\-]+")
_SLUG_RUNS = re.compile(r"-{2,}")


def title_slug(title: str) -> str:
    """The archival site's title-slug form of an act title, as verified
    against 32/32 real acts (2026-10-12 coverage probe: state and
    municipal, punctuation-heavy titles — ``(ZPKŽP)``, ``št. 1/2020``,
    ``Münchnu`` — all resolve). Lowercase, Slovenian diacritics folded,
    every non-alphanumeric run to one hyphen."""
    t = title.lower()
    for lat, ascii_ in (("č", "c"), ("š", "s"), ("ž", "z"), ("đ", "d"), ("ć", "c")):
        t = t.replace(lat, ascii_)
    t = t.replace("(", "- ").replace(")", " -")
    return _SLUG_RUNS.sub("-", _SLUG_NON_WORD.sub("-", t)).strip("-")


def archive_url_for(slug: str, title: str) -> str:
    """The archival per-act HTML page address (pre-ZOUL acts only)."""
    return f"{ARCHIVE_BASE}/glasilo-uradni-list-rs/vsebina/{slug}/{title_slug(title)}?h="


def html_rel_path(day: str, slug: str) -> str:
    """Primary-file path of one act's archival HTML page."""
    return f"01_raw/uradnilist/html/{day[:4]}/{slug}.html"


def pdf_rel_path(day: str, pdf_name: str) -> str:
    """Storage path of one as-published gazette PDF (issue-level before
    ZOUL, per-act since)."""
    return f"01_raw/uradnilist/{day[:4]}/{pdf_name}"


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country svn --source uradnilist window=2026-09-28:2026-10-09\n"
        "  python cli.py collect --country svn --source uradnilist sync=1\n"
        "  python cli.py collect --country svn --source uradnilist window=2024-01-01:2024-03-31 scope=all\n"
        "  python cli.py status --country svn --source uradnilist"
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


def _parse_pdf(raw: str) -> str:
    pdf = raw.strip().lower()
    if pdf not in ("on", "off"):
        raise _fail(
            "pdf must be 'on' (default: pre-ZOUL acts also store the verbatim "
            "issue PDF as second carrier) or 'off' (HTML primary carrier only)"
        )
    return pdf


def _month_seeds(from_date: date, to_date: date, scope: str, pdf: str) -> list[TaskSeed]:
    """One ul_month seed per calendar month overlapping the window; the
    from/to bounds ride along so edge months only emit in-window dates."""
    seeds: list[TaskSeed] = []
    month = date(from_date.year, from_date.month, 1)
    while month <= to_date:
        seeds.append(
            TaskSeed(
                type="ul_month",
                params={
                    "month": f"{month.year:04d}-{month.month:02d}",
                    "from": from_date.isoformat(),
                    "to": to_date.isoformat(),
                    "scope": scope,
                    "pdf": pdf,
                },
            )
        )
        month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    return seeds


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")
    scope = _parse_scope(str(params.get("scope", "state")))
    pdf = _parse_pdf(str(params.get("pdf", "on")))

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
        # Never claim *today*: the day's issue may not be on the calendar
        # yet (publication happens during the day, ZOUL era per-act issues
        # can appear one by one).
        to_date = datetime.now(UTC).date() - timedelta(days=1)
        if from_date > to_date:
            return []  # already in sync — nothing due
    else:
        raise _fail("give window=FROM:TO or sync=1")

    return _month_seeds(from_date, to_date, scope, pdf)


def build_source() -> SourceDefinition:
    from adapters.base import CleanDefinition
    from adapters.svn.sources.uradnilist.clean import (
        CLEAN_VERSION,
        UradnilistCleanHandler,
    )
    from adapters.svn.sources.uradnilist.day import UlDateHandler
    from adapters.svn.sources.uradnilist.html_doc import UlHtmlHandler
    from adapters.svn.sources.uradnilist.issue_pdf import UlPdfHandler
    from adapters.svn.sources.uradnilist.month import UlMonthHandler

    return SourceDefinition(
        name="uradnilist",
        start_tasks=start_tasks,
        task_types={
            "ul_month": UlMonthHandler(),
            "ul_date": UlDateHandler(),
            "ul_html": UlHtmlHandler(),
            "ul_pdf": UlPdfHandler(),
            "uradnilist_clean": UradnilistCleanHandler(),
        },
        # Flat document-shaped gazette path (DEU/FRA/ESP/LVA precedent):
        # every act is one documents row, no cross-document persistent
        # entity — zero domain tables. The clean task targets the
        # registering task type (ul_date) and sniffs the carrier by magic
        # bytes (the ISL mixed-corpus precedent): pre-ZOUL archival HTML
        # is whitelisted to plain text; post-ZOUL PDF-primary acts answer
        # explained-empty so seeding skips them from then on. The
        # scanned-era whole-issue PDFs (1991-1994) have no text layer;
        # PDF-text cleaning is a separate country subtask (JPN/ISL
        # precedent).
        domain_schema="",
        parallel_safe=True,
        clean=CleanDefinition(
            task_type="uradnilist_clean",
            version=CLEAN_VERSION,
            targets=("ul_date",),
        ),
    )
