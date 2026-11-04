"""Task type ``per_clean``: one portal-era document -> unified XML.

The corpus mixes two raw carriers, so the handler branches on the shared
magic-number classifier (both shapes are born-digital; the legacy whole
editions never enter cleaning — they are produced by ``per_day_list``,
outside the declaration's ``targets``):

- **device HTML**: the embedded ``div#visor-html`` document is the whole
  content. Extracted with the framework HTML engine: keep the visor, drop
  the nested ``head`` (title/styles) and the site's stamped id line
  (``span.bold-cuerpo`` — observed exactly once per page, always the bare
  norm id), and the stray ``html`` line the embedded doctype leaves.
  Empty visor text is an explained empty (a norm whose carrier is image
  only), not a crash.
- **supplement PDF**: geometry channel (pdfminer line assembly); the
  scan floor is the framework's — under it the document is a scan and
  dies loud (OCR out of scope, 2026-09-19 ruling). Version encodes the
  PDF fingerprint slot (``v*100``), same convention as the PDF sources.
"""

from __future__ import annotations

from adapters.base import CleanedRecord, RequestSpec, Response, TaskResult, TaskView
from runtime.errors import PermanentError
from runtime.stages.cleaning import (
    detect_format,
    geometry_pdf_to_text,
    html_to_text,
    measure_pdf,
)
from runtime.stages.pdf_clean import SCAN_CHAR_FLOOR

__all__ = ["CLEAN_VERSION", "PerCleanHandler"]

CLEAN_VERSION = 1

_KEEP_SELECTOR = "div#visor-html"
_DROP_SELECTORS: tuple[str, ...] = ("head", "span.bold-cuerpo")
_DROP_STRINGS: tuple[str, ...] = ("html",)


class PerCleanHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(local_doc=str(task.params["doc_id"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        doc_id = str(task.params["doc_id"])
        version = int(task.params["v"])
        kind = detect_format(response.content)
        if kind == "html":
            return self._clean_html(doc_id, version, response)
        if kind == "pdf":
            return self._clean_pdf(doc_id, version, response)
        raise PermanentError(
            f"clean {doc_id}: stored file is neither HTML nor PDF (detect={kind!r})"
        )

    def _clean_html(self, doc_id: str, version: int, response: Response) -> TaskResult:
        text = html_to_text(
            response.content,
            keep=_KEEP_SELECTOR,
            drop=_DROP_SELECTORS,
            drop_strings=_DROP_STRINGS,
        )
        if not text.strip():
            return TaskResult(
                expected_empty=(
                    f"clean {doc_id}: the device page embeds no text in its visor — "
                    "possible image-only norm; verify before treating as a fault"
                )
            )
        return TaskResult(
            cleaned=[
                CleanedRecord(doc_id=doc_id, version=version, content=text.encode("utf-8"))
            ]
        )

    def _clean_pdf(self, doc_id: str, version: int, response: Response) -> TaskResult:
        measure = measure_pdf(response.content)
        if int(measure["pages"]) == 0:
            # not a scan — the source delivered a structurally unreadable
            # PDF (probed live 2026-11-02: VistaNLSE served a 4.9 MB
            # %PDF-1.7 body whose page tree resolves to nothing)
            raise PermanentError(
                f"clean {doc_id}: the stored PDF resolves to 0 pages — "
                "unreadable at the source; the raw bytes are kept for "
                "re-examination"
            )
        if int(measure["chars"]) < SCAN_CHAR_FLOOR:
            raise PermanentError(
                f"扫描件——OCR 界外: clean {doc_id} has {measure['chars']} text chars "
                f"across {measure['pages']} page(s); scanned documents are out of "
                "scope (2026-09-19 user ruling)"
            )
        text = geometry_pdf_to_text(response.content)
        return TaskResult(
            cleaned=[
                CleanedRecord(
                    doc_id=doc_id,
                    # geometry is deterministic per rule version: fingerprint
                    # slot 0, same encoding as the framework PDF sources
                    version=version * 100,
                    content=text.encode("utf-8"),
                )
            ]
        )
