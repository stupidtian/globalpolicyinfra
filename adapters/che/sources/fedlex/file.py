"""Task type ``che_file``: one file from the portal-host filestore.

The URL comes from the graph (``jolux:isExemplifiedBy``) with the data
host swapped for the robots-friendly portal host — same path, verified
2026-09-09. Never constructed: a guessed filestore URL answers with an
HTTP 206 HTML error page, not a 404 (probed), so the parser verifies the
payload's magic bytes against the format the URL promises before letting
it anywhere near the ledger.

The spawn (as_day / sr_entry) carried every document field in task
params; this handler adds only the bytes. One request = one file = one
documents row, so the ledger's INSERT-first-wins documents path can never
race a sibling (the SVK PDF-ordering lesson doesn't apply here).
"""

from __future__ import annotations

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from core.document import DocumentRecord, compute_doc_id

__all__ = ["CheFileHandler"]

_MAGIC = {
    "html": b"<",
    "xml": b"<",
    "pdf": b"%PDF",
    "pdf-a": b"%PDF",
    "docx": b"PK",
    "epub": b"PK",
}


class CheFileHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=str(task.params["url"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        if response.status_code != 200:
            raise ValueError(f"file download returned HTTP {response.status_code}")

        params = task.params
        url = str(params["url"])
        fmt = str(params.get("fmt") or "")
        if not fmt:
            # spawn didn't say: derive from the URL's format segment
            fmt = url.rstrip("/").split("/")[-2]
        magic = _MAGIC.get(fmt)
        if magic is None:
            raise ValueError(f"unknown format {fmt!r} for {url}")
        # real manifestations may open with a newline (probed 2026-09-13:
        # the html files start b"\n<!DOCTYPE"); leading whitespace is fine,
        # a different payload is the trap — HTML error pages arrive with
        # success-ish statuses when a URL was invented
        if not response.content.lstrip().startswith(magic):
            raise ValueError(
                f"{url} does not start with {magic!r} as a {fmt} file should — "
                "response is not the advertised format"
            )

        title = str(params["title"])
        publication_date = params.get("publication_date") or None
        meta = {k: str(v) for k, v in dict(params.get("meta") or {}).items()}
        document = DocumentRecord(
            title=title,
            source_url=url,
            publication_date=publication_date,
            issuing_authority=params.get("issuing_authority") or None,
            doc_type=params.get("doc_type") or "OTHER",
            entity_ref=params.get("entity_ref") or None,
            language=params.get("language") or None,
            raw_metadata=meta,
        )
        doc_id = compute_doc_id("CHE", url, publication_date)
        return TaskResult(
            documents=[document],
            files=[FileOut(path=str(params["path"]), content=response.content, doc_id=doc_id)],
        )
