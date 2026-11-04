"""The elperuano source: task-type registry, seed generation, shared parsing.

Diario Oficial El Peruano (https://elperuano.pe, published by the state
printer Editora Perú, founded 1825) — Peru's official gazette. Normative
content runs in the daily **Normas Legales** supplement (plus the
occasional Edición Extraordinaria); this pack collects those norms from
1997-07 onward (~350-400k items estimated; probed 2026-10-31, see
docs/countries/per/elperuano-zh.md). SPIJ, the Ministry of Justice's free
consolidated register, is unreachable from this network (TCP timeouts on
both methods while other .pe government hosts answered) — recorded as a
gap, not a blocker.

Three hosts, all key-free, session-free, plain HTTP:

- ``diariooficial.elperuano.pe`` — the ASP.NET legacy portal: one POST
  (``Normas/Filtro``, form fields ``cddesde``/``cdhasta`` dd/MM/yyyy) per
  day returns that day's norms as an HTML fragment (one ``<article>`` per
  norm: h4 issuing authority, h5 official designation + link, date line,
  sumilla). The per-norm identity (``data-id``) sits inside a *commented
  out* button inside each article — comments must be read, elements
  alone miss it.
- ``busquedas.elperuano.pe`` — the 2023-09 search portal: one SSR device
  page per norm with the full text embedded (``div#visor-html`` wrapping
  a complete XHTML document). Its norm search only reaches back to
  2023-09, so enumeration always runs through the daily POST.
- ``epdoc2.elperuano.pe`` — file delivery: whole-edition PDFs
  (``Descarga.asp?Referencias=base64("{CODE}{YYYYMMDD}")``) and one-norm
  special-supplement PDFs (``VistaNLSE.asp``).

Two carrier eras, decided **per entry by link shape** (never by date —
the switchover sits between 2023-08 and 2023-09):

- legacy entries link the whole-edition PDF (all of a day's norms in one
  file); the per-norm PDF endpoint returns malformed-encrypted PDFs that
  pypdf/pymupdf/pypdfium2 all refuse — so the edition file is the only
  carrier and every norm document of that day shares it;
- portal-era entries link a per-norm device page; occasional
  extraordinary norms instead link a single-norm "SEPARATA ESPECIAL" PDF.

Task types (each = one module with ``build_request`` + ``parse``):

=================  =====================================================
type               what one task does
=================  =====================================================
per_day_list       one calendar day's POST listing; legacy entries are
                   registered immediately (metadata is complete there)
                   and grouped into one ``per_day_edition`` per edition
                   PDF; portal entries spawn one ``per_norm_detail``
                   each. A no-edition day is an explained empty and the
                   watermark still advances.
per_day_edition    one whole-edition PDF; writes the file once per day
                   and attaches it to every norm document of that day
                   (one FileOut per doc_id, same path — the gazette's
                   as-published shape).
per_norm_detail    one device-page HTML or special-supplement PDF;
                   registers the document and stores the response
                   verbatim as the primary file.
per_clean          local read: device HTML -> embedded visor text;
                   supplement PDF -> geometry channel (scans fail
                   loud, OCR out of scope). Whole editions are not
                   cleaned — per-norm text inside a combined issue
                   needs page-boundary segmentation, deferred.
=================  =====================================================

Params (key=value on the CLI)::

    window=2000-01-01:2000-01-10          closed range(s); comma
    window=2000-01-01:2000-01-10,2026-10-26:2026-10-30   multi-range
    sync=1        from = day after the kv cursor, to = *yesterday*
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "CURSOR_KEY",
    "FILTER_URL",
    "build_source",
    "edition_pdf_path",
    "edition_ref_parts",
    "map_doc_type",
    "old_source_url",
    "parse_day_listing",
    "start_tasks",
]

FILTER_URL = "https://diariooficial.elperuano.pe/Normas/Filtro"
PORTAL_BASE = "https://busquedas.elperuano.pe"
#: Canonical rebuildable anchor for a legacy-era norm: the day's edition
#: viewer on the new portal plus the per-norm data-id as a fragment (the
#: fragment keeps doc_ids distinct when a day carries repeated
#: designations — doc_id hashes this string whole).
CUADERNILLO_BASE = f"{PORTAL_BASE}/cuadernillo"
CURSOR_KEY = "elperuano_last_date"

_DEVICE_MARK = "busquedas.elperuano.pe/dispositivo/"
_SEPARATA_MARK = "VistaNLSE.asp"
_EDITION_MARK = "epdoc2.elperuano.pe/EpPo/Descarga.asp"

_EDITION_REF = re.compile(r"Referencias=([A-Za-z0-9+/=]+)")
_EDITION_CODE = re.compile(r"^([A-Z]+)(\d{8})$")
_ANNEX_REF = re.compile(r"Referencias=([A-Za-z0-9+/=]+)")
#: {norm_id}-{part}{YYYYMMDD} — the part keeps the norm id's own hyphen
#: (2568392-2 20261028), so the split takes only the trailing date.
_ANNEX_TAIL = re.compile(r"^(?P<part>.+?)(?P<ymd>\d{8})$")
_COMMENT_BLOCK = re.compile(
    r'data-id="(?P<data_id>[^"]+)"'
    r'.*?data-fecha="(?P<fecha>\d{8})"'
    r'.*?data-url="(?P<url>[^"]+)"',
    re.DOTALL,
)

_RAW_ROOT = "01_raw/elperuano"

#: Official-designation prefix -> soft doc_type (the native string always
#: travels in meta.designation; cross-country typology is analysis-side).
#: Matching strips accents and runs longest-prefix-first.
_TYPE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("DECRETO LEGISLATIVO", "STATUTE"),
    ("LEY", "STATUTE"),
    ("DECRETO SUPREMO", "DECREE"),
    ("DECRETO DE URGENCIA", "DECREE"),
    ("DECRETO", "DECREE"),
    ("RESOLUCION", "SECONDARY_LEGISLATION"),
    ("REGLAMENTO", "SECONDARY_LEGISLATION"),
    ("ORDENANZA", "SECONDARY_LEGISLATION"),
    ("DIRECTIVA", "SECONDARY_LEGISLATION"),
    ("CIRCULAR", "SECONDARY_LEGISLATION"),
    ("MANUAL", "SECONDARY_LEGISLATION"),
)


def map_doc_type(designation: str) -> str:
    """Official designation -> soft doc_type (Spanish original kept in
    meta.designation)."""
    folded = (
        designation.upper()
        .replace("Á", "A").replace("É", "E").replace("Í", "I")
        .replace("Ó", "O").replace("Ú", "U").replace("Ü", "U")
    )
    for prefix, doc_type in _TYPE_PREFIXES:
        if folded.startswith(prefix):
            return doc_type
    return "OTHER"


@dataclass(frozen=True)
class ListingEntry:
    """One norm as the daily listing describes it.

    ``annex_ids`` collects the article's auxiliary part files (TUPA and
    the like): commented buttons pointing at ``DescargaIN.asp`` whose
    reference decodes to ``{norm_id}-{part}{YYYYMMDD}`` — sibling parts
    of the SAME norm (the gazette publishes them as extra PDFs next to
    the norm's own). Recorded in meta, not fetched."""

    authority: str
    designation: str
    sumilla: str
    link: str
    extraordinary: bool
    data_id: str
    data_url: str
    data_fecha: str
    annex_ids: tuple[str, ...] = ()


def parse_day_listing(content: bytes, date_iso: str) -> list[ListingEntry]:
    """Parse one day's Filtro response into entries.

    Every article must yield exactly one commented identity block
    (``data-id``/``data-fecha``/``data-url``) — zero or several is a
    shape mutation and dies loud (the identity fragment is what keeps
    same-day duplicates distinct in doc_id). The printed ``Fecha`` must
    equal the requested day.
    """
    from bs4 import BeautifulSoup, Comment, Tag

    soup = BeautifulSoup(content, "html.parser")
    articles = soup.select("article.edicionesoficiales_articulos")
    if not articles:
        if b"<h5" in content:
            raise ValueError(
                f"daily listing {date_iso}: no <article> entries but the body "
                "carries norm headings — unknown page shape"
            )
        return []

    entries: list[ListingEntry] = []
    for article in articles:
        assert isinstance(article, Tag)
        text_box = article.select_one("div.ediciones_texto")
        if text_box is None:
            raise ValueError(f"daily listing {date_iso}: an article has no text block")
        heading_el = text_box.find("h4")
        authority = heading_el.get_text(" ", strip=True) if heading_el is not None else ""
        heading = text_box.find("h5")
        if heading is None:
            raise ValueError(f"daily listing {date_iso}: an article has no h5 designation")
        designation = heading.get_text(" ", strip=True)
        link_el = heading.find("a")
        if link_el is None or not link_el.get("href"):
            raise ValueError(
                f"daily listing {date_iso}: designation {designation!r} carries no link"
            )
        link = str(link_el["href"]).strip()

        paragraphs = text_box.find_all("p", recursive=False)
        date_line = paragraphs[0].get_text(" ", strip=True) if paragraphs else ""
        sumilla = paragraphs[1].get_text(" ", strip=True) if len(paragraphs) > 1 else ""
        match = re.search(r"Fecha:\s*(\d{2})/(\d{2})/(\d{4})", date_line)
        if match is None:
            raise ValueError(
                f"daily listing {date_iso}: article {designation!r} carries no "
                f"'Fecha: dd/mm/yyyy' line (got {date_line!r})"
            )
        printed = date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        if printed.isoformat() != date_iso:
            raise ValueError(
                f"daily listing {date_iso}: article {designation!r} is dated "
                f"{printed.isoformat()} — the listing disagrees with the requested day"
            )

        identities = [
            c
            for c in article.find_all(string=lambda s: isinstance(s, Comment))
            if "data-id=" in c
        ]
        # One article = one norm. Its identity block points at the whole
        # edition (Descarga.asp); further blocks point at the norm's own
        # annex parts (DescargaIN.asp, "Descargar TUPA" et al.) — same
        # data-id, sibling part numbers. Seen from 2026-10-28 on.
        primary = [c for c in identities if "DescargaIN.asp" not in str(c)]
        annex_blocks = [c for c in identities if "DescargaIN.asp" in str(c)]
        if len(primary) != 1:
            raise ValueError(
                f"daily listing {date_iso}: article {designation!r} carries "
                f"{len(primary)} commented identity blocks (expected exactly 1)"
            )
        block = _COMMENT_BLOCK.search(str(primary[0]))
        if block is None:
            raise ValueError(
                f"daily listing {date_iso}: the identity comment of "
                f"{designation!r} lost its data-id/data-fecha/data-url shape"
            )
        annex_ids: list[str] = []
        for annex in annex_blocks:
            ref = _ANNEX_REF.search(str(annex))
            if ref is None:
                raise ValueError(
                    f"daily listing {date_iso}: annex button of {designation!r} "
                    "carries no decodable Referencias"
                )
            try:
                decoded = base64.b64decode(ref.group(1), validate=True).decode("ascii")
            except (binascii.Error, UnicodeDecodeError) as exc:
                raise ValueError(
                    f"daily listing {date_iso}: annex button of {designation!r}: "
                    f"undecodable Referencias ({exc})"
                ) from None
            split = _ANNEX_TAIL.match(decoded)
            if split is None:
                raise ValueError(
                    f"daily listing {date_iso}: annex reference {decoded!r} of "
                    f"{designation!r} does not end in an 8-digit date"
                )
            annex_ids.append(split.group("part"))
        entries.append(
            ListingEntry(
                authority=authority,
                designation=designation,
                sumilla=sumilla,
                link=link,
                extraordinary="Extraordinaria" in date_line,
                data_id=block.group("data_id").strip(),
                data_url=block.group("url").strip(),
                data_fecha=block.group("fecha").strip(),
                annex_ids=tuple(annex_ids),
            )
        )
    return entries


def era_of(entry: ListingEntry) -> str:
    """Carrier era by link shape: ``device`` | ``separata`` | ``edition``.

    Anything else is a shape the corpus has not shown — loud, never
    guessed (an unrecognized link means the switchover moved or a third
    carrier appeared; both deserve eyes)."""
    if _DEVICE_MARK in entry.link:
        return "device"
    if _SEPARATA_MARK in entry.link:
        return "separata"
    if _EDITION_MARK in entry.link:
        return "edition"
    raise ValueError(f"entry {entry.designation!r}: unrecognized link shape {entry.link!r}")


def edition_ref_parts(data_url: str) -> tuple[str, str]:
    """An epdoc2 URL -> ``(edition_code, yyyymmdd)`` — e.g. the
    Referencias ``base64('NL20000101')`` gives ``('NL', '20000101')``."""
    match = _EDITION_REF.search(data_url)
    if match is None:
        raise ValueError(f"edition URL {data_url!r} carries no Referencias")
    try:
        decoded = base64.b64decode(match.group(1), validate=True).decode("ascii")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError(f"edition URL {data_url!r}: undecodable Referencias ({exc})") from None
    code = _EDITION_CODE.match(decoded)
    if code is None:
        raise ValueError(
            f"edition URL {data_url!r}: decoded reference {decoded!r} is not "
            "'CODE + YYYYMMDD' (e.g. NL20000101)"
        )
    return code.group(1), code.group(2)


def old_source_url(edition_code: str, ymd: str, data_id: str) -> str:
    """Canonical rebuildable URL of one legacy-era norm (doc_id basis)."""
    return f"{CUADERNILLO_BASE}/{edition_code}/{ymd}#{data_id}"


def edition_pdf_path(edition_code: str, ymd: str) -> str:
    return f"{_RAW_ROOT}/editions/{ymd[:4]}/{edition_code}{ymd}.pdf"


def device_file_path(data_id: str, suffix: str) -> str:
    return f"{_RAW_ROOT}/dispositivo/{data_id[:3]}/{data_id}.{suffix}"


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country per --source elperuano window=2026-10-26:2026-10-30\n"
        "  python cli.py collect --country per --source elperuano "
        "window=2000-01-01:2000-01-10,2026-10-26:2026-10-30\n"
        "  python cli.py collect --country per --source elperuano sync=1\n"
        "  python cli.py status --country per --source elperuano"
    )


