"""Task type ``boe_clean``: one gazette item XML -> deterministic plain text.

Single-carrier corpus (full census 2026-10-08, 31,057 files, zero parse
errors, evidence in the task folder's clean-probe/): every file roots at
``<documento fecha_actualizacion=…>`` carrying up to four blocks —

===============  ==================================================================
block            content / rule (clean-plan.md §1–§2, user-ruled 2026-10-08)
===============  ==================================================================
metadatos        bibliographic fields — dropped; its ``titulo`` is prepended
                 as the finished text's first line (user ruling Q1: the
                 printed gazette starts with the title; the body itself
                 never carries it, 24/24 probed fixtures)
metadata-eli     ELI RDF — dropped (absent in 3,607 items, both root shapes
                 are known)
analisis         subjects / alert keywords / regulation references — dropped
                 whole: each ``referencia`` owns a nested ``<texto>``
                 description element (141,873 texto elements vs 31,057
                 documents — the name collision the block drop swallows;
                 never pick texto by name)
texto            the body — the only content source
===============  ==================================================================

Vocabulary (all 30 inner tag names of the census are accounted for):
``p`` is the workhorse (8.5M); the table family renders one cell per line
(DNK convention); ``br`` forces a line break (user ruling Q2 — table-cell
stacked items and signature-title folds, unlike AUT's space join whose
context was the RIS glyph stream); ``tp`` is the source's one-time typo of
``<p>`` (same class/position, BOE-A-2018-17694) and renders as p; the 13
inline names (strong/em/span/sup/sub/…/img/col) never split words — img
and col are always empty, they contribute zero characters.

An empty body (19 scan-delivered documents — Constitutional Court
autos whose only carrier is the PDF) is an explained empty, not a handler
fault (AUT stub precedent): task done, no cleaned row. A tag outside the
census vocabulary, a foreign root or malformed XML is a shape mutation
and raises PermanentError — loud, never silently inlined.
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

__all__ = ["CLEAN_VERSION", "BoeCleanHandler"]

CLEAN_VERSION = 1

_ROOT = "documento"

#: Block vocabulary (clean-plan.md §1.3) — lowercase; the framework
#: matches case-insensitively and namespace-free.
_BLOCK_TAGS: tuple[str, ...] = (
    "p", "tp",
    "table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption", "colgroup",
    "blockquote", "br", "ul", "li", "pre", "div",
)

#: Whole subtrees that never reach the text. ``alerta`` is always inside
#: ``analisis`` (census: 60,340/60,340) — listed as belt-and-suspenders.
_DROP_TAGS: tuple[str, ...] = ("metadatos", "metadata-eli", "analisis", "alerta")

#: Inline-neutral names — never split words; img/col are always empty.
_INLINE_KNOWN: tuple[str, ...] = (
    "strong", "em", "span", "sup", "sub", "abbr", "u", "b", "i",
    "acronym", "font", "img", "col",
)

#: Every tag name observed in the 31,057-file census (block + drop +
#: inline + the two containers). Anything else is a loud shape mutation.
_KNOWN_TAGS = frozenset({*_BLOCK_TAGS, *_DROP_TAGS, *_INLINE_KNOWN, _ROOT, "texto"})

_WHITESPACE_RUN = re.compile(r"[ \t\r\n\f\v\u00a0]+")


def _local(tag: str) -> str:
    return tag.rpartition("}")[-1].lower()


class BoeCleanHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(local_doc=str(task.params["doc_id"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        doc_id = str(task.params["doc_id"])
        if not response.content.strip():
            raise PermanentError(f"clean {doc_id}: stored file is empty")
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise PermanentError(f"clean {doc_id}: stored file is not XML: {exc}") from exc
        if _local(root.tag) != _ROOT:
            raise PermanentError(f"clean {doc_id}: unexpected root element {root.tag!r}")

        drops = {t.lower() for t in _DROP_TAGS}

        def audit(element: ET.Element) -> None:
            # Mirrors the renderer: dropped subtrees are removed before the
            # walk, so their inner vocabulary (metadatos' 33 fields, the ELI
            # RDF names, ...) is out of scope by construction.
            name = _local(element.tag)
            if name in drops:
                return
            if name not in _KNOWN_TAGS:
                raise PermanentError(
                    f"clean {doc_id}: unknown element <{name}> — shape mutation"
                )
            for child in element:
                audit(child)

        audit(root)

        body = xml_to_text(response.content, block_tags=_BLOCK_TAGS, drop_tags=_DROP_TAGS)
        if not body.strip():
            return TaskResult(
                expected_empty=(
                    f"clean {doc_id}: the gazette item carries no body text — "
                    "source delivered it as a scan PDF only (19 such documents, "
                    "Constitutional Court autos et al., census 2026-10-08)"
                )
            )

        title = ""
        metadatos = root.find("metadatos")
        if metadatos is not None:
            titulo = metadatos.find("titulo")
            if titulo is not None and titulo.text:
                title = _WHITESPACE_RUN.sub(" ", titulo.text).strip()
        text = f"{title}\n\n{body}" if title else body
        return TaskResult(
            cleaned=[
                CleanedRecord(doc_id=doc_id, version=CLEAN_VERSION, content=text.encode("utf-8"))
            ]
        )
