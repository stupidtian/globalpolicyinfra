"""The slovlex source: task-type registry, seed generation, shared helpers.

Zbierka zákonov (the Slovak Collection of Laws) via the Slov-Lex portal of
the Ministry of Justice — https://www.slov-lex.sk. Since Act 400/2015
Z. z. (sections 12/14/22) the Collection's electronic edition on Slov-Lex
IS the official gazette: free, same legal force as paper, numbered
per year, declared with a publication date. Corpus 1918–2026, 26,562
entries (probed 2026-09-08).

Capture policy (as-declared originals, plan Q1 ruling 2026-09-08,
sharpened 2026-09-15): the document is the text a publication event
produced — captured via the stable alias ``/SK/ZZ/{y}/{n}/vyhlasene_znenie``
(Vyhlásené znenie, the as-declared text; probed to exist on every
instrument and byte-identical to the dated original). The listing's own
pointer drifts to the newest consolidated version for amended laws and is
deliberately NOT followed for capture — only its effect-status fields
(ucinnyOd/ucinnyDo) ride into meta. Version history (konsolidované
znenia) is reachable as dated pages chained by their validity windows
(see the version-channel notes in the task folder).

Channels (probed 2026-09-08, no key / no session / no csrf / robots open):

* listing  GET https://api-gateway.slov-lex.sk/vyhladavanie/predpisZbierky/rozsirene
           Solr-style {numFound, start, docs}, default vyhlaseny-desc.
           Working params: rows/start/q/typPredp/rocnik/sort (date filters
           and fq are silently ignored — verified twice each).
* body     GET https://static.slov-lex.sk/static{iri}.html
           server-rendered HTML; metadata table (id="InfoTable"),
           relation tables ("Vzťahy predpisu"), full text. UTF-8 without a
           charset header — decode explicitly (the 2026-07 legacy crawl
           double-encoded all 57 files by trusting HTTP-client guessing).
* pdf      GET https://static.slov-lex.sk/pdf/SK/ZZ/{y}/{n}/ZZ_{y}_{n}_{ver}.pdf
           the legally binding version (the HTML page says so). NOTE: the
           page's own href prefix ``/static/pdf/…`` is stale and 404s; the
           live prefix is ``/pdf/…`` (download-verified twice 2026-09-08).

Task types (each = one module with ``build_request`` + ``parse``; the
one-request-per-task contract makes the PDF a task of its own, running
BEFORE the document task so ``meta.files`` can state the sibling truthfully):

===============  =====================================================
type             what one task does
===============  =====================================================
svk_list         one listing page (100 rows, vyhlaseny-desc); spawns one
                 svk_pdf per in-window instrument; a full page that has not
                 crossed the window's lower bound chains to start+100;
                 crossing it (or a short page = corpus tail) advances the
                 cursor slovlex_last_date — the "confirmed consumed" watermark
svk_pdf          one instrument's official PDF; 200 stores the file and
                 spawns svk_doc with pdf_ok=1, 404/410 (declared
                 not-found) spawns it with pdf_ok=0 — the HTML stays the
                 document, the missing PDF is recorded, not faked
svk_doc          one instrument's HTML page; cross-checks the listing row
                 (cislo / vyhlaseny / typ) against the page, parses the
                 InfoTable + relation tables + the embedded História
                 version list, emits the document + main file (+ meta.files
                 pointing at the already-written PDF); with versions=1 it
                 also spawns one svk_doc per dated version (no recursion:
                 spawns drop the flag)
===============  =====================================================

Params (key=value on the CLI)::

    window=2026-06-16:2026-07-02   closed vyhlaseny range (required, or sync=1)
    sync=1                          from = day after the kv cursor
                                    slovlex_last_date, to = yesterday (the
                                    day's issues fill in during the day)
    max_docs=200                    cap on document spawns (stops the walk
                                    too: a trial window, not a partial crawl)
    versions=1                      additionally fetch every dated version
                                    from each page's embedded História
                                    table (default 0: events only — the
                                    timeline itself lands in meta either way)
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "ALIAS_VER",
    "API_URL",
    "CURSOR_KEY",
    "PAGE_SIZE",
    "PDF_BASE",
    "STATIC_BASE",
    "alias_iri",
    "build_slovlex",
    "canonical_html_url",
    "canonical_pdf_url",
    "iri_parts",
    "list_params",
    "map_doc_type",
    "sk_date_to_iso",
    "start_tasks",
    "utc_date",
]

API_URL = "https://api-gateway.slov-lex.sk/vyhladavanie/predpisZbierky/rozsirene"
STATIC_BASE = "https://static.slov-lex.sk/static"
PDF_BASE = "https://static.slov-lex.sk/pdf"
CURSOR_KEY = "slovlex_last_date"
PAGE_SIZE = 100

#: typPredp machine name -> cross-country doc_type (the Slovak original is
#: always kept in meta.typ_predp_value; unmapped names -> OTHER, re-labelling
#: never needs a re-crawl). Probed vocabulary, 2026-09-08.
_DOC_TYPES = {
    "Zakon": "STATUTE",
    "NariadenieVlady": "REGULATION",
    "Vyhlaska": "DECREE",
    "Opatrenie": "SECONDARY_LEGISLATION",
    "Oznamenie": "ADMINISTRATIVE_NOTICE",
    "Rozhodnutie": "ADMINISTRATIVE_NOTICE",
    # Uznesenie (government resolution) crosses classes — left as OTHER.
}

#: Same mapping keyed by the Slovak word — some listing rows carry only
#: typPredp_value without the machine name (probed 2026-09-16, /SK/ZZ/2016/87).
_DOC_TYPES_BY_WORD = {
    word: _DOC_TYPES[machine]
    for machine, word in (
        ("Zakon", "Zákon"),
        ("NariadenieVlady", "Nariadenie vlády"),
        ("Vyhlaska", "Vyhláška"),
        ("Opatrenie", "Opatrenie"),
        ("Oznamenie", "Oznámenie"),
        ("Rozhodnutie", "Rozhodnutie"),
    )
}


def map_doc_type(typ_predp: str | None, typ_value: str = "") -> str:
    if typ_predp:
        return _DOC_TYPES.get(typ_predp.strip(), "OTHER")
    return _DOC_TYPES_BY_WORD.get(typ_value.strip(), "OTHER")


def list_params(start: int) -> dict[str, str]:
    """Query params for one listing page (probed shape).

    ``sort=vyhlaseny desc`` pins the order the walk logic relies on instead
    of trusting the server default (probed working with ``+``-encoded
    space, which is what the HTTP transport emits for params).
    """
    return {"rows": str(PAGE_SIZE), "start": str(start), "sort": "vyhlaseny desc"}


#: Trailing iri segment forms (probed 2026-09-15): a version's effective
#: date (yyyymmdd), or the stable alias ``vyhlasene_znenie`` — the
#: as-declared original, byte-identical to the dated original page modulo
#: the header banner and link targets (diff-verified on 16/1993; exists on
#: every law probed: fresh 2026 laws, a repealed 1993 law, an Oznámenie).
ALIAS_VER = "vyhlasene_znenie"

#: Correction entries in the Collection ("Redakčné oznámenie" errata).
_CORRECTION_NO = re.compile(r"c\d+(?:-r\d+)?$")


def iri_parts(iri: str) -> tuple[str, str, str]:
    """/SK/ZZ/2026/126/20260701 -> ("2026", "126", "20260701");

    /SK/ZZ/2025/35/vyhlasene_znenie -> ("2025", "35", "vyhlasene_znenie").
    Some listing rows carry a stray ".html" suffix on the trailing token
    (probed 2026-09-16, /SK/ZZ/2019/83/…); it is stripped before the shape
    check — normalization, not a shape change. Anything else raises.
    """
    part = iri.split("/")
    if len(part) != 6 or part[1:3] != ["SK", "ZZ"]:
        raise ValueError(f"iri {iri!r} is not /SK/ZZ/{{year}}/{{no}}/{{ver}}")
    rocnik, number, ver = part[3], part[4], part[5]
    ver = ver.removesuffix(".html")
    # The number segment is either digits (a normal instrument) or the
    # Collection's correction form c{N}-r{K} ("Redakčné oznámenie" errata,
    # probed 2026-09-16, /SK/ZZ/2015/c98-r1/…).
    if not (rocnik.isdigit() and (number.isdigit() or _CORRECTION_NO.match(number))):
        raise ValueError(f"iri {iri!r} is not /SK/ZZ/{{year}}/{{no}}/{{ver}}")
    if ver != ALIAS_VER and not (ver.isdigit() and len(ver) == 8):
        raise ValueError(f"iri {iri!r} is not /SK/ZZ/{{year}}/{{no}}/{{ver}}")
    return rocnik, number, ver


def alias_iri(rocnik: str, number: str) -> str:
    """The as-declared original's stable iri for one instrument."""
    return f"/SK/ZZ/{rocnik}/{number}/{ALIAS_VER}"


