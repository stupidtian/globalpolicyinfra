"""Task type ``govza_clean``: strip one collected document to plain text.

Reads the stored file via ``RequestSpec.local_doc`` (no network; the
engine decompresses ``.gz`` automatically) and serves the source's
mixed carriers with one sniffing handler (the AUS FRL precedent):
:func:`detect_format` classifies the stored bytes and branches —

- **PDF** (the corpus's primary carrier: every gazette notice, act and
  bill the portal links a file for): measured first — fewer than 20
  deep-collected text chars is a scan and fails permanently (OCR out of
  scope by user ruling; the probed 2002/2005/2025 samples all carry
  real text layers, so scans are the exception to be counted, not the
  norm to be processed) — then the local geometry channel
  (:func:`geometry_pdf_to_text`). A render whose non-empty lines are
  mostly ``(cid:…)`` strings (fonts without ToUnicode maps) fails loud
  (the FRL corpus finding): garbage text must not enter the cleaned
  ledger.
- **HTML** (the early non-gazette layers whose only carrier is the
  portal page itself): a pure whitelist — the body lives in the single
  ``div.field--name-body`` container (verified present and unique on
  the 2025/2005/1995 samples, 2026-10-10); every decoration (search
  area, navigation, footer) sits outside it. Zero keep matches is a
  shape mutation and dies loud.

An extraction that yields nothing (an empty body container) is an
explained empty, not a handler fault (ESP/AUT stub precedent): task
done, no cleaned row. Version is the bare ``v`` (the handler is not the
framework PdfCleanHandler, so no backend fingerprint applies; the MinerU
channel is not declared — every probed PDF is locally extractable).
"""

from __future__ import annotations

from adapters.base import (
    CleanedRecord,
    RequestSpec,
    Response,
    TaskResult,
    TaskView,
)
from runtime.errors import PermanentError
from runtime.stages.cleaning import (
    detect_format,
    geometry_pdf_to_text,
    html_to_text,
    measure_pdf,
)
from runtime.stages.pdf_clean import SCAN_CHAR_FLOOR

__all__ = ["CID_LINE_RATIO", "CLEAN_VERSION", "GovzaCleanHandler", "cid_line_ratio"]

CLEAN_VERSION = 1

#: The portal page's body container — single whitelist, all three probed
#: page generations.
KEEP_SELECTOR = "div.field--name-body"

#: A rendered PDF is garbage when at least this share of its non-empty
#: lines carry ``(cid:`` glyphs (fonts without ToUnicode maps).
CID_LINE_RATIO = 0.5


def cid_line_ratio(text: str) -> float:
    """Share of non-empty lines carrying ``(cid:`` glyphs."""
    lines = [line for line in text.split("\n") if line.strip()]
    if not lines:
        return 0.0
    return sum(1 for line in lines if "(cid:" in line) / len(lines)


class GovzaCleanHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(local_doc=str(task.params["doc_id"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        kind = str(task.params["kind"])
        if kind != "govza_detail":
            raise PermanentError(f"govza_clean has no rules for kind {kind!r}")
        doc_id = str(task.params["doc_id"])
        fmt = detect_format(response.content)

        if fmt == "pdf":
            measure = measure_pdf(response.content)
            if int(measure["chars"]) < SCAN_CHAR_FLOOR:
                raise PermanentError(
                    f"扫描件——OCR 界外: doc {doc_id} has {measure['chars']} text "
                    f"chars across {measure['pages']} page(s); scanned documents "
                    "are out of scope (2026-09-19 user ruling)"
                )
            text = geometry_pdf_to_text(response.content)
            if cid_line_ratio(text) >= CID_LINE_RATIO:
                raise PermanentError(
                    f"govza_clean {doc_id}: PDF renders as (cid:…) garbage "
                    f"({measure['chars']} chars, fonts without ToUnicode maps)"
                )
        elif fmt == "html":
            try:
                text = html_to_text(response.content, keep=KEEP_SELECTOR)
            except ValueError as exc:
                raise PermanentError(f"govza_clean {doc_id}: {exc}") from exc
        else:
            raise PermanentError(
                f"govza_clean {doc_id}: stored file is {fmt!r} — neither a PDF "
                "nor the portal page HTML"
            )

        if not text.strip():
            return TaskResult(
                expected_empty=f"govza_clean {doc_id}: extraction yielded no text"
            )
        return TaskResult(
            cleaned=[
                CleanedRecord(
                    doc_id=doc_id,
                    version=CLEAN_VERSION,
                    content=text.encode("utf-8"),
                )
            ]
        )
