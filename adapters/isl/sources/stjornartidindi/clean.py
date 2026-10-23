"""Task type ``stjornartidindi_clean``: one document's plain-text extract.

Reads the stored main file via ``RequestSpec.local_doc`` (no network) and
routes by content magic (user-approved clean-plan.md 2026-09-30; probe:
docs/tasks/2026-09-17-isl/clean-probe/):

- ``%PDF-`` prefix → the PDF body carrier (digitisation-stub fallback
  docs after the repair-isl-mainfile alignment, plus the two documents
  whose primary was always the PDF). ``measure_pdf`` gates first:
  fewer than 150 chars per page is a scan-like gazette compilation
  (annual A-deild compendiums, probed 47-72 chars/page vs a 259 minimum
  for real text) — PermanentError, OCR is out of scope. Otherwise the
  local geometry channel extracts the text and the pack strips the four
  probed print-decoration line signatures (spaced-out masthead, issue
  number, compendium footer, publication stamp) — the geometry function
  has no decoration hooks of its own.
- anything else → the HTML leg. The stored body is the API's inline
  content fragment: no site chrome exists, so ``keep`` is None (plan
  Q3) and the only decoration is the trailing publication stamp, whose
  date varies — dropped by centered-container ``:-soup-contains``
  selectors (case-sensitive + centered-only, so body paragraphs
  mentioning "útgáfud" survive; probed).

Both legs end in one ``CleanedRecord`` per document at version 1 (the
sniffing handler is not the framework's PdfCleanHandler, so the reseed
threshold is the bare ``v`` — equivalent to ×100 here since there is no
MinerU fingerprint in this corpus).
"""

from __future__ import annotations

import re

from adapters.base import (
    CleanedRecord,
    RequestSpec,
    Response,
    TaskResult,
    TaskView,
)
from runtime.errors import PermanentError
from runtime.stages.cleaning import geometry_pdf_to_text, html_to_text, measure_pdf

__all__ = ["CLEAN_VERSION", "STAMP_DROP_SELECTORS", "IsCleanHandler"]

CLEAN_VERSION = 1

#: chars per page below which a PDF is a scan-like compilation (probed
#: 2026-09-30 on 130 sampled files: scan-like 47-72, real text >= 259).
SCAN_LIKE_CHARS_PER_PAGE = 150

#: The publication stamp rides in centered containers; its date varies,
#: so exact-match drop_strings cannot catch it. ``:-soup-contains`` is
#: the non-deprecated soupsieve spelling; case-sensitive matching plus
#: the centered-only constraint keeps body text mentioning "útgáfud".
STAMP_DROP_SELECTORS: tuple[str, ...] = (
    "p[align=center]:-soup-contains(Útgáfud)",
    "div[align=center]:-soup-contains(Útgáfud)",
)

#: Print-decoration line signatures of the PDF leg (probe §3), applied
#: to the geometry output after stripping. Each is whole-line.
_PDF_LINE_FILTERS: tuple[re.Pattern[str], ...] = (
    # spaced-out masthead: "STJÓRNARTÍÐI NDI" normalises to the word
    re.compile(r"^STJÓRNARTÍÐINDI$"),
    re.compile(r"^Nr\.?\s*\d+$"),
    re.compile(r"^Stjórnartíðindi [ABC] \d+, nr\. \d+\. Útgáfudagur "),
    re.compile(r"^[ABC] deild\s*[-—]\s*Útgáfud"),
)


def _filter_pdf_lines(text: str) -> str:
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and _is_decoration(stripped):
            continue
        kept.append(line)
    return "\n".join(kept).strip("\n") + "\n"


def _is_decoration(stripped: str) -> bool:
    for pattern in _PDF_LINE_FILTERS:
        if pattern.match(stripped):
            return True
    return stripped.replace(" ", "") == "STJÓRNARTÍÐINDI"


class IsCleanHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(local_doc=str(task.params["doc_id"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        doc_id = str(task.params["doc_id"])
        data = response.content
        if data.startswith(b"%PDF-"):
            return TaskResult(cleaned=[self._clean_pdf(doc_id, data)])
        return TaskResult(cleaned=[self._clean_html(doc_id, data)])

    def _clean_pdf(self, doc_id: str, data: bytes) -> CleanedRecord:
        measured = measure_pdf(data)
        per_page = measured["chars"] / max(int(measured["pages"]), 1)
        if per_page < SCAN_LIKE_CHARS_PER_PAGE:
            raise PermanentError(
                f"{doc_id}: scan-like gazette compilation "
                f"({per_page:.0f} chars/page over {measured['pages']} pages) — "
                "OCR is out of scope"
            )
        text = _filter_pdf_lines(geometry_pdf_to_text(data))
        return CleanedRecord(
            doc_id=doc_id,
            version=CLEAN_VERSION,
            content=text.encode("utf-8"),
        )

    def _clean_html(self, doc_id: str, data: bytes) -> CleanedRecord:
        try:
            text = html_to_text(data, drop=STAMP_DROP_SELECTORS)
        except ValueError as exc:
            raise PermanentError(f"{doc_id}: {exc}") from exc
        return CleanedRecord(
            doc_id=doc_id,
            version=CLEAN_VERSION,
            content=text.encode("utf-8"),
        )