def number_segment(number: str) -> str:
    """Folder/filename segment for an instrument number: zero-padded digits
    for laws, the correction token verbatim (separate namespace)."""
    return f"{int(number):03d}" if number.isdigit() else number


def canonical_html_url(iri: str) -> str:
    """Stable, rebuildable URL of one version's page (doc_id hashes this)."""
    return f"{STATIC_BASE}{iri}.html"


def canonical_pdf_url(iri: str) -> str:
    """Official PDF of one version.

    Dated versions: ``ZZ_{y}_{n}_{ver}.pdf``. The as-declared alias carries
    its own undated PDF ``ZZ_{y}_{n}.pdf`` (probed 200 on both forms
    2026-09-08/15; the page-native ``/static/pdf`` prefix is stale — see
    module docstring).
    """
    rocnik, number, ver = iri_parts(iri)
    if ver == ALIAS_VER:
        return f"{PDF_BASE}/SK/ZZ/{rocnik}/{number}/ZZ_{rocnik}_{number}.pdf"
    return f"{PDF_BASE}/SK/ZZ/{rocnik}/{number}/ZZ_{rocnik}_{number}_{ver}.pdf"


def sk_date_to_iso(text: str) -> str | None:
    """'03.06.2026' -> '2026-06-03' (Slovak DD.MM.YYYY, first date in text)."""
    import re

    match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
    if match is None:
        return None
    day, month, year = (int(g) for g in match.groups())
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def utc_date() -> date:
    return datetime.now(UTC).date()


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country svk --source slovlex "
        "window=2026-06-16:2026-07-02\n"
        "  python cli.py collect --country svk --source slovlex sync=1\n"
        "  python cli.py status --country svk --source slovlex"
    )


