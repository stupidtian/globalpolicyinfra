"""Task type ``frl_clean``: strip one collected document to plain text.

The register's documents are 99.96% EPUB (as-made volumes) plus 30
digital-native PDFs (2004–2006 notices and two very large acts). One
sniffing handler serves both: the framework's :func:`detect_format`
classifies the stored bytes (this is its first scheduled consumer) and
branches — EPUB goes straight to :func:`epub_to_text`, PDF goes through
:func:`measure_pdf` into the local geometry channel.

Rules table: **empty, by design** (probed 2026-08-31..10-02, see
docs/tasks/2026-08-30-aus/clean-probe/). FRL as-made EPUBs carry no site
decoration — cover title page, body, amendment history and signature
blocks are all legitimate content; the only "Federal Register of
Legislation" hits ever found are the endnote abbreviation legend and a
standard legal notice sentence (framework-epub-cleaning correction 3,
reproduced independently on 13 stratified samples). keep/drop/
drop_strings are therefore all empty and epub_to_text gets the raw book.

Two loud failure shapes beyond the format sniff (both real corpus
findings, 2026-10-02):

- a degenerate/stub PDF (smallest real file is 704 bytes, 0 pages) falls
  under the framework's scan floor — fewer than 20 text chars is out of
  scope (no OCR), PermanentError;
- a PDF whose fonts lack ToUnicode maps renders as ``(cid:…)`` garbage
  (the 2000 States Grants Act: 94% of lines); when at least half the
  non-empty output lines are CID strings the conversion fails loudly —
  garbage text must not enter the cleaned ledger.

Version: bare ``v`` (the handler is not the framework PdfCleanHandler,
so the cli reseeding threshold stays un-multiplied; everything is local,
no backend fingerprint to absorb).
"""

from __future__ import annotations

from adapters.base import CleanedRecord, RequestSpec, Response, TaskResult, TaskView
from runtime.errors import PermanentError
from runtime.stages.cleaning import (
    detect_format,
    epub_to_text,
    geometry_pdf_to_text,
    measure_pdf,
)
from runtime.stages.pdf_clean import SCAN_CHAR_FLOOR

__all__ = ["CID_LINE_RATIO", "CLEAN_VERSION", "FrlCleanHandler", "cid_line_ratio"]

CLEAN_VERSION = 1

#: A rendered PDF is garbage when at least this share of its non-empty
#: lines are ``(cid:…)`` strings (fonts without ToUnicode maps).
CID_LINE_RATIO = 0.5


def cid_line_ratio(text: str) -> float:
    """Share of non-empty lines carrying ``(cid:`` glyphs."""
    lines = [line for line in text.split("\n") if line.strip()]
    if not lines:
        return 0.0
    return sum(1 for line in lines if "(cid:" in line) / len(lines)


class FrlCleanHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(local_doc=str(task.params["doc_id"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        doc_id = str(task.params["doc_id"])
        fmt = detect_format(response.content)
        if fmt == "epub":
            text = epub_to_text(response.content)
            if not text:
                # Real corpus finding (3 of 76,664, 2026-10-03): some books
                # are image-only — the single spine chapter is nothing but
                # <img> tags over 18–180 page scans. Text extraction has
                # nothing to extract; empty output would only die later on
                # the engine's trailing-newline contract with a misleading
                # message, so classify it here where the cause is known.
                raise PermanentError(
                    f"frl_clean: doc {doc_id} is an image-only EPUB (page "
                    "scans) — nothing to extract, OCR is out of scope "
                    "(2026-09-19 user ruling)"
                )
        elif fmt == "pdf":
            text = self._pdf(response.content, doc_id)
        else:
            raise PermanentError(
                f"frl_clean: doc {doc_id} is {fmt!r} after format sniffing — "
                "not convertible, refusing to guess"
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

    def _pdf(self, data: bytes, doc_id: str) -> str:
        measure = measure_pdf(data)
        if int(measure["chars"]) < SCAN_CHAR_FLOOR:
            raise PermanentError(
                f"frl_clean: doc {doc_id} has {measure['chars']} text chars "
                f"across {measure['pages']} page(s) — scanned or degenerate "
                "file, OCR is out of scope (2026-09-19 user ruling)"
            )
        text = geometry_pdf_to_text(data)
        ratio = cid_line_ratio(text)
        if ratio >= CID_LINE_RATIO:
            raise PermanentError(
                f"frl_clean: doc {doc_id} renders {ratio:.0%} (cid:…) lines — "
                "fonts without ToUnicode maps, text layer is not recoverable "
                "(raw PDF kept in 01_raw; OCR is out of scope)"
            )
        return text
