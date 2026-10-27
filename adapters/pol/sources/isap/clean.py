"""Task type ``isap_clean``: one document's plain-text extract (mixed carriers).

Reads the stored main file via ``RequestSpec.local_doc`` (no network) and
routes by content magic (pdf-clean-plan 2026-10-23, user-delegated; probe:
docs/tasks/2026-09-09-pol/pdf-clean-probe/):

- ``%PDF-`` prefix → the PDF body carrier (acts with no HTML: consolidation
  announcements, the 2025 fresh-year items, era-2000s entries).
  ``measure_pdf`` gates first: fewer than 20 deep text chars is a scan —
  PermanentError, OCR is out of scope (2026-09-19 ruling; census: 300
  scans, 1.4%, all era-2000). A PDF that fails parsing is characterized
  and raised as Permanent (probed: one 413 MB truncated file). Otherwise
  the local geometry channel extracts the text, the pack applies the
  mojibake repair table and strips the probed print-decoration line
  signatures (masthead, issue footer, price/ISSN lines) — the geometry
  function has no decoration hooks of its own.
- anything else → the HTML leg: the pre-existing ``_to_text`` path
  (body whitelist, fragment fallback, "Pokaż całość" drop) — v2 behavior
  byte-for-byte unchanged.

Repair table (probed: era-2001-2009 PDFs lack ToUnicode maps, so pdfminer
falls back to PDFDocEncoding and Polish letters surface as symbol glyphs —
"w∏adz" for "władz", "ROZPORZÑDZENIE" for "ROZPORZĄDZENIE"). Every table
key is a character that never occurs in correct Polish text, so the
translation is a no-op on the clean 2012+ outputs (validated: zero
occurrences across the eyeball set) — derived by word-level alignment of
200 era-2001-2009 documents against their ledger titles
(tools/pol_pdf_derive_table.py; votes in pdf-clean-probe/repair-table.json).

Both legs end in one ``CleanedRecord`` per document at version 2 (the
sniffing handler is not the framework's PdfCleanHandler, so the reseed
threshold is the bare ``v`` — the HTML rows are also at 2, so the PDF leg
seeds exactly the PDF-primary documents and re-cleans nothing else).
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
from runtime.stages.cleaning import (
    geometry_pdf_to_text,
    html_to_text,
    measure_pdf,
)

__all__ = ["CLEAN_VERSION", "REPAIR_TABLE", "IsapCleanHandler"]

CLEAN_VERSION = 2

#: Deep-collected text chars below which a PDF is an image-only scan
#: (pdf-clean census 2026-10-23: 300 documents, 1.4%, all era-2000).
_SCAN_CHAR_FLOOR = 20

_HINT_LINE = "Pokaż całość"

#: Mojibake repair table (derived + validated, see module docstring).
REPAIR_TABLE = str.maketrans({
    "à": "ą",
    "∏": "ł",
    "Ê": "ś",
    "´": "ę",
    "˝": "ż",
    "ƒ": "ń",
    "ê": "ź",
    "ç": "ć",
    "Â": "Ś",
    "Ñ": "Ą",
})

#: Print-decoration line signatures of the PDF leg (probe eyeball 2026-10-23),
#: applied to the geometry output after repair. Each is a whole-line,
#: case-sensitive fullmatch of page furniture only (masthead, issue header,
#: page footer/number, ISSN and price lines).
_PDF_LINE_FILTERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^DZIENNIK USTAW$"),
    re.compile(r"^DZIENNIK$"),
    re.compile(r"^USTAW$"),
    re.compile(r"^RZECZYPOSPOLITEJ POLSKIEJ$"),
    re.compile(r"^Poz\. \d+$"),
    re.compile(r"^[–-] \d+ [–-]$"),
    re.compile(r"^ISSN [\d-]+$"),
    re.compile(r"^Dziennik Ustaw Nr \d+$"),
    re.compile(r"^Cena .*zł$"),
)


def _to_text(content: bytes) -> str:
    try:
        return html_to_text(content, keep="body", drop_strings=(_HINT_LINE,))
    except ValueError:
        # Bare-fragment shape: no <body> element to whitelist — extract the
        # whole document (ELI HTML carries no site chrome in either shape).
        return html_to_text(content, drop_strings=(_HINT_LINE,))


def _filter_pdf_lines(text: str) -> str:
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and any(p.fullmatch(stripped) for p in _PDF_LINE_FILTERS):
            continue
        kept.append(line)
    return "\n".join(kept).strip("\n") + "\n"


def _clean_pdf(doc_id: str, data: bytes) -> CleanedRecord:
    try:
        measure = measure_pdf(data)
    except Exception as exc:
        raise PermanentError(
            f"{doc_id}: malformed PDF ({type(exc).__name__}: {exc})"
        ) from exc
    if int(measure["chars"]) < _SCAN_CHAR_FLOOR:
        raise PermanentError(
            f"扫描件——OCR 界外: {doc_id} has {measure['chars']} text chars "
            f"across {measure['pages']} page(s); scanned documents are out "
            "of scope (2026-09-19 user ruling)"
        )
    text = geometry_pdf_to_text(data).translate(REPAIR_TABLE)
    text = _filter_pdf_lines(text)
    return CleanedRecord(
        doc_id=doc_id,
        version=CLEAN_VERSION,
        content=text.encode("utf-8"),
    )


class IsapCleanHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(local_doc=str(task.params["doc_id"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        doc_id = str(task.params["doc_id"])
        kind = str(task.params["kind"])
        data = response.content
        if data.startswith(b"%PDF-"):
            return TaskResult(cleaned=[_clean_pdf(doc_id, data)])
        if kind == "isap_pdf":
            # A PDF-primary document whose stored file is not a PDF: the
            # loud characterization of a source defect (probed: DU/2009/1788
            # serves an XML signature file on text.pdf).
            raise PermanentError(
                f"{doc_id}: primary carrier is not a PDF "
                f"(starts {data[:16]!r})"
            )
        if kind != "isap_act":
            raise PermanentError(
                f"isap_clean has no container rules for kind {kind!r} "
                "(expected the producing task type isap_act/isap_pdf)"
            )
        try:
            text: str = _to_text(data)
        except ValueError as exc:
            raise PermanentError(f"{doc_id}: {exc}") from exc
        record = CleanedRecord(
            doc_id=doc_id,
            version=CLEAN_VERSION,
            content=text.encode("utf-8"),
        )
        return TaskResult(cleaned=[record])