def _parse_date(raw: str, label: str) -> str:
    try:
        date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None
    return raw


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
        # To yesterday, not today: the day's issues fill in during the day,
        # and a half-filled today must not become a "consumed" watermark.
        to_str = (utc_date() - timedelta(days=1)).isoformat()
    else:
        raise _fail("give window=FROM:TO or sync=1")

    if from_str > to_str:
        raise _fail(f"window start {from_str} is after its end {to_str}")

    seed_params: dict[str, Any] = {"start": 0, "from": from_str, "to": to_str}
    raw_max = str(params.get("max_docs", "")).strip()
    if raw_max:
        if not raw_max.isdigit() or int(raw_max) < 1:
            raise _fail(f"max_docs must be a positive integer (got {raw_max!r})")
        seed_params["max_docs"] = int(raw_max)
    # pdf=0 skips the PDF sibling entirely (HTML-only sweeps, e.g. the
    # 2000–2025 backfill; user ruling 2026-09-08). Default stays 1 (plan Q2).
    raw_pdf = str(params.get("pdf", "1")).strip()
    if raw_pdf not in ("0", "1"):
        raise _fail(f"pdf must be 0 or 1 (got {raw_pdf!r})")
    seed_params["pdf"] = int(raw_pdf)
    # versions=1 additionally fetches every dated version listed in each
    # page's embedded "História" table (version channel, probed
    # 2026-09-15). The version timeline itself lands in meta either way.
    raw_versions = str(params.get("versions", "0")).strip()
    if raw_versions not in ("0", "1"):
        raise _fail(f"versions must be 0 or 1 (got {raw_versions!r})")
    if raw_versions == "1":
        seed_params["versions"] = 1
    return [TaskSeed(type="svk_list", params=seed_params)]


def build_slovlex() -> SourceDefinition:
    from adapters.svk.sources.slovlex.doc import SvkDocHandler
    from adapters.svk.sources.slovlex.list import SvkListHandler
    from adapters.svk.sources.slovlex.pdf import SvkPdfHandler

    return SourceDefinition(
        name="slovlex",
        start_tasks=start_tasks,
        task_types={
            "svk_list": SvkListHandler(),
            "svk_pdf": SvkPdfHandler(),
            "svk_doc": SvkDocHandler(),
        },
    )
