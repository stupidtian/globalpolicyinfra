"""The pravo source: task-type registry and seed generation.

Russia's federally officialised legal acts, collected from the official
internet portal of legal information (pravo.gov.ru). Two systems, one key
— the 16-digit publication number (``{level 4}{YYYYMMDD}{seq 4}``, e.g.
``0001202610060001``; federal acts always start ``0001``, regional acts
carry the subject code ``XY00``):

===============  ==========================================================
system           role
===============  ==========================================================
publication.     enumeration (date-addressed day search) + document
pravo.gov.ru     identity (``/document/{number}`` page). Its only file
                 delivery is scanned PDF without a text layer — usable as
                 identity, not as machine-readable content.
actual.pravo.    the legal-text bank (successor of the old
gov.ru:8000      ips.pravo.gov.ru interface, test mode): HTML full text and
                 the version ledger, addressed by the same publication
                 number. Normative acts only — international treaties and
                 UN Security Council resolutions are not in the bank
                 (probed 2026-10-12: docid=0).
===============  ==========================================================

Task types (each = one module with ``build_request`` + ``parse``):

===============  =====================================================
type             what one task does
===============  =====================================================
pravo_day        one calendar day (and page): GET the day search;
                 every kept entry (federal by publication-number
                 prefix, court acts excluded by default) yields a
                 pravo_text. A fuller page derives the next page —
                 the *tail* page is the one that fully consumed the
                 day and moves the ``pravo_last_date`` cursor. Empty
                 days («Документы не найдены», HTTP 200) are
                 explained empties; the cursor still advances (the
                 archive's early years are sparse — that is data
                 reality, not a channel fault).
pravo_text       one document's bank lookup: GET the version ledger
                 (``redactions``); every version field goes to meta,
                 the initial (as-published) redaction seeds a
                 pravo_body. Not in the bank (treaties, UNSC
                 resolutions, not-yet-registered fresh acts, the
                 odd historical gap) = permanent "bank-miss" — the
                 repair channel (``requeue``) re-fetches later.
pravo_body       one document's text: GET ``redtext`` for the initial
                 redaction, verify the HTML envelope, register the
                 document and store the HTML verbatim as the
                 primary file.
pravo_clean      Word-exported HTML -> deterministic plain text
                 (framework html engine, keep="body").
===============  =====================================================

Params (key=value on the CLI)::

    window=2026-10-05:2026-10-07   closed date range (required, or sync=1)
    sync=1                          from = day after the kv cursor
                                    pravo_last_date, to = *yesterday*
                                    (documents appear on the portal
                                    during the Moscow working day)
    scope=federal                   keep level: federal (default,
                                    prefix 0001) | all (regional acts too)
    include_court=no                Constitutional Court acts: no
                                    (default, case law is out of scope)
                                    | yes
    types=                          comma list of doc_type values to keep
                                    (STATUTE | DECREE | ORDER | OTHER);
                                    empty = all. Filtered at the listing
                                    layer, so excluded types never cost a
                                    document request; widening later
                                    re-walks pages cheaply and re-fetches
                                    only the new types (done-skip on the
                                    rest).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from html import unescape as _html_unescape
from typing import Any

from adapters.base import CleanDefinition, SourceDefinition, TaskSeed

__all__ = [
    "BANK_API",
    "CURSOR_KEY",
    "FEDERAL_PREFIX",
    "PAGE_SIZE",
    "PORTAL_BASE",
    "build_source",
    "is_court_title",
    "map_doc_type",
    "parse_title",
    "start_tasks",
]

PORTAL_BASE = "http://publication.pravo.gov.ru"
BANK_API = "http://actual.pravo.gov.ru:8000/api/ebpi"

CURSOR_KEY = "pravo_last_date"
PAGE_SIZE = 200
FEDERAL_PREFIX = "0001"

_COURT_MARKS = ("Конституционного Суда", "конституционного суда")

_TYPE_RULES: tuple[tuple[str, str], ...] = (
    ("Федеральный конституционный закон", "STATUTE"),
    ("Федеральный закон", "STATUTE"),
    ("Закон Российской Федерации", "STATUTE"),
    ("Постановление Правительства", "DECREE"),
    ("Постановление", "OTHER"),
    ("Указ", "DECREE"),
    ("Распоряжение", "DECREE"),
    ("Приказ", "ORDER"),
)


def map_doc_type(title: str) -> str:
    """Title-native type word -> controlled doc_type (native preserved in
    meta by the callers; cross-country typology is analysis-side)."""
    stripped = title.strip()
    for prefix, doc_type in _TYPE_RULES:
        if stripped.startswith(prefix):
            return doc_type
    return "OTHER"


def is_court_title(title: str) -> bool:
    """True for Constitutional Court acts (case law — excluded by default)."""
    return any(mark in title for mark in _COURT_MARKS)


_DATE_RE = re.compile(r"от\s*(\d{2})\.(\d{2})\.(\d{4})")
_NUMBER_RE = re.compile(r"№\s*([0-9A-Za-zА-Яа-яЁё\-]+)")
_ORDER_AUTHORITY_RE = re.compile(r"^Приказ\s+(.+?)\s+от\s*\d{2}\.")


def parse_title(title: str) -> dict[str, str]:
    """Split a listing title (``< requisite >< title proper >``) into the
    research fields: doc_number, doc_date (ISO), issuing_authority. Every
    field is a plain extraction — absent means absent, never guessed."""
    out: dict[str, str] = {}
    requisite = title.split("(")[0].strip()
    m = _DATE_RE.search(requisite)
    if m:
        out["doc_date"] = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = _NUMBER_RE.search(requisite)
    if m:
        out["doc_number"] = m.group(1)
    if _ORDER_AUTHORITY_RE.match(requisite):
        out["issuing_authority"] = _ORDER_AUTHORITY_RE.match(requisite).group(1)  # type: ignore[union-attr]
    elif requisite.startswith(("Указ Президента", "Распоряжение Президента")):
        out["issuing_authority"] = "Президент Российской Федерации"
    elif requisite.startswith(
        ("Постановление Правительства", "Распоряжение Правительства")
    ):
        out["issuing_authority"] = "Правительство Российской Федерации"
    elif requisite.startswith(
        (
            "Федеральный конституционный закон",
            "Федеральный закон",
            "Закон Российской Федерации",
        )
    ):
        out["issuing_authority"] = "Федеральное Собрание Российской Федерации"
    return out


def clean_listing_title(raw: str) -> str:
    """One listing title line: ``<br />`` folds to spaces, entities
    (named and numeric — the portal mixes both) decoded, whitespace
    collapsed (the raw is server-rendered HTML)."""
    text = re.sub(r"<br\s*/?>", " ", raw)
    text = _html_unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country rus --source pravo window=2026-10-05:2026-10-07\n"
        "  python cli.py collect --country rus --source pravo sync=1\n"
        "  python cli.py collect --country rus --source pravo window=… scope=all\n"
        "  python cli.py collect --country rus --source pravo window=… include_court=yes\n"
        "  python cli.py status --country rus --source pravo"
    )


def _parse_date(raw: str, label: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None


def _parse_scope(raw: str) -> str:
    value = raw.strip().lower()
    if value not in ("federal", "all"):
        raise _fail(f"scope must be federal or all (got {raw!r})")
    return value


def _parse_include_court(raw: str) -> str:
    value = raw.strip().lower()
    if value not in ("no", "yes"):
        raise _fail(f"include_court must be no or yes (got {raw!r})")
    return value


_TYPE_CHOICES = ("STATUTE", "DECREE", "ORDER", "OTHER")


def _parse_types(raw: str) -> str:
    """Comma list of controlled doc_type values; empty = no type filter.

    The filter runs at the *listing* layer (the title's native type word is
    right there, probed stable across 2012–2026), so excluded types never
    cost a document request. Deliberately NOT carried into pravo_text
    params: widening the set later re-walks the day pages (cheap) and the
    already-captured documents keep their exact task identities —
    done-skip means widening backfills only the new types, zero re-fetch.
    """
    raw = raw.strip()
    if not raw:
        return ""
    parts = [p.strip().upper() for p in raw.split(",") if p.strip()]
    unknown = [p for p in parts if p not in _TYPE_CHOICES]
    if unknown:
        raise _fail(
            f"types must be a comma list of {', '.join(_TYPE_CHOICES)} "
            f"(unknown: {', '.join(unknown)})"
        )
    return ",".join(parts)


def _parse_content(raw: str) -> str:
    """Which downstream leg carries the document body.

    ``html`` (default): the legal-text bank full text — exists for laws,
    presidential and government acts, Constitutional Court findings.
    ``pdf``: the portal's scanned original — the only carrier for ministry
    normative acts (the bank does not carry that class at all, probed
    0/15 on 2026-10-12); scans have no text layer, so this leg preserves
    the official original, not machine-readable text. The choice rides in
    the day-task params (task identity), never in the document tasks':
    switching a class between legs later keeps the document identity and
    updates the carrier in place.
    """
    value = raw.strip().lower()
    if value not in ("html", "pdf"):
        raise _fail(f"content must be html or pdf (got {raw!r})")
    return value


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")
    scope = _parse_scope(str(params.get("scope", "federal")))
    include_court = _parse_include_court(str(params.get("include_court", "no")))
    types = _parse_types(str(params.get("types", "")))
    content = _parse_content(str(params.get("content", "html")))

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
        from_date = date.fromisoformat(str(cursor)) + timedelta(days=1)
        # Never claim *today*: documents go up during the Moscow working
        # day, so a pre-publication fetch answers the same "no documents"
        # as a genuinely empty day (FRA/ESP precedent).
        to_date = datetime.now(UTC).date() - timedelta(days=1)
        if from_date > to_date:
            return []  # already in sync — nothing due
    else:
        raise _fail("give window=FROM:TO or sync=1")

    seeds: list[TaskSeed] = []
    day = from_date
    while day <= to_date:
        seeds.append(
            TaskSeed(
                type="pravo_day",
                params={
                    "date": day.isoformat(),
                    "scope": scope,
                    "include_court": include_court,
                    "types": types,
                    "content": content,
                    # Only the window-end day's tail page writes the cursor:
                    # day seeds of one run are enqueued up front and their
                    # page chains complete interleaved, so per-day writes
                    # would be last-wins in wall-clock order and an earlier
                    # day's deeper page could overwrite the watermark
                    # backwards (observed in the first real window,
                    # 2026-10-12). One designated writer = one write.
                    "cursor_through": to_date.isoformat(),
                },
            )
        )
        day += timedelta(days=1)
    return seeds


def build_source() -> SourceDefinition:
    from adapters.rus.sources.pravo.body import PravoBodyHandler
    from adapters.rus.sources.pravo.clean import CLEAN_VERSION, PravoCleanHandler
    from adapters.rus.sources.pravo.day import PravoDayHandler
    from adapters.rus.sources.pravo.pdf import PravoPdfHandler
    from adapters.rus.sources.pravo.text import PravoTextHandler

    return SourceDefinition(
        name="pravo",
        start_tasks=start_tasks,
        task_types={
            "pravo_day": PravoDayHandler(),
            "pravo_text": PravoTextHandler(),
            "pravo_body": PravoBodyHandler(),
            "pravo_pdf": PravoPdfHandler(),
            "pravo_clean": PravoCleanHandler(),
        },
        # Flat gazette corpus: publication is one-shot, the publication
        # number is the whole identity, no cross-document entity exists.
        # Word-exported HTML -> plain text over the keep="body" whitelist
        # (probed 2026-10-12 on the 2012-02-29 federal law sample: clean
        # Russian text, zero CSS leakage, byte-for-byte deterministic).
        # Cleaning targets the HTML leg only: the PDF leg carries scanned
        # originals with no text layer (OCR is out of scope).
        clean=CleanDefinition(
            task_type="pravo_clean",
            version=CLEAN_VERSION,
            targets=("pravo_body",),
        ),
        parallel_safe=True,
    )
