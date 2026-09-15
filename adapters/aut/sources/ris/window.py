"""Task type ``bgbl_window``: one month-aligned window of the gazette.

GET the ``Bundesrecht`` search on the OGD RIS API and turn every entry
into a document record (metadata lives *only* in the search response —
the entry XML carries an empty ``<metadaten/>`` block) plus one
``bgbl_file`` seed. Probed behaviours shape this handler (2026-09-13/14,
samples in the task archive):

- ``OgdDocumentReference`` arrives as a list, a bare dict (single hit),
  or not at all (zero hits — HTTP 200, a normal no-publication window);
- ``Dokumentliste.ContentReference`` likewise arrives as dict or list;
  exactly one referenced file has ``DataType="Xml"`` — the primary
  artifact of this pack. A window entry without an XML URL is an
  unexplained shape and fails loud;
- the window date filter is verified per entry (publication date within
  [von, bis]): the API ignores unknown parameter spellings silently (the
  old code's failure), so an out-of-range date means the filter did not
  take effect and everything else is suspect;
- a window counts as fully consumed when page_number × page_size ≥ total
  hits — only then does the watermark advance (a partial page fetch must
  not claim the tail of the window);
- the response's own ``Technisch.Applikation`` must match the requested
  one (a mismatched era would silently mix two metadata vocabularies).
"""

from __future__ import annotations

from typing import Any

from adapters.aut.sources.ris import (
    API_BASE,
    APPL_PDF,
    CURSOR_KEY,
    FILE_BASE,
    PAGE_SIZE,
    window_query,
)
from adapters.base import (
    RequestSpec,
    Response,
    TaskResult,
    TaskSeed,
    TaskView,
)
from core.document import DocumentRecord

__all__ = ["BgblWindowHandler", "map_doc_type"]

#: native BgblAuth/BgblPdf ``Typ`` -> controlled doc_type (native word always
#: kept in meta; cross-country typology is analysis-side, not collection-side).
_DOC_TYPE_MAP: dict[str, str] = {
    "Gesetz": "STATUTE",
    "Verordnung": "REGULATION",
}


def map_doc_type(native_type: str) -> str:
    return _DOC_TYPE_MAP.get(native_type.strip(), "OTHER")


def _as_list(value: Any) -> list[dict[str, Any]]:
    """The API collapses single-element arrays into bare dicts."""
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    raise ValueError(f"unexpected shape {type(value).__name__}: {value!r}")


def _xml_url(entry: dict[str, Any], application: str, native_id: str) -> str:
    """The entry's XML url. Scan-era entries (BgblPdf) sometimes omit the
    Xml reference from their Dokumentliste while the file itself exists at
    the canonical path (verified 2026-09-14 on 2003_312_2, June 2003: the
    constructed url answers 200 with full OCR text) — so a missing
    reference is not an anomaly; the canonical form is constructed then."""
    dokumentliste = entry["Data"].get("Dokumentliste")
    if not isinstance(dokumentliste, dict):
        raise TypeError(f"entry Dokumentliste is {type(dokumentliste).__name__}, not a dict")
    canonical = f"{FILE_BASE}/{application}/{native_id}/{native_id}.xml"
    references = _as_list(dokumentliste.get("ContentReference"))
    formats: list[str] = []
    for reference in references:
        if not isinstance(reference, dict):
            raise TypeError(f"unexpected ContentReference shape: {reference!r}")
        # ContentUrl collapses to a bare dict when it holds a single URL.
        for content_url in _as_list(reference.get("Urls", {}).get("ContentUrl", [])):
            if not isinstance(content_url, dict):
                raise TypeError(
                    f"unexpected ContentUrl item shape: {content_url!r}"
                )
            formats.append((content_url.get("DataType") or "").strip())
            if (content_url.get("DataType") or "").strip() == "Xml":
                url = str(content_url.get("Url") or "").strip()
                if url:
                    return url
    if application == APPL_PDF:
        return canonical
    raise ValueError(
        f"entry carries no Xml content url (formats: {formats})"
    )


def _block(bundesrecht: dict[str, Any], application: str) -> dict[str, Any]:
    if application not in bundesrecht:
        raise ValueError(
            f"search response carries no {application} metadata block "
            f"(found: {[k for k in bundesrecht if k not in ('Titel', 'Kurztitel', 'Eli')]})"
        )
    block: dict[str, Any] = bundesrecht[application]
    return block