def _parse_windows(raw: str) -> list[tuple[date, date]]:
    windows: list[tuple[date, date]] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        from_str, sep, to_str = token.partition(":")
        if not sep or not from_str or not to_str:
            raise _fail(f"window token {token!r} must look like FROM:TO (ISO dates)")
        try:
            from_date = date.fromisoformat(from_str.strip())
            to_date = date.fromisoformat(to_str.strip())
        except ValueError:
            raise _fail(f"window token {token!r} carries non-ISO dates") from None
        if from_date > to_date:
            raise _fail(f"window token {token!r} starts after it ends")
        windows.append((from_date, to_date))
    if not windows:
        raise _fail('window must look like FROM:TO, comma-separated for several')
    return windows


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")
    if params.get("window"):
        windows = _parse_windows(str(params["window"]))
    elif is_sync:
        kv = params.get("_kv", {})
        cursor = kv.get(CURSOR_KEY)
        if not cursor:
            raise _fail("sync=1 needs a previous sweep; run an initial window=… first")
        from_date = date.fromisoformat(str(cursor)) + timedelta(days=1)
        # Never claim *today*: the supplement can be published
        # Lima-morning or arrive later as an extraordinary edition, and a
        # pre-publication fetch answers the same empty template as a
        # no-edition day (ESP/FRA precedent).
        to_date = datetime.now(UTC).date() - timedelta(days=1)
        if from_date > to_date:
            return []  # already in sync — nothing due
        windows = [(from_date, to_date)]
    else:
        raise _fail("give window=FROM:TO or sync=1")

    seeds: list[TaskSeed] = []
    for from_date, to_date in windows:
        day = from_date
        while day <= to_date:
            seeds.append(TaskSeed(type="per_day_list", params={"date": day.isoformat()}))
            day += timedelta(days=1)
    return seeds


