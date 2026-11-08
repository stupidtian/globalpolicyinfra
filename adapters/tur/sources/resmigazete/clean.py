"""Task type ``rg_clean``: one gazette document's plain-text extract.

Reads the stored primary file via ``RequestSpec.local_doc`` (no network,
no rate limit) and routes by content magic. Scope confirmed by the user
2026-10-16 — clean the text-bearing ~91,250 (htm items + digital PDFs),
skip the rest with an explained empty:

- ``%PDF-`` prefix → the PDF leg. ``measure_pdf`` gates first: fewer than
  20 extracted chars is a **scan** — expected empty ("scanned, OCR out of
  scope", 2026-09-19 ruling; census 2026-10-16: ~2,465 scans, concentrated
  2005-2019, mostly monthly certificate-list Tebliğ). A PDF that fails
  parsing is characterized and raised Permanent (real anomaly). Otherwise
  the local geometry channel extracts the text. PDFs whose embedded fonts
  lack ToUnicode maps yield ``(cid:…)`` glyph soup (census: ~1,675, all
  2022+) — uninterpretable, expected empty (extractor limitation, not a
  scan; an alternative channel is an architecture-side decision). PDFs at
  or above ``_STREAM_BYTES`` take the page-streaming geometry leg
  (:func:`geometry_pdf_to_text_streamed`) — probed 2026-11-03: the
  corpus's largest item (308 MB, Karar No. 8561, the SOLAS 74/1978
  technical-annex amendments) MemoryError'd the in-memory path on 8 GB.
- HTML (htm items and anchor-era slices — Windows-1254 Word exports; bs4
  charset sniffing decodes them) → ``html_to_text`` with no keep selector
  (Word exports carry no wrapper container) and two fixed hint lines
  dropped ("Resmî Gazete" masthead repeat, "Print"). An image-only body
  (``<img`` present, < 40 extracted chars — the probed kadro-decision GIF
  slices, ~3,400) is an expected empty: no text exists to clean.
- anything else (OLE ``D0CF11E0`` doc/xls, ``GIF8`` — the probed
  attachment tail, 760) → expected empty: binary formats have no text
  channel in v1 scope.

Both productive legs end in one ``CleanedRecord`` per document at
version 1. Seeding covers every ``rg_item``-produced document (99,546);
explained empties keep the task done with no cleaned row, so re-seeds
after a version bump revisit them.
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
    geometry_pdf_to_text_streamed,
    html_to_text,
    measure_pdf,
)

__all__ = ["CLEAN_VERSION", "RgCleanHandler"]

#: v2 (2026-11-03): undeclared anchor-era slices decode cp1254 (was:
#: utf-8/replace, which destroyed every Turkish letter into U+FFFD —
#: 10,703 records re-cleaned); v1 (2026-10-16): initial scope.
CLEAN_VERSION = 2

#: Extracted chars below which a PDF has no text layer (scan; census
#: 2026-10-16: ~2,465, 11% of the PDF corpus, 2005-2019 concentrated).
_SCAN_CHAR_FLOOR = 20

#: Extracted chars below which an HTML body counts as image-only/ornament
#: (census 2026-10-16: ~3,400 anchor-era GIF slices + separator rows).
_IMAGE_ONLY_FLOOR = 40

#: Glyph-soup signature of PDFs whose embedded fonts lack ToUnicode maps
#: (census 2026-10-16: ~1,675, all 2022+). Counted over the head of the
#: extraction — the tokens permeate every line when present.
_CID_MARK = "(cid:"

#: PDFs at or above this size take the page-streaming geometry leg. The
#: in-memory geometry holds every page's layout objects at once; the
#: corpus's largest item (308 MB — Karar No. 8561, the SOLAS 74/1978
#: technical-annex amendments, Mükerrer 2024-05-27) MemoryError'd it on
#: 8 GB (probed 2026-11-03). Everything below cleaned fine in memory
#: (85k records), so the threshold stays far above the observed range.
_STREAM_BYTES = 100 * 1024 * 1024

_HTML_MAGICS = (b"<", b"\xef\xbb\xbf")  # '<' or UTF-8 BOM

#: Fixed masthead hint lines of the Word-export HTML (whole-line matches;
#: date/issue lines are doc-specific and kept — they inform).
_HTM_DROP_LINES = ("Resmî Gazete", "Print")

_CHARSET_RE = re.compile(rb'charset=["\']?([\w-]+)', re.IGNORECASE)

#: XML 1.0 forbids C0 controls other than tab/LF/CR inside text nodes, and
#: the framework's unified-XML readback gate (unified-xml-spec v1.0)
#: parses every cleaned product back — cp1254-era extractions do surface
#: stray controls (form feeds et al.), which would fail that gate. Stripped
#: deterministically before the record is emitted.
_XML_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _sanitize(text: str) -> str:
    return _XML_ILLEGAL.sub("", text)


def _normalize(text: str) -> str:
    """The engine's readback enforces the output contract byte-level
    (no BOM, no CR, exactly one trailing newline) — PDF geometry output
    violates it whenever the source uses CR operators (live: 702 permanents
    2026-11-02). HTML leg conforms by construction; applied to both for
    symmetry. Idempotent."""
    text = _sanitize(text).replace("﻿", "")
    text = "\n".join(text.splitlines())
    return text.rstrip("\n") + "\n" if text else ""


def _decode_declared(data: bytes) -> bytes:
    """Decode with the file's own declared code page, re-encode UTF-8, and
    strip the (now wrong) meta declaration — so BeautifulSoup's charset
    detection sees clean UTF-8 instead of running its slow statistical
    pass on every Windows-1254 Word export (probed 2026-11-02: 0.5–2 s
    per 20 KB file, the clean run's bottleneck; ~10 ms after).

    Undeclared files — the anchor-era item slices (2000-2004), bare
    ``<a name>`` fragments cut mid-body with no head at all — are
    windows-1254, the gazette's Word-export encoding of that era. They
    must NOT ride the utf-8/replace default: every Turkish letter would
    become U+FFFD (live: 10,703 anchor-era records, surfaced by the
    quality eyeball 2026-11-03). Strict UTF-8 validation instead: a
    genuine UTF-8 file passes untouched, and Turkish cp1254 text (high
    bytes on every other word) practically never validates as UTF-8, so
    the cp1254 fallback fires exactly on the era slices."""
    codec: str | None = None
    match = _CHARSET_RE.search(data[:600])
    if match:
        declared = match.group(1).decode("ascii", errors="replace")
        if declared in ("windows-1254", "cp1254"):
            codec = "cp1254"
    if codec is None:
        try:
            data.decode("utf-8")
            codec = "utf-8"
        except UnicodeDecodeError:
            codec = "cp1254"
    decoded = data.decode(codec, errors="replace")
    decoded = re.sub(r"(?i)<meta[^>]+charset[^>]*>\s*", "", decoded)
    return decoded.encode("utf-8")


class RgCleanHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(local_doc=str(task.params["doc_id"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        doc_id = str(task.params["doc_id"])
        data = response.content

        if data.startswith(b"%PDF-"):
            return self._pdf_leg(doc_id, data)

        if data.startswith(_HTML_MAGICS):
            return self._html_leg(doc_id, data)

        # OLE compound files (doc/xls: D0CF11E0), GIF87a/89a, and any other
        # binary: no text channel in v1 scope — explained empty, task done.
        return TaskResult(
            expected_empty=(
                f"rg_clean {doc_id}: binary carrier ({data[:4]!r}) — doc/xls/gif "
                "attachments have no text channel in v1 scope"
            ),
        )

    def _pdf_leg(self, doc_id: str, data: bytes) -> TaskResult:
        if b"/Font" not in data:
            # cheap pre-gate: image-only scanned PDFs declare no font
            # resources at all, while pdfminer's full-layout pass on a
            # multi-megabyte scan costs minutes (probed: anchor-era files
            # at 4.8 MB avg, max 98 MB). Everything with a text layer
            # carries /Font — let it through to the real measurement.
            return TaskResult(
                expected_empty=(
                    f"rg_clean {doc_id}: scanned PDF (no font resources) — "
                    "OCR out of scope (2026-09-19 ruling)"
                ),
            )
        try:
            measure = measure_pdf(data)
        except Exception as exc:
            raise PermanentError(
                f"{doc_id}: malformed PDF ({type(exc).__name__}: {exc})"
            ) from exc
        chars = int(measure["chars"])
        if chars < _SCAN_CHAR_FLOOR:
            return TaskResult(
                expected_empty=(
                    f"rg_clean {doc_id}: scanned PDF ({measure['pages']} page(s), "
                    f"{chars} text chars) — OCR out of scope (2026-09-19 ruling)"
                ),
            )
        if len(data) >= _STREAM_BYTES:
            # treaty-sized item: page-streaming geometry (same output
            # contract; the in-memory twin would MemoryError)
            text = geometry_pdf_to_text_streamed(data)
        else:
            text = geometry_pdf_to_text(data)
        if not text.strip():
            # the measure/geometry char-count mismatch shape (live: 703
            # permanents 2026-11-02, 2012-13 concentrated): a text-less
            # body yields an empty record, which the engine's determinism
            # gate rejects — explained empty, same OCR boundary
            return TaskResult(
                expected_empty=(
                    f"rg_clean {doc_id}: PDF yields no extractable text "
                    "(text-less container) — OCR out of scope"
                ),
            )
        head = text[:400]
        if head.count(_CID_MARK) >= 5:
            # Embedded fonts without ToUnicode maps — glyph indices, not
            # characters. Uninterpretable output: excluded from v1 scope
            # (an alternative extraction channel is an architecture-side
            # decision), NOT a scan — recorded as its own reason.
            return TaskResult(
                expected_empty=(
                    f"rg_clean {doc_id}: PDF text is CID glyph soup (fonts "
                    "without ToUnicode maps) — no interpretable text; "
                    "alternative channel pending architecture decision"
                ),
            )
        return TaskResult(
            cleaned=[CleanedRecord(
                doc_id=doc_id,
                version=CLEAN_VERSION,
                content=_normalize(text).encode("utf-8"),
            )],
        )

    def _html_leg(self, doc_id: str, data: bytes) -> TaskResult:
        text = html_to_text(_decode_declared(data), drop_strings=_HTM_DROP_LINES)
        if not text.strip():
            return TaskResult(
                expected_empty=(
                    f"rg_clean {doc_id}: HTML body extracts to nothing — "
                    "no text to clean"
                ),
            )
        if len(text.strip()) < _IMAGE_ONLY_FLOOR:
            kind = "image-only slice" if b"<img" in data.lower() else "ornament-only body"
            return TaskResult(
                expected_empty=(
                    f"rg_clean {doc_id}: {kind} ({len(text.strip())} chars after "
                    "extraction) — scanned/image content, no text to clean"
                ),
            )
        return TaskResult(
            cleaned=[CleanedRecord(
                doc_id=doc_id,
                version=CLEAN_VERSION,
                content=_normalize(text).encode("utf-8"),
            )],
        )
