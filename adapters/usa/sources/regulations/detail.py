"""Task types ``fr_detail`` / ``fr_text_dl``: one FR document's full record.

``fr_detail`` fetches the complete field set the listing cannot carry
(subtype, effective/comment dates, corrections links, topics, the XML text
URL), writes the folder mirror, and registers each downloadable format as a
**document** (entity_ref points at the fr_documents row) plus one
``fr_text_dl`` per format.

``fr_text_dl`` fetches one artifact (raw.txt / full.xml / doc.pdf) into the
document's folder; its doc_id linkage lets the framework fill in
local_path/file_hash/content_length on the documents row.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.usa.schema import fr_doc_type, fr_folder, president_name, yn_flag
from adapters.usa.sources.regulations.enumerate import API_BASE
from core.document import DocumentRecord, compute_doc_id

__all__ = ["FORMAT_TARGETS", "FrDetailHandler", "FrTextDownloadHandler"]

#: format param → (detail field, folder name, extension fallback)
FORMAT_TARGETS: dict[str, tuple[str, str, str]] = {
    "txt": ("raw_text_url", "raw", "txt"),
    "xml": ("full_text_xml_url", "full", "xml"),
    "pdf": ("pdf_url", "doc", "pdf"),
}


def _normalize_correction_of(value: object) -> str | None:
    """FR hands back the corrected document as a bare number or an API URL
    (verified real data 2026-08-27: URL); reduce both to the document
    number so the column joins cleanly."""
    if isinstance(value, dict):
        value = value.get("document_number")
    if not isinstance(value, str) or not value:
        return None
    if "/" in value:
        value = value.rstrip("/").rsplit("/", 1)[-1]
    return value or None


def _topic_names(value: Any) -> list[str]:
    """FR returns ``topics`` as plain strings; older mirrors may use
    ``{"name": …}`` objects — accept both (string shape verified against
    real data 2026-08-27)."""
    names: list[str] = []
    for item in value or []:
        name = item if isinstance(item, str) else (item or {}).get("name")
        if name:
            names.append(str(name))
    return names


class FrDetailHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        number = str(task.params["document_number"])
        return RequestSpec(url=f"{API_BASE}/documents/{number}.json")

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        doc = response.json()
        document_number = str(doc.get("document_number") or task.params["document_number"])
        publication_date = str(doc.get("publication_date") or "")
        title_text = str(doc.get("title") or document_number)
        folder = fr_folder(publication_date, document_number)
        rids = [str(r) for r in (doc.get("regulation_id_numbers") or []) if r]
        agencies = doc.get("agencies") or []
        row = {
            "document_number": document_number,
            "publication_date": publication_date,
            "title": title_text,
            "type": doc.get("type"),
            "subtype": doc.get("subtype"),
            "action": doc.get("action"),
            "abstract": doc.get("abstract"),
            "citation": doc.get("citation"),
            "volume": doc.get("volume"),
            "start_page": doc.get("start_page"),
            "end_page": doc.get("end_page"),
            "agencies": agencies,
            "president": president_name(doc.get("president")),
            "executive_order_number": doc.get("executive_order_number"),
            "proclamation_number": doc.get("proclamation_number"),
            "effective_on": doc.get("effective_on"),
            "comments_close_on": doc.get("comments_close_on"),
            "dates_text": doc.get("dates"),
            "significant": yn_flag(doc.get("significant")),
            "cfr_references": doc.get("cfr_references") or [],
            "rin": rids[0] if rids else None,
            "rins": rids,
            "docket_ids": doc.get("docket_ids") or [],
            "topics": _topic_names(doc.get("topics")),
            "correction_of": _normalize_correction_of(doc.get("correction_of")),
            "corrections": doc.get("corrections") or [],
            "regulations_gov_url": doc.get("regulations_dot_gov_url"),
            "html_url": doc.get("html_url"),
            "raw_text_url": doc.get("raw_text_url"),
            "full_text_xml_url": doc.get("full_text_xml_url"),
            "pdf_url": doc.get("pdf_url"),
            "folder": folder,
        }

        formats = [f.strip() for f in str(task.params.get("formats", "txt,xml")).split(",") if f.strip()]
        lead_agency = next((a.get("raw_name") for a in agencies if a.get("raw_name")), None)
        fr_type = doc.get("type")
        fr_subtype = doc.get("subtype")
        documents: list[DocumentRecord] = []
        next_tasks: list[TaskSeed] = []
        for fmt in formats:
            target = FORMAT_TARGETS.get(fmt)
            if target is None:
                continue
            url_field, stem, _fallback = target
            url = doc.get(url_field)
            if not url:
                continue
            url = str(url)
            documents.append(
                DocumentRecord(
                    title=title_text,
                    source_url=url,
                    publication_date=publication_date or None,
                    issuing_authority=lead_agency or "Federal Register",
                    doc_type=fr_doc_type(fr_type, fr_subtype),
                    entity_ref=f"fr_documents:{document_number}",
                    language="en",
                    raw_metadata={
                        "fr_type": str(fr_type or ""),
                        "subtype": str(fr_subtype or ""),
                        "format": fmt,
                        "citation": str(row["citation"] or ""),
                    },
                )
            )
            next_tasks.append(
                TaskSeed(
                    type="fr_text_dl",
                    params={
                        "url": url,
                        "fmt": fmt,
                        "stem": stem,
                        "date": publication_date,
                        "folder": folder,
                    },
                )
            )

        return TaskResult(
            upsert_rows={"fr_documents": [row]},
            documents=documents,
            next_tasks=next_tasks,
            files=[FileOut(path=f"{folder}/detail.json", content=response.content)],
        )


class FrTextDownloadHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=str(task.params["url"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        url = str(task.params["url"])
        stem = str(task.params.get("stem") or "raw")
        folder = str(task.params["folder"])
        extension = PurePosixPath(urlsplit(url).path).suffix.lstrip(".").lower() or "txt"
        doc_id = compute_doc_id("USA", url, str(task.params.get("date") or "") or None)
        return TaskResult(
            files=[
                FileOut(
                    path=f"{folder}/text/{stem}.{extension}",
                    content=response.content,
                    doc_id=doc_id,
                )
            ]
        )
