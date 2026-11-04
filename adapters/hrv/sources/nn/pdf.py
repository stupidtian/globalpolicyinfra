"""Task type ``nn_pdf``: the per-item PDF as the full-text carrier.

``GET /eli/sluzbeni/{Y}/{issue}/{ordinal}/pdf`` — the item-level PDF
that exists exactly from NN 1/2023 onward (probed 2026-11-01: the last
2022 item answers 302 -> 404; digital-native text layer, verified by
page-1 pdfminer extraction on an issue sample). This task runs only
when the ``nn_doc`` page answered with a pdf-view instead of inline
text — recent items whose HTML body is back-filled with a lag. It
registers the document with the PDF as the PRIMARY file (raw_format=
pdf) and records the item HTML page — already on disk from the
``nn_doc`` task — in meta.files, keeping the "primary file =
full-text carrier" invariant without any later repair pass.

All bibliographic fields travel in the task params (parsed from the
``nn_doc`` page by the seeding task); the PDF carries no parseable
metadata of its own that the ledger needs, so the parse only verifies
the magic bytes and registers.
"""

from __future__ import annotations

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.hrv.sources.nn import article_pdf_url_for, site_url_for
from adapters.hrv.sources.nn.doc import map_doc_type, meta_out
from core.document import DocumentRecord, compute_doc_id

__all__ = ["PdfHandler"]

_PDF_MAGIC = b"%PDF-"


class PdfHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=article_pdf_url_for(
                int(task.params["year"]),
                int(task.params["issue"]),
                int(task.params["art"]),
            )
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        year, issue, ordinal = (
            int(task.params["year"]),
            int(task.params["issue"]),
            int(task.params["art"]),
        )
        label = f"nn_pdf {year}/{issue}/{ordinal}"
        content = response.content
        if not content.startswith(_PDF_MAGIC):
            head = content[:32]
            raise ValueError(
                f"{label}: body is not a PDF (head={head!r}) — the item PDF "
                "may be missing or the endpoint may have moved"
            )

        pub_date = str(task.params["pub_date"])
        native_type = str(task.params.get("native_type", "")).strip()
        stub_path = f"01_raw/nn/{year}/{issue}_{ordinal}.html"
        fields = meta_out(
            year=year,
            issue=issue,
            ordinal=ordinal,
            native_type=native_type,
            subtype=str(task.params.get("subtype", "")).strip(),
            relation=str(task.params.get("relation", "")).strip(),
            csv_title=str(task.params.get("title", "")).strip(),
            nn_part=str(task.params.get("nn_part", "")).strip(),
            eli=f"/eli/sluzbeni/{year}/{issue}/{ordinal}",
            printed_page=str(task.params.get("printed_page", "")).strip(),
            body_carrier="pdf",
            extra={"files": stub_path},
        )
        issuer = str(task.params.get("issuer", "")).strip()
        source_url = site_url_for(year, issue, ordinal)
        doc_id = compute_doc_id("HRV", source_url, pub_date)
        record = DocumentRecord(
            title=str(task.params["title"]),
            source_url=source_url,
            publication_date=pub_date,
            issuing_authority=issuer if issuer and issuer != "-" else None,
            doc_type=map_doc_type(native_type),
            language="hr",
            raw_metadata=fields,
        )
        return TaskResult(
            documents=[record],
            files=[
                FileOut(
                    path=f"01_raw/nn/{year}/{issue}_{ordinal}.pdf",
                    content=content,
                    doc_id=doc_id,
                )
            ],
        )
