"""Task types ``bek_day`` and ``bek_year``: SRU enumeration, two axes.

Two enumeration entries over the same SRU endpoint, converging at the
identity layer (same identifier → same doc → done-skip; the
multi-entry-one-funnel pattern of ARCHITECTURE.md §6.5):

- ``bek_day`` — the **increment axis**: one (date, blad) searchRetrieve
  with ``dt.issued==date`` scoped to the publication's content-area. One
  task per calendar day; drives the ``bek_last_date`` cursor.
- ``bek_year`` — the **backfill/sweep axis**: one (year, blad)
  searchRetrieve over the whole content-area year, paged. Exists because
  the day axis structurally misses cross-year verbeterbladen: a corrected
  reprint of a 2007 sheet is issued in January 2008 but lives in
  content-area ``stb/2007`` — the day query for 2008-01-22 scopes to
  ``stb/2008`` and never sees it (found in the 2000-2025 backfill,
  2026-09-30: ~89 records, all concentrated in January). The year axis
  has no date filter and therefore catches them; it never moves the
  cursor (a completed sweep is discovery, not increment consumption).

Probed behaviours shared by both (2026-09-29, samples in the probe
folder):

- The API answers HTTP 200 even when nothing matches
  (``numberOfRecords=0``) — unlike BOE there is no 404 no-edition shape,
  so nothing needs an ``accept_not_found`` declaration. A zero-record
  day/year is an explained empty.
- Issue numbers are not contiguous (stb-2026: 290 exists, 294-296 don't,
  298 records in the year) — enumeration is strictly API-driven.
- ``startRecord`` paging works; both handlers chain to the next page when
  ``numberOfRecords`` exceeds the page window (a day of Staatsblad is
  single-digit counts, a year is 450-1000 — only the year axis pages in
  practice).
- A record with an xml manifestation spawns one ``bek_item``, its SRU
  metadata riding along in the task params — no second metadata request.
  A record without one (scan era, pre-1995) registers a metadata-only
  document right here: the ledger row carries the pdf link in meta, the
  missing full text is an honest documented gap, not a failure (same
  shape ESP uses for its 1961-1989 scan era).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.nld.sources.bekendmakingen import (
    CURSOR_KEY,
    PAGE_SIZE,
    SRU_BASE,
    map_doc_type,
)
from core.document import DocumentRecord

__all__ = ["SRU_NS", "BekDayHandler", "BekYearHandler", "record_fields"]

SRU_NS = {
    "sru": "http://docs.oasis-open.org/ns/search-ws/sruResponse",
    "gzd": "http://standaarden.overheid.nl/sru",
    "dcterms": "http://purl.org/dc/terms/",
    "ow": "http://standaarden.overheid.nl/wetgeving/",
    "c": "http://standaarden.overheid.nl/collectie/",
}


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def _manifestation(enriched: ET.Element | None, kind: str) -> str:
    if enriched is None:
        return ""
    for url in enriched.findall("gzd:itemUrl", SRU_NS):
        if (url.get("manifestation") or "").strip() == kind:
            return _text(url)
    return ""


def record_fields(record: ET.Element) -> dict[str, str]:
    """Flatten one ``sru:record`` into the string fields the pack uses.

    Metadata comes from the record itself (``gzd:originalData`` — the
    Dublin-Core blocks) plus the manifestation URLs from
    ``gzd:enrichedData``. Empty values are dropped: task params are part
    of the task identity and only stable values travel in them.
    """
    gzd = record.find("sru:recordData/gzd:gzd", SRU_NS)
    if gzd is None:
        raise ValueError("SRU record without a gzd:gzd recordData block")
    orig = gzd.find("gzd:originalData/ow:meta", SRU_NS)
    enriched = gzd.find("gzd:enrichedData", SRU_NS)

    fields: dict[str, str] = {}
    for block, tags in (
        (
            "ow:owmskern",
            ("dcterms:identifier", "dcterms:title", "dcterms:language", "dcterms:creator"),
        ),
        ("ow:owmsmantel", ("dcterms:issued", "dcterms:publisher")),
    ):
        node = orig.find(block, SRU_NS) if orig is not None else None
        for tag in tags:
            fields[tag] = _text(node.find(tag, SRU_NS)) if node is not None else ""
    # The native type word (Wet/AMvB/…) sits in a scheme-carrying
    # dcterms:type; the record may repeat the element across schemes.
    kern = orig.find("ow:owmskern", SRU_NS) if orig is not None else None
    fields["dcterms:type"] = ""
    if kern is not None:
        for type_el in kern.findall("dcterms:type", SRU_NS):
            word = _text(type_el)
            if word:
                fields["dcterms:type"] = word
                break
    tpm = orig.find("ow:tpmeta", SRU_NS) if orig is not None else None
    for tag in (
        "ow:behandeldDossier",
        "ow:datumOndertekening",
        "ow:jaargang",
        "ow:publicatienaam",
        "ow:publicatienummer",
        "c:content-area",
    ):
        fields[tag] = _text(tpm.find(tag, SRU_NS)) if tpm is not None else ""

    for key, value in (
        ("preferred_url", _text(enriched.find("gzd:preferredUrl", SRU_NS)) if enriched is not None else ""),
        ("xml_url", _manifestation(enriched, "xml")),
        ("pdf_url", _manifestation(enriched, "pdf")),
        ("html_url", _manifestation(enriched, "html")),
    ):
        if value:
            fields[key] = value
    return {k: v for k, v in fields.items() if v}


def _sru_envelope(response: Response, label: str) -> tuple[int, list[ET.Element]]:
    """Validate the SRU envelope; return (numberOfRecords, records).

    Raises on non-XML bodies, unknown roots, SRU diagnostics, a missing
    numberOfRecords, and a records block empty while total claims rows.
    """
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        raise ValueError(f"{label}: body is not XML: {exc}") from exc
    if root.tag != f"{{{SRU_NS['sru']}}}searchRetrieveResponse":
        raise ValueError(f"{label}: unexpected root {root.tag!r}")

    diagnostics = root.find("sru:diagnostics", SRU_NS)
    if diagnostics is not None:
        raise ValueError(
            f"{label}: SRU diagnostic — "
            f"{_text(diagnostics.find('.//sru:message', SRU_NS)) or 'unknown error'}"
        )
    total_raw = _text(root.find("sru:numberOfRecords", SRU_NS))
    if not total_raw.isdigit():
        raise ValueError(f"{label}: numberOfRecords missing/unreadable ({total_raw!r})")
    total = int(total_raw)
    if total == 0:
        return 0, []

    records = root.findall("sru:records/sru:record", SRU_NS)
    if not records:
        raise ValueError(
            f"{label}: numberOfRecords={total} but the records block is empty "
            "— page window past the end or shape change"
        )
    return total, records


def _harvest(
    records: list[ET.Element], label: str
) -> tuple[list[TaskSeed], list[DocumentRecord]]:
    """Turn SRU records into bek_item seeds and metadata-only documents.

    Records without an xml manifestation (scan era) register directly as
    metadata-only documents — see module docstring.
    """
    next_tasks: list[TaskSeed] = []
    documents: list[DocumentRecord] = []
    for record in records:
        f = record_fields(record)
        identifier = f.get("dcterms:identifier", "")
        issued = f.get("dcterms:issued", "")
        if not identifier or not issued:
            raise ValueError(
                f"{label}: a record carries no identifier/issued ({sorted(f)})"
            )
        meta = {
            "identifier": identifier,
            "native_type": f.get("dcterms:type", ""),
            "creator": f.get("dcterms:creator", ""),
            "publisher": f.get("dcterms:publisher", ""),
            "datum_ondertekening": f.get("ow:datumOndertekening", ""),
            "behandeld_dossier": f.get("ow:behandeldDossier", ""),
            "jaargang": f.get("ow:jaargang", ""),
            "publicatienaam": f.get("ow:publicatienaam", ""),
            "publicatienummer": f.get("ow:publicatienummer", ""),
            "content_area": f.get("c:content-area", ""),
            "preferred_url": f.get("preferred_url", ""),
            "xml_url": f.get("xml_url", ""),
            "pdf_url": f.get("pdf_url", ""),
            "html_url": f.get("html_url", ""),
        }
        meta = {k: v for k, v in meta.items() if v}
        if not f.get("xml_url"):
            # Scan era (pre-1995 Staatsblad): no full text exists —
            # register the publication as a metadata-only document,
            # pdf_url already in meta.
            meta["scan_era"] = "true"
            documents.append(
                DocumentRecord(
                    title=f.get("dcterms:title", "") or identifier,
                    source_url=meta.get(
                        "preferred_url",
                        f"https://zoek.officielebekendmakingen.nl/{identifier}.html",
                    ),
                    publication_date=issued,
                    issuing_authority=meta.get("creator") or None,
                    doc_type=map_doc_type(meta.get("native_type", "")),
                    language="nld",
                    raw_metadata=meta,
                )
            )
        else:
            params: dict[str, str] = {
                "id": identifier,
                "issued": issued,
                "title": f.get("dcterms:title", "") or identifier,
            }
            for key in (
                "native_type",
                "creator",
                "publisher",
                "datum_ondertekening",
                "behandeld_dossier",
                "jaargang",
                "publicatienaam",
                "publicatienummer",
                "content_area",
                "preferred_url",
                "xml_url",
                "pdf_url",
                "html_url",
            ):
                if key in meta:
                    params[key] = meta[key]
            next_tasks.append(TaskSeed(type="bek_item", params=params))
    return next_tasks, documents


def _chain_page(total: int, start: int, task_type: str, params: dict[str, Any]) -> list[TaskSeed]:
    """Next-page seed when total rows exceed the served window."""
    if total <= start + PAGE_SIZE - 1:
        return []
    return [TaskSeed(type=task_type, params={**params, "start_record": start + PAGE_SIZE})]


def _build_request(query: str, start: int) -> RequestSpec:
    params: dict[str, Any] = {
        "operation": "searchRetrieve",
        "version": "2.0",
        "query": query,
        "maximumRecords": str(PAGE_SIZE),
    }
    if start > 1:
        params["startRecord"] = str(start)
    return RequestSpec(url=SRU_BASE, params=params)


class BekDayHandler:
    """Increment axis: one calendar day, drives the bek_last_date cursor."""

    def build_request(self, task: TaskView) -> RequestSpec:
        day = str(task.params["date"])
        blad = str(task.params["blad"])
        query = (
            'c.product-area=="officielepublicaties" AND '
            f'c.content-area=="officielepublicaties/{blad}/{day[:4]}" AND '
            f'dt.issued=="{day}"'
        )
        return _build_request(query, int(task.params.get("start_record", 1)))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        day = str(task.params["date"])
        blad = str(task.params["blad"])
        start = int(task.params.get("start_record", 1))
        total, records = _sru_envelope(response, f"bek_day {day}/{blad}")

        if total == 0:
            return TaskResult(
                expected_empty=f"no {blad} publications issued on {day} "
                "(SRU answers 200 with numberOfRecords=0)",
                cursor_updates={CURSOR_KEY: day},
            )

        next_tasks, documents = _harvest(records, f"bek_day {day}/{blad}")
        next_tasks += _chain_page(
            total, start, "bek_day", {"date": day, "blad": blad}
        )
        return TaskResult(
            next_tasks=next_tasks,
            documents=documents,
            cursor_updates={CURSOR_KEY: day},
            expected_empty=None
            if (next_tasks or documents)
            else f"records on {day} yielded no items and no documents",
        )


class BekYearHandler:
    """Sweep axis: one content-area year, no date filter, no cursor.

    Catches what the day axis cannot see — records whose issued year
    differs from their content-area year (cross-year verbeterbladen,
    late-registered sheets). Converges with bek_day at the identity
    layer: the identifier is the same, done tasks skip.
    """

    def build_request(self, task: TaskView) -> RequestSpec:
        year = str(task.params["year"])
        blad = str(task.params["blad"])
        query = (
            'c.product-area=="officielepublicaties" AND '
            f'c.content-area=="officielepublicaties/{blad}/{year}"'
        )
        return _build_request(query, int(task.params.get("start_record", 1)))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        year = str(task.params["year"])
        blad = str(task.params["blad"])
        start = int(task.params.get("start_record", 1))
        total, records = _sru_envelope(response, f"bek_year {year}/{blad}")

        if total == 0:
            return TaskResult(
                expected_empty=f"no {blad} records in the {year} content-area "
                "(SRU answers 200 with numberOfRecords=0)"
            )

        next_tasks, documents = _harvest(records, f"bek_year {year}/{blad}")
        next_tasks += _chain_page(
            total, start, "bek_year", {"year": year, "blad": blad}
        )
        return TaskResult(
            next_tasks=next_tasks,
            documents=documents,
            expected_empty=None
            if (next_tasks or documents)
            else f"records in {year}/{blad} yielded no items and no documents",
        )
