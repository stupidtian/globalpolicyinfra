"""Task type ``finlex_clean``: render one stored AkomaNtoso XML to plain text.

Reads the stored XML via ``RequestSpec.local_doc`` (no network) and renders
it with the framework's ``xml_to_text`` — one engine, two functions: this
pack declares the AkomaNtoso vocabulary, never a converter (framework
increment 2026-09-29, first consumers DNK then FIN).

Block map probed 2026-10-03 across 11 samples × 11 decades (1917–2025,
docs/tasks/2026-09-13-fin/clean-probe/) plus a 1,500-file tag-frequency
audit — every structural tag in the corpus classified, zero parse
failures:

- **drop** ``meta`` (the whole identification/FRBR*/references/proprietary
  subtree — bibliography, never body text);
- **block** (line break): the act scaffolding (preface, preamble with its
  enacting clause, body, conclusions), the provision hierarchy (part /
  chapter / section / subsection / paragraph / subparagraph / intro / num),
  headings (heading, crossHeading, docTitle, docNumber, formula),
  containers (content, hcontainer, block, blockContainer, tblock, list,
  item, level, wrapUp, p, br), tables (table / tr / td / caption — one
  cell per line), signatures, and the finlex extensions (img, latex,
  foreign, statuteBookOfFinlandReference);
- **inline** (everything not declared — text kept, words never split):
  b, i, sub, sup, ref, person, role, a, span, affectedDocument, …

Language scope (user ruling 2026-09-14, single-language = Finnish): a
stored document whose expression language is not ``fin`` is an explained
empty — the swe files collected by the legacy bilingual chain keep their
ledger rows but produce no cleaned text (back-fill them later by bumping
the rule version, zero rebuild).

Latex strings (e.g. ``$ K_{tapa} \\cdot S \\cdot 1295,50 \\, \\text{€} $``)
are kept verbatim — fidelity over rendering; the analysis side decides
what to do with them.
"""

from __future__ import annotations

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

__all__ = ["BLOCK_TAGS", "CLEAN_VERSION", "DROP_TAGS", "FinlexCleanHandler"]

CLEAN_VERSION = 1

#: Line-break vocabulary: every structural tag observed in the corpus
#: (1,500-file audit) that carries or delimits body text.
BLOCK_TAGS: tuple[str, ...] = (
    # act scaffolding
    "act", "preface", "preamble", "body", "conclusions",
    # provision hierarchy
    "part", "chapter", "section", "subsection", "paragraph",
    "subparagraph", "intro", "num",
    # headings
    "heading", "crossHeading", "docTitle", "docNumber", "formula",
    # containers / paragraphs
    "content", "hcontainer", "block", "blockContainer", "tblock",
    "list", "item", "level", "wrapUp", "p", "br",
    # tables: one cell per line
    "table", "tr", "td", "caption",
    # signature block
    "signature",
    # finlex extensions / misc
    "img", "latex", "foreign", "statuteBookOfFinlandReference",
)

#: Subtrees removed whole (bibliography never reaches the text).
DROP_TAGS: tuple[str, ...] = ("meta",)

_AKN = "{http://docs.oasis-open.org/legaldocml/ns/akn/3.0}"


class FinlexCleanHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(local_doc=str(task.params["doc_id"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        doc_id = str(task.params["doc_id"])
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise PermanentError(f"{doc_id}: body is not XML: {exc}") from exc
        if not root.tag.endswith("akomaNtoso"):
            raise PermanentError(
                f"{doc_id}: unexpected root element {root.tag!r}"
            )

        # Single-language scope: the expression's language, straight from
        # the record (legacy bilingual-chain files ride the same queue).
        lang = ""
        for node in root.iter(f"{_AKN}FRBRlanguage"):
            lang = (node.get("language") or "").strip()
            break
        if lang and lang != "fin":
            return TaskResult(
                expected_empty=(
                    f"{doc_id}: expression language {lang!r} — outside the "
                    "single-language (Finnish) scope; re-clean with "
                    "version+1 after widening langs to include it"
                )
            )

        try:
            text = xml_to_text(
                response.content,
                block_tags=BLOCK_TAGS,
                drop_tags=DROP_TAGS,
            )
        except ValueError as exc:
            raise PermanentError(f"{doc_id}: {exc}") from exc
        if not text.strip():
            raise PermanentError(
                f"{doc_id}: rendered text is empty — a body the block map "
                "cannot see is a loud failure, never a silent blank"
            )
        record = CleanedRecord(
            doc_id=doc_id,
            version=CLEAN_VERSION,
            content=text.encode("utf-8"),
        )
        return TaskResult(cleaned=[record])