def _entry_metadata(
    entry: dict[str, Any], application: str, von: str, bis: str
) -> dict[str, Any]:
    """Flatten one search hit into the fields this pack records."""
    data = entry["Data"]
    technisch = data["Metadaten"]["Technisch"]
    if (technisch.get("Applikation") or "").strip() != application:
        raise ValueError(
            f"entry {technisch.get('ID')!r} belongs to application "
            f"{technisch.get('Applikation')!r}, not the requested {application!r}"
        )

    bundesrecht = data["Metadaten"]["Bundesrecht"]
    block = _block(bundesrecht, application)
    if application == "BgblAuth":
        pub = (block.get("Ausgabedatum") or "").strip()
    else:
        pub = (block.get("Kundmachungsdatum") or "").strip()
    if not pub:
        raise ValueError(f"entry {technisch.get('ID')!r} carries no publication date")
    if not (von <= pub <= bis):
        raise ValueError(
            f"entry {technisch.get('ID')!r} published {pub} outside the window "
            f"[{von}, {bis}] — the date filter did not take effect"
        )

    meta_fields: dict[str, str] = {
        "applikation": application,
        "native_id": (technisch.get("ID") or "").strip(),
        "native_type": (block.get("Typ") or "").strip(),
        "bgblnummer": (block.get("Bgblnummer") or block.get("Fundstelle") or "").strip(),
        "teil": (block.get("Teil") or "").strip(),
    }
    if kurz := (bundesrecht.get("Kurztitel") or "").strip():
        meta_fields["kurztitel"] = kurz
    if eli := (bundesrecht.get("Eli") or data["Metadaten"].get("Allgemein", {}).get("DokumentUrl") or "").strip():
        meta_fields["eli"] = eli
    if alte := (block.get("AlteDokumentnummer") or "").strip():
        meta_fields["alte_dokumentnummer"] = alte
    if application == "BgblAuth":
        # Parliamentary-reference fields come with the entry; raw values only
        # (section 5.3: modification-relation fields are collected, not built on).
        for key, field in (
            ("gesetzgebungsperiode", "Gesetzgebungsperiode"),
            ("datum_nationalrat", "DatumNationalrat"),
            ("nummer_nationalrat", "NummerNationalrat"),
            ("datum_bundesrat", "DatumBundesrat"),
            ("nummer_bundesrat", "NummerBundesrat"),
        ):
            if value := (block.get(field) or "").strip():
                meta_fields[key] = value
    if application == "BgblPdf":
        for key, field in (
            ("jahrgang", "Jahrgang"),
            ("beginnseite_stueck", "BeginnseiteStueck"),
            ("endseite_stueck", "EndseiteStueck"),
        ):
            if value := (block.get(field) or "").strip():
                meta_fields[key] = value

    return {
        "pub": pub,
        "organ": (data["Metadaten"]["Technisch"].get("Organ") or "").strip(),
        "title": (bundesrecht.get("Titel") or "").strip(),
        "meta": meta_fields,
        "xml_url": _xml_url(entry, application, meta_fields["native_id"]),
    }


class BgblWindowHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        application = str(task.params["applikation"])
        von = str(task.params["von"])
        bis = str(task.params["bis"])
        return RequestSpec(
            url=f"{API_BASE}/Bundesrecht",
            params={
                "Applikation": application,
                **window_query(application, von, bis),
                "DokumenteProSeite": PAGE_SIZE,
                "Seitennummer": str(task.params.get("seitennummer", "1")),
                "Sortierung.SortedByColumn": "Kundmachungsdatum",
                "Sortierung.SortDirection": "Ascending",
            },
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        application = str(task.params["applikation"])
        von = str(task.params["von"])
        bis = str(task.params["bis"])
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(f"window {von}..{bis} ({application}): {exc}") from exc

        if "OgdSearchResult" not in payload:
            raise ValueError(
                f"window {von}..{bis} ({application}): no OgdSearchResult envelope"
            )
        search_result = payload["OgdSearchResult"]
        if "OgdDocumentResults" not in search_result:
            error = search_result.get("Error")
            raise ValueError(
                f"window {von}..{bis} ({application}): source reported an error "
                f"({error!r})" if error else
                f"window {von}..{bis} ({application}): no OgdDocumentResults block"
            )

        results = search_result["OgdDocumentResults"]
        hits = results.get("Hits", {})
        total = int(hits.get("#text", "0"))
        page_number = int(hits.get("@pageNumber", "1"))
        page_size = int(hits.get("@pageSize", "20"))
        entries = _as_list(results.get("OgdDocumentReference"))

        next_tasks: list[TaskSeed] = []
        documents: list[DocumentRecord] = []
        for entry in entries:
            fields = _entry_metadata(entry, application, von, bis)
            native_id = fields["meta"]["native_id"]
            documents.append(
                DocumentRecord(
                    title=fields["title"] or native_id,
                    source_url=fields["xml_url"],
                    publication_date=fields["pub"],
                    issuing_authority=fields["organ"] or None,
                    doc_type=map_doc_type(fields["meta"]["native_type"]),
                    language="deu",
                    raw_metadata=fields["meta"],
                )
            )
            next_tasks.append(
                TaskSeed(
                    type="bgbl_file",
                    params={
                        "applikation": application,
                        "id": native_id,
                        "pub": fields["pub"],
                        "url": fields["xml_url"],
                    },
                )
            )

        if not documents and total == 0:
            return TaskResult(
                expected_empty=(
                    f"no BGBl entries published {von}..{bis} ({application}) — "
                    "an empty window is a fully consumed window"
                ),
                cursor_updates={CURSOR_KEY: bis},
            )

        if page_number * page_size < total:
            next_tasks.append(
                TaskSeed(
                    type="bgbl_window",
                    params={
                        "applikation": application,
                        "von": von,
                        "bis": bis,
                        "seitennummer": str(page_number + 1),
                    },
                )
            )
            return TaskResult(documents=documents, next_tasks=next_tasks)

        # Last page (or single short page): the window is fully consumed.
        return TaskResult(
            documents=documents,
            next_tasks=next_tasks,
            cursor_updates={CURSOR_KEY: bis},
        )
