"""Task type ``isap_pdf``: the act's original PDF.

``GET /eli/acts/DU/{y}/{p}/text.pdf`` — the typeset original (probed
2026-09-20: DU/2024/1 at 270,714 bytes ``%PDF-1.7``, byte-identical to the
``/text/O/{fileName}`` inventory copy). Two roles in one task type:

- primary carrier (``doc_id`` + ``record`` in params) for acts with no
  HTML — the consolidation announcements (their ``textHTML`` is false) and
  any HTML-less era item: the record travels from the act task in params
  and THIS task registers the document it downloads, so ``produced_by``
  separates the two carriers honestly;
- typeset sibling (bare params) beside a primary HTML — its path travels
  in the document's ``meta.files`` (declared by the act task at upsert
  time).

A response without the ``%PDF`` magic is a loud shape change.
"""

from __future__ import annotations

from typing import Any

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.pol.sources.isap import ELI_BASE, act_folder
from core.document import DocumentRecord

__all__ = ["IsapPdfHandler"]


class IsapPdfHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        publisher = str(task.params["publisher"])
        return RequestSpec(
            url=(
                f"{ELI_BASE}/acts/{publisher}/{task.params['year']}/"
                f"{task.params['pos']}/text.pdf"
            )
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        publisher = str(task.params["publisher"])
        label = f"{publisher}/{task.params['year']}/{task.params['pos']}"
        content = response.content
        if not content.startswith(b"%PDF"):
            raise ValueError(
                f"isap_pdf {label}: response is not a PDF "
                f"({len(content)} bytes, starts {content[:20]!r})"
            )
        file_out = FileOut(
            path=f"{act_folder(publisher, task.params['year'], task.params['pos'])}/text.pdf",
            content=content,
            doc_id=str(task.params["doc_id"]) if task.params.get("doc_id") else None,
        )
        record_bundle = task.params.get("record")
        if not isinstance(record_bundle, dict):
            return TaskResult(files=[file_out])
        return TaskResult(
            documents=[_record_from_bundle(record_bundle)],
            files=[file_out],
        )


def _record_from_bundle(bundle: dict[str, Any]) -> DocumentRecord:
    meta = dict(bundle.get("raw_metadata") or {})
    meta.pop("files", None)  # not a str — rebuilt below for the PDF carrier
    meta["files"] = "act.json"
    return DocumentRecord(
        title=str(bundle["title"]),
        source_url=str(bundle["source_url"]),
        publication_date=bundle.get("publication_date"),
        issuing_authority=bundle.get("issuing_authority"),
        doc_type=bundle.get("doc_type"),
        entity_ref=bundle.get("entity_ref"),
        language="pol",
        raw_metadata=meta,
    )