def build_source() -> SourceDefinition:
    from adapters.base import CleanDefinition
    from adapters.per.sources.elperuano.clean import CLEAN_VERSION, PerCleanHandler
    from adapters.per.sources.elperuano.detail import PerNormDetailHandler
    from adapters.per.sources.elperuano.edition import PerDayEditionHandler
    from adapters.per.sources.elperuano.enumerate import PerDayListHandler

    return SourceDefinition(
        name="elperuano",
        start_tasks=start_tasks,
        task_types={
            "per_day_list": PerDayListHandler(),
            "per_day_edition": PerDayEditionHandler(),
            "per_norm_detail": PerNormDetailHandler(),
            "per_clean": PerCleanHandler(),
        },
        # Gazette-shaped corpus: a norm is published once and never
        # revisited, so no cross-document persistent entity exists — zero
        # domain tables, documents is the whole ledger (DEU BGBl / FRA
        # JORF form, section 6.4 judgment).
        domain_schema="",
        domain_tables=(),
        domain_keys={},
        # All three hosts answer bare stateless HTTP (probed 2026-10-31
        # with a cookie-free client) — safe on any worker with any session
        # (framework-concurrency ruling 1.4).
        parallel_safe=True,
        # Cleaning covers the portal-era carriers only: documents produced
        # by per_norm_detail (device HTML + single-norm supplement PDFs).
        # Legacy whole editions (produced_by per_day_list) are never
        # cleaned — per-norm text inside a combined issue needs
        # page-boundary segmentation, a separate effort.
        clean=CleanDefinition(
            task_type="per_clean",
            version=CLEAN_VERSION,
            targets=("per_norm_detail",),
        ),
    )
