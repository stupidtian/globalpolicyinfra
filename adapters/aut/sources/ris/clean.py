"""Task type ``bgbl_clean``: one gazette XML -> deterministic plain text.

The corpus is single-carrier (probed 2026-10-03 over the full library,
census in the task folder's clean-probe/): 22,525 documents carry a
``risdok`` root and one carries ``erechtdok`` (the e-recht converter's
rendition of BGBLA_2018_II_314) — same inner layout, one rule set. The
handler renders with the framework's ``xml_to_text`` over the RIS
vocabulary (clean-plan.md §2):

===============  ==================================================================
role             rules
===============  ==================================================================
drop (7)         ``metadaten`` (always empty — the ledger carries it),
                 ``layoutdaten`` (page geometry), ``kzinhalt``/``fzinhalt``
                 (per-page running heads "BGBl. II - Ausgegeben am …" and
                 footers "www.ris.bka.gv.at"), ``classes`` (CSS stylesheet
                 text), ``binary``/``src`` (image placeholders)
block (32)       ``absatz`` (1.3M, the workhorse), ``ueberschrift``, section/
                 list/table families (``td`` = one cell per line, DNK-style),
                 ``schluss``/``unterschrift`` closing blocks, ``inhaltsvz``,
                 ``fntext``, the ``ausgabe`` masthead lines, and the rare
                 ``beschr``/``pdvorlage``/``pdeinst``/``pre``/``div``
glyph map (16)   RIS encodes characters as EMPTY elements named after the
                 glyph — ``<ldquo/>`` is “, ``<bdquo/>`` is „, ``<gdash/>``
                 is –, ``<euro/>`` is €, ``<nbsp/>`` (543k) is THE word
                 separator (``BGBl. Nr.<nbsp/>651/1989``). Left alone, the
                 engine would concatenate across them: quotes/dashes/currency
                 lost corpus-wide and words fused. A handler-side pure pass
                 injects the character into the empty element (plus numeric
                 ``uchar code`` decoding and ``br`` -> space, user-ruled
                 2026-10-03) before ``xml_to_text`` runs. Mechanical format
                 conversion, zero semantics.
===============  ==================================================================

All 78 tag names of the full-library census are accounted for; a tag
outside that vocabulary (or a root other than risdok/erechtdok) is a
shape mutation and raises PermanentError — loud, never silently inlined.
A text-free rendition after the drops is a source-side data gap (2 scan-era
OCR stubs library-wide) and is recorded as an explained empty — no cleaned
row, task done.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import cast

from adapters.base import (
    CleanedRecord,
    RequestSpec,
    Response,
    TaskResult,
    TaskView,
)
from runtime.errors import PermanentError
from runtime.stages.cleaning import xml_to_text

__all__ = ["CLEAN_VERSION", "BgblCleanHandler"]

CLEAN_VERSION = 1

_ROOTS = ("risdok", "erechtdok")

#: Block vocabulary (clean-plan.md §2.2), lowercase — the framework
#: matches case-insensitively and namespace-free.
_BLOCK_TAGS: tuple[str, ...] = (
    "abschnitt",
    "absatz", "ueberschrift",
    "ausgabe", "adtext", "addat", "adid",
    "liste", "listelem", "aufzaehlung", "ziffernliste", "literaliste",
    "subliteraliste", "betragliste", "betraglistetgue", "erlliste", "strichliste",
    "table", "thead", "tr", "td",
    "schluss", "schlussteil", "unterschrift", "inhaltsvz",
    "fntext", "fnen",
    "beschr", "pdvorlage", "pdeinst", "pre", "div",
)

#: Subtrees that never reach the text (clean-plan.md §2.1).
_DROP_TAGS: tuple[str, ...] = (
    "metadaten", "layoutdaten", "kzinhalt", "fzinhalt", "classes", "binary", "src",
)

#: Empty elements whose NAME is the glyph (clean-plan.md §2.3). ``br``
#: joins the line with a space (user ruling 2026-10-03, Q2=B).
_GLYPHS: dict[str, str] = {
    "nbsp": " ",
    "tab": " ",
    "br": " ",
    "gdash": "–",
    "bdash": "-",
    "ldquo": "“",
    "bdquo": "„",
    "rdquo": "”",
    "sbquo": "‚",
    "rsquo": "’",
    "amp": "&",
    "gt": ">",
    "lt": "<",
    "euro": "€",
    "dots": "…",
    # "uchar" is not here: its character rides in the code attribute and is
    # decoded numerically in the same pass.
}

#: Every tag name observed in the 22,526-file census (block + drop + glyph
#: + the inline-neutral rest + the two roots). Anything else is a loud
#: shape mutation (clean-plan.md §2.4).
_KNOWN_TAGS = frozenset({
    *_BLOCK_TAGS, *_DROP_TAGS, *_GLYPHS, "uchar",
    "risdok", "erechtdok", "nutzdaten",
    "n", "gldsym", "feld", "b", "i", "u", "sub", "super", "span", "em",
    "symbol", "kidea", "lidea", "gs", "fnzeichen", "abstand", "wechsel",
    "aw", "en", "link",
})


def prepare(raw: bytes) -> bytes:
    """One parse, three mechanical passes: root check, unknown-tag check,
    glyph injection. Pure; same input -> same output bytes."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise PermanentError(f"stored file is not XML: {exc}") from exc
    root_name = root.tag.split("}")[-1]
    if root_name not in _ROOTS:
        raise PermanentError(f"unexpected root element {root.tag!r}")
    glyphs = _GLYPHS
    for el in root.iter():
        name = el.tag.split("}")[-1]
        if name not in _KNOWN_TAGS:
            raise PermanentError(f"unknown element <{name}> — shape mutation")
        if el.text:
            continue
        if name in glyphs:
            el.text = glyphs[name]
        elif name == "uchar":
            code = el.get("code") or ""
            el.text = chr(int(code)) if code.isdigit() else ""
    return cast(bytes, ET.tostring(root, encoding="utf-8"))


class BgblCleanHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(local_doc=str(task.params["doc_id"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        doc_id = str(task.params["doc_id"])
        if not response.content.strip():
            raise PermanentError(f"clean {doc_id}: stored file is empty")
        prepared = prepare(response.content)
        text = xml_to_text(prepared, block_tags=_BLOCK_TAGS, drop_tags=_DROP_TAGS)
        if not text.strip():
            # Source-side data gap, not a handler fault (first seen in the
            # full run 2026-10-04, 2 occurrences library-wide: 2001_122_2,
            # 2003_41_1 — scan-era OCR renditions consisting solely of empty
            # paragraphs and an EMPTY signature block; the sibling 2003_42_1
            # at least carries the signature text). Data fact -> explained
            # empty, done without a cleaned row (DNK stub-family precedent).
            return TaskResult(
                expected_empty=(
                    f"clean {doc_id}: the source rendition carries no text at "
                    "all — scan-era OCR produced only empty paragraphs and an "
                    "empty signature block"
                )
            )
        return TaskResult(
            cleaned=[
                CleanedRecord(
                    doc_id=doc_id, version=CLEAN_VERSION, content=text.encode("utf-8")
                )
            ]
        )
