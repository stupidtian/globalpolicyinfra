"""Task type ``retsinformation_clean``: one document -> deterministic plain text.

The corpus has exactly one full-text carrier per document (probed
2026-09-29, whole-library census in the task folder's clean-probe/):
32,630 documents carry the official LexDania XML with a ``DokumentIndhold``
body; 10,167 stub-era documents (1963-2007 plus 34 harvest-era stragglers)
carry a ``text.html`` sibling whose XML is metadata-only. The two sets are
disjoint and complete — every document cleans from exactly one carrier,
so the handler sniffs the bytes it is handed and routes to one of two
probed rule sets (no era logic; a year can mix carriers, 2007 does):

===============  ==================================================================
leg              rules
===============  ==================================================================
XML              ``xml_to_text`` with the Danish legislative block vocabulary
                 (Exitus/Linea/Paragraf/Stk/Rubrica/Kapitel/.../Tr/Td — see
                 clean-plan.md §1.2; declared lowercase, the framework matches
                 case-insensitively); ``Meta`` subtree dropped (pure metadata,
                 the ledger already carries it); ``Char``/``Indentatio`` stay
                 inline so words never split. An empty body container (no text
                 after the drop) is an explained empty, not a fault.
HTML             ``html_to_text`` with ``keep="#INDHOLD"`` — the server-rendered
                 full-text container; every piece of page furniture (bjelke
                 banners, the table-of-contents, "Den fulde tekst" hints,
                 FONT/ALIGN legacy markup) sits outside it and vanishes; HTML
                 entities decode in the wash.
===============  ==================================================================

A zero ``keep`` match or bytes matching neither carrier shape raises
PermanentError — loud, never silent (shape mutation must fail loudly).
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
from runtime.stages.cleaning import html_to_text, xml_to_text

__all__ = ["CLEAN_VERSION", "RetsinformationCleanHandler"]

CLEAN_VERSION = 1

#: Danish legislative block vocabulary (clean-plan.md §1.2), lowercase —
#: the framework strips namespaces and lowercases before matching.
_XML_BLOCK_TAGS: tuple[str, ...] = (
    "exitus", "linea", "paragraf", "stk", "rubrica", "kapitel",
    "paragrafgruppe", "bog", "afsnit", "indledning", "ikraft",
    "ikraftcentereretparagraf", "nota", "tr", "td", "table", "explicatus",
    "index", "tekstgruppe", "underskriftgruppe",
)

#: Pure metadata — accessions, journal numbers, validity windows; the
#: ledger carries all of it, the rendered text must not.
_XML_DROP_TAGS: tuple[str, ...] = ("meta",)

#: The stub-era HTML body containers (probed 2026-09-29). ``#INDHOLD``
#: carries the text of every ordinary document; a rare annex-order family
#: (orders whose body IS the annex — e.g. 2006/62 surveillance tables)
#: leaves INDHOLD empty and puts the content in ``#GIVET`` (signature
#: block) plus the ``BILAG`` divs. The whitelist keeps all three; matching
#: none of them is a loud shape mutation.
_HTML_KEEP = "#INDHOLD, #GIVET, [id^=B]"

#: The no-text markers: the source's own notice paragraphs delivered in
#: place of a document body (both probed 2026-09-29 during the first clean
#: sweep). Each is *data* ("no full text exists on the site"), not a
#: container-shape mutation:
#: - Faroe/Greenland documents promulgated before 2008 exist only in the
#:   printed Lovtidende A (five occurrences library-wide);
#: - Lovtidende B budget/appropriation acts are never entered into
#:   retsinformation.dk at all — only the printed part B and a PDF link
#:   (the ltb suffix of the corpus).
_PRINT_ONLY_MARKERS: tuple[bytes, ...] = (
    b"kun i den trykte udgave af Lovtidende",
    b"ikke indlagt i retsinformation.dk",
)


def _is_xml(content: bytes) -> bool:
    """Carrier sniff: LexDania XML vs server-rendered HTML. Text.html is
    only ever written with non-empty documentHtml, so it always starts
    with markup/whitespace that is not an XML declaration or Dokument."""
    stripped = content.lstrip()[:200]
    return stripped.startswith((b"<?xml", b"<Dokument"))


class RetsinformationCleanHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(local_doc=str(task.params["doc_id"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        doc_id = str(task.params["doc_id"])
        content = response.content
        if not content.strip():
            raise PermanentError(f"clean {doc_id}: stored file is empty")
        if _is_xml(content):
            text = xml_to_text(
                content, block_tags=_XML_BLOCK_TAGS, drop_tags=_XML_DROP_TAGS
            )
            if not text.strip():
                # a body container with nothing in it — the source has no
                # rendered text for this document (probed shape: zero in the
                # whole library, kept as a loud-but-done safety net)
                return TaskResult(
                    expected_empty=(
                        f"clean {doc_id}: XML body container carries no text "
                        "(metadata-only rendition, no full text on the source)"
                    )
                )
        elif b"<" in content:
            if any(marker in content for marker in _PRINT_ONLY_MARKERS):
                return TaskResult(
                    expected_empty=(
                        f"clean {doc_id}: print-only document — the source "
                        "offers no full text, only a printed-Lovtidende notice "
                        "(Faroe/Greenland pre-2008, or Lovtidende B budget acts)"
                    )
                )
            try:
                text = html_to_text(content, keep=_HTML_KEEP)
            except ValueError as exc:
                raise PermanentError(f"clean {doc_id}: {exc}") from exc
        else:
            raise PermanentError(
                f"clean {doc_id}: stored bytes match neither carrier shape "
                "(no XML declaration/Dokument root, no HTML markup)"
            )
        return TaskResult(
            cleaned=[
                CleanedRecord(
                    doc_id=doc_id, version=CLEAN_VERSION, content=text.encode("utf-8")
                )
            ]
        )
