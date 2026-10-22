"""Task type ``kanpo_clean``: gazette PDF → deterministic plain text.

A thin subclass of the framework's :class:`runtime.stages.pdf_clean.
PdfCleanHandler` — registered under the kanpo source's
``CleanDefinition`` — adding the two Japan-specific decorations on top of
the framework geometry channel (see clean-plan §2.1; rules verified on
the 23-sample P0 in ``clean-probe/``):

- **Masthead height filter** (``max_char_height=9.5``): the gazette's
  masthead — the horizontal date row, the issue-number row, the 官報
  logotype, the vertical doc-kind labels (規則/その他告示…) — is always
  set in 10/12/14pt type while *all* body text is 5–9pt (23/23 P0
  samples). One pre-assembly filter removes every masthead char and, with
  them, every masthead garble (PUA digits of the 2016+ era and the
  unmapped CIDs of 2003–2015 live exclusively in those rows). Date and
  issue numbers survive losslessly in the ledger's meta columns.
- **Line rules** (post-assembly, deterministic): runs of a repeated
  decoration glyph rendered at body height by the 2016+ layout — column
  rules as ``(cid:23075)`` repeats, rule segments as PUA repeats, the
  2003–2008 left-edge ruler as ``GGGG…`` — assemble into standalone
  lines that match one of three shapes and are dropped.

No PUA mapping table: PUA assignments are per-document font subsets
(\ue890 is a date digit in one PDF and a rule glyph in another), so a
global char map is unsafe; everything decodable already dies with the
masthead. Unmapped ``(cid:N)`` residues outside run-lines stay verbatim
(clean-brief default).

The Mineru branch is deliberately unwired: kanpo declares an empty
``pdf_rules`` table (everything digital-native routes to geometry, P0),
and any future rule addition must come back to this handler on purpose —
raising loudly here beats silently diverging from the framework router.
"""

from __future__ import annotations

import re

from adapters.base import CleanedRecord, Response, TaskResult, TaskView
from runtime.errors import PermanentError
from runtime.stages.cleaning import geometry_pdf_to_text
from runtime.stages.pdf_clean import SCAN_CHAR_FLOOR, PdfCleanHandler

__all__ = [
    "MASTHEAD_CHAR_HEIGHT",
    "KanpoCleanHandler",
    "drop_decoration_line",
]

#: Body text is uniformly 5–9pt, masthead/logotype/kind-labels 10/12/14pt
#: (clean-probe analysis_height.txt, 23/23 samples). 9.5 sits in the gap.
MASTHEAD_CHAR_HEIGHT = 9.5

#: R1 — a run (>=2) of one repeated ``(cid:N)`` token: the 2016+ layout
#: renders vertical column rules as glyphs; isolated in their own x-band
#: they assemble into standalone run-lines.
_CID_RUN = re.compile(r"^\(cid:(\d+)\)(?:\(cid:\1\))*$")
#: R2 — a run (>=2) of one repeated PUA char: rule/stamp segments.
_PUA_RUN = re.compile(r"^([\ue000-\uf8ff])\1+$")
#: R3 — a run (>=3) of one repeated ASCII letter: the 2003–2008 left-edge
#: ruler is a column of twelve "G" glyphs.
_ASCII_RUN = re.compile(r"^([A-Za-z])\1{2,}$")
#: R4 — a Latin-letter border run with corners: 別表 tables in the
#: tategaki layout are set rotated, so their drawn borders land as glyph
#: stacks in body-font height mapping to arbitrary ASCII letters
#: (2004-12-15 政令: top edge "ioooo…k", sides "l"/"m"). Corner letters
#: plus a >=3 repeat of one letter is a border, never Japanese content.
_LATIN_BORDER = re.compile(r"^[A-Za-z]*([A-Za-z])\1{2,}[A-Za-z]*$")
#: R5 — the postal-permit colophon ("明治二十五年三月三十一日第三種郵便物
#: 認可…発行者…印刷者…"): page furniture on ~11% of pages (500-doc
#: eyeball, 2026-09-30). Only the short unambiguous phrases drop — the
#: bare date line stays (it is the *content* of rescript-reprint extras)
#: and so do 発行者/印刷者 lines (financial statutes use 発行者 in body
#: text — 2012-07-30 郵政民営化施行省令 in-corpus proof).
_COLOPHON_MARKS = ("第三種郵便物認可", "この刊行物")
#: R6 — a lone Latin-1 supplement char: the postal mark 〒 maps to "¾"
#: in the old font subset and lands as a one-char line.
_LONE_LATIN1 = re.compile(r"^[¡-ÿ]$")


def drop_decoration_line(line: str) -> bool:
    """True when the whole assembled line is decoration, not content."""
    if not line:
        return False
    if (
        _CID_RUN.match(line)
        or _PUA_RUN.match(line)
        or _ASCII_RUN.match(line)
        or _LATIN_BORDER.match(line)
        or _LONE_LATIN1.match(line)
    ):
        return True
    return len(line) <= 24 and any(mark in line for mark in _COLOPHON_MARKS)


class KanpoCleanHandler(PdfCleanHandler):
    """Framework PDF router with the kanpo masthead/line decorations.

    Geometry-only fast path: with the empty ``pdf_rules`` table the
    framework router is a constant ("geometry"), so the separate
    ``measure_pdf`` pass adds a full second PDF parse per document for
    nothing. This override parses once — the scan floor is judged on the
    extracted text instead of the measure dict (equivalent for a corpus
    where every page carries body text; loud either way). Output bytes
    are identical to the two-parse path. If rules ever become non-empty
    the fast path refuses loudly, same as the framework contract.
    """

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        doc_id = str(task.params["doc_id"])
        if self._definition.pdf_rules:
            raise PermanentError(
                f"kanpo pdf_rules must stay empty (geometry-only corpus); "
                f"doc {doc_id} — extend this handler deliberately before "
                "declaring rules"
            )
        text = geometry_pdf_to_text(
            response.content, max_char_height=MASTHEAD_CHAR_HEIGHT
        )
        if len("".join(text.split())) < SCAN_CHAR_FLOOR:
            raise PermanentError(
                f"扫描件——OCR 界外: doc {doc_id} extracted "
                f"{len(''.join(text.split()))} text chars; scanned documents "
                "are out of scope (2026-09-19 user ruling)"
            )
        kept = [
            line
            for line in text.split("\n")
            if not drop_decoration_line(line)
        ]
        return TaskResult(
            cleaned=[
                CleanedRecord(
                    doc_id=doc_id,
                    version=int(task.params["v"]) * 100,  # geometry: fingerprint 0
                    content="\n".join(kept).encode("utf-8"),
                )
            ]
        )
