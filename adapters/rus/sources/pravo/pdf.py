"""Task type ``pravo_pdf``: one document's scanned original, one request.

GET the publication portal's direct PDF (``/file/pdf?eoNumber={number}``)
and store the bytes verbatim as the primary file. This leg exists for
document classes the legal-text bank does not carry — ministry normative
acts (ведомственные акты, probed 2026-10-12: 0 of 15 orders across
2015–2026 present in the bank) — where the portal's PDF is a *scan with
no text layer*, so what it preserves is the official original image plus
the listing metadata; machine-readable text for this class does not exist
in the free official channels (the scan-OCR path is a separate,
architecture-gated undertaking).

The document identity is identical to the HTML leg's: ``source_url`` is
the portal document page and the ``doc_id`` derives from it, so a future
widening (types/content changes) reuses the same identity — switching a
document's carrier later updates the row in place instead of duplicating
it.

Cleaning: not declared for this leg (CleanDefinition targets
``pravo_body`` only) — the scans carry no extractable text, and routing
them through the PDF cleaner would produce loud permanent failures by
design (OCR is out of scope).
"""

from __future__ import annotations

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.rus.sources.pravo import PORTAL_BASE
from core.document import DocumentRecord, compute_doc_id
from runtime.errors import PermanentError, TransientError

__all__ = ["PravoPdfHandler"]


class PravoPdfHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=f"{PORTAL_BASE}/file/pdf",
            params={"eoNumber": str(task.params["номер"])},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        pnum = str(task.params["номер"])
        if response.status_code >= 500:
            raise TransientError(
                f"pravo_pdf {pnum}: portal answered HTTP {response.status_code}"
            )
        if response.status_code != 200:
            raise PermanentError(
                f"pravo_pdf {pnum}: unexpected HTTP {response.status_code} "
                "(the listing advertised this PDF moments ago)"
            )
        if not response.content.startswith(b"%PDF"):
            raise ValueError(
                f"pravo_pdf {pnum}: body is not a PDF — delivery shape mutated"
            )

        pub_date = str(task.params["pub_date"])
        ymd = pub_date.replace("-", "")
        source_url = f"{PORTAL_BASE}/document/{pnum}"

        meta: dict[str, str] = {"номер": pnum, "files": "doc.pdf"}
        for key in ("doc_number", "doc_date", "pdf_pages", "scope"):
            value = str(task.params.get(key, ""))
            if value:
                meta[key] = value

        document = DocumentRecord(
            title=str(task.params["title"]),
            source_url=source_url,
            publication_date=pub_date,
            issuing_authority=str(task.params["issuing_authority"])
            if str(task.params.get("issuing_authority", ""))
            else None,
            doc_type=str(task.params.get("doc_type", "OTHER")) or "OTHER",
            language="rus",
            raw_metadata=meta,
        )
        doc_id = compute_doc_id("RUS", source_url, pub_date)
        path = f"01_raw/pravo/{ymd[:4]}/D{ymd}/{pnum}/doc.pdf"

        return TaskResult(
            documents=[document],
            files=[
                FileOut(path=path, content=response.content, doc_id=doc_id)
            ],
        )
