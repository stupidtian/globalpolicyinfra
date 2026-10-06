"""Task type ``bekendmakingen_clean``: one document -> deterministic plain text.

The whole ledger carries one gazette series (Staatsblad, ``stb``); the
shape variation lives in the full-text XML generations. A whole-corpus
census (16,464 files, 2026-10-03, clean-probe/) found exactly five body
roots, all parsed cleanly by stdlib ElementTree (the SDU-family external
DOCTYPE references are inert; no custom entity references occur):

===============  ========  =============================================
root             files     carrier
===============  ========  =============================================
officiele-       10,709    op-xsd-2014, the modern publication schema
publicatie
staatsbl         5,665     SDU DTD "staatsblad xml 1.1" (2000-2008)
vblad            81        verbeterblad corrected-sheet reprints (same
                           SDU 1.1 DTD family)
metadata         4         no full text on the source; the xml
                           manifestation is a bare metadata stub (~305 B)
staatsblad       5         SDU DTD "Staatsblad 1.61/1.64" strays
===============  ========  =============================================

The text-leaf vocabularies of the four full-text shapes do not collide
(33/34/29/17 tags, superset 47 blocks), so all shapes share ONE block
table + ONE inline whitelist + ONE drop list (clean-plan.md §3; the
tables are closed over the full-corpus text-leaf census). Blocks break
lines; inline wrappers (nadruk emphasis, sup footnote marks, extref
citations, soort/grslag clause fragments) flow so words never split;
``metadata``/``meta`` subtrees and the printer's order number are
dropped (the ledger already carries all of it). CalS tables render one
cell per line (``entry``).

Loudness: before rendering, the handler walks the parsed tree and
requires every text-bearing element's local name to be in the closed
vocabulary (blocks ∪ inline) — anything else is a shape mutation and
raises PermanentError naming the doc_id and the tag. Unknown roots,
malformed XML and empty files die loud the same way. The four
metadata-stub documents render to empty text — an explained empty (done,
not an error): the source simply has no full text behind them.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from adapters.base import (
    CleanedRecord,
    RequestSpec,
    Response,
    TaskResult,
    TaskView,
)
from runtime.errors import PermanentError
from runtime.stages.cleaning import xml_to_text

__all__ = ["CLEAN_VERSION", "BekendmakingenCleanHandler"]

CLEAN_VERSION = 1

#: Body roots across the corpus generations (census 2026-10-03). Anything
#: else is a shape change and dies loud.
KNOWN_ROOTS = frozenset(
    {"officiele-publicatie", "staatsbl", "vblad", "metadata", "staatsblad"}
)

#: Block vocabulary (clean-plan.md §3): closed over the full-corpus
#: text-leaf census; lowercase — the framework strips namespaces and
#: lowercases before matching. Structural containers without direct text
#: need no entry (only text-bearing elements force line breaks).
_XML_BLOCK_TAGS: tuple[str, ...] = (
    # running text
    "al", "considerans.al", "parlementair.al", "noot.al", "noot.nr", "nootnr",
    "wat", "term", "tuskop", "tussenkop",
    # headings and numbering
    "label", "nr", "li.nr", "lidnr", "intitule", "titel", "subtitel",
    # tables (CALS) — one cell per line
    "table", "row", "entry", "title", "bijschrift",
    # signature block and issue stamps
    "ondertekening", "functie", "organisatie", "naam", "plaats", "datum",
    "koning", "wij", "wie", "deze",
    "gegeven", "slotformulering", "slotform", "ondplts", "onddatum",
    "ondtekst", "minvan",
    "uitgegeven", "uitgifte-regel", "uitdag", "uitmaand", "uitjaar",
    # gazette front matter (kept as the printed issue header)
    "stbjaar", "stbnr", "jaargang",
    "afkondig",
)

#: Inline fragment wrappers: their text flows into the surrounding line
#: (never split off). Closed over the same census. ``voornaam``/
#: ``achternaam`` are inline so a name renders on one line inside its
#: block-level ``naam`` container in both generations (op-xsd children;
#: SDU direct text).
_XML_INLINE_TAGS: frozenset[str] = frozenset(
    {"nadruk", "sup", "extref", "inf", "soort", "grslag", "dossierref",
     "vetnr", "rijksnr", "aanhaling", "voornaam", "achternaam"}
)

#: Pure metadata — the ledger carries every field; the printer's order
#: number is production metadata. Whole subtrees removed.
_XML_DROP_TAGS: tuple[str, ...] = ("metadata", "meta", "ordernr", "versie")

#: The corpus omits whitespace at inline tag boundaries in places (print
#: artifact, probed 2026-10-03: ``<datum>Uitgegeven de<nadruk>eerste
#: </nadruk></datum>`` renders as "Uitgegeven deeerste" without this).
#: Deterministic country-side fix: insert a space after every opening and
#: before every closing INLINE tag; the engine's whitespace folding
#: collapses the doubles this creates where the source already had one.
_INLINE_SPACE_FIX = re.compile(
    rb"(<(?:"
    + b"|".join(t.encode() for t in sorted(_XML_INLINE_TAGS))
    + rb")[^>]*>)|(</(?:"
    + b"|".join(t.encode() for t in sorted(_XML_INLINE_TAGS))
    + rb")>)"
)


def _add_inline_spaces(content: bytes) -> bytes:
    return _INLINE_SPACE_FIX.sub(
        lambda m: m.group(1) + b" " if m.group(1) else b" " + m.group(2), content
    )


def _local(tag: str) -> str:
    return tag.rpartition("}")[-1].lower()


def _audit_vocabulary(root: ET.Element, doc_id: str) -> None:
    """Every text-bearing element must sit in the closed vocabulary.

    drop-tagged subtrees are skipped (their text is removed anyway);
    inline and block tags are both fine; anything else is an unmapped
    text carrier — a shape mutation that must fail loud, not leak into
    the output glued to a neighbouring line.
    """
    drops = {t.lower() for t in _XML_DROP_TAGS}
    allowed = frozenset(t.lower() for t in _XML_BLOCK_TAGS) | _XML_INLINE_TAGS

    def walk(el: ET.Element) -> None:
        tag = _local(el.tag)
        if tag in drops:
            return
        if el.text and el.text.strip() and tag not in allowed:
            raise PermanentError(
                f"clean {doc_id}: text-bearing element <{el.tag}> is outside the "
                "declared vocabulary (neither block nor inline) — shape change"
            )
        for child in el:
            walk(child)

    walk(root)


class BekendmakingenCleanHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(local_doc=str(task.params["doc_id"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        doc_id = str(task.params["doc_id"])
        content = response.content
        if not content.strip():
            raise PermanentError(f"clean {doc_id}: stored file is empty")
        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            raise PermanentError(
                f"clean {doc_id}: stored file is not parseable XML: {exc}"
            ) from exc
        root_name = _local(root.tag)
        if root_name not in KNOWN_ROOTS:
            raise PermanentError(
                f"clean {doc_id}: unknown body root <{root.tag}> "
                f"(known: {sorted(KNOWN_ROOTS)}) — shape change"
            )
        _audit_vocabulary(root, doc_id)
        text = xml_to_text(
            _add_inline_spaces(content),
            block_tags=_XML_BLOCK_TAGS,
            drop_tags=_XML_DROP_TAGS,
        )
        if not text.strip():
            # The metadata-stub generation (root <metadata>): the source
            # keeps no full text behind these files — an explained empty,
            # done (clean_type exclusion stops re-seeding).
            return TaskResult(
                expected_empty=(
                    f"clean {doc_id}: no text after the metadata drop "
                    "(metadata-only rendition, no full text on the source)"
                )
            )
        return TaskResult(
            cleaned=[
                CleanedRecord(
                    doc_id=doc_id, version=CLEAN_VERSION, content=text.encode("utf-8")
                )
            ]
        )
