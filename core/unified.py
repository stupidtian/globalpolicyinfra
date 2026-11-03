"""The unified document model and its XML contract (unified-xml-spec v1.0).

The spec (docs/design/unified-xml-spec.md, frozen 2026-10-27) is the
design authority; this module is its executable form. Stage one: every
clean product becomes one XML file per document — a structured header
(read out of the ledger, never written back) plus a body that is either
the source structure mapped onto the spec's division vocabulary
(``native``) or the plain cleaned text verbatim (``flat``). The
``derived`` structure tier is a reserved vocabulary value only (stage
three; no production path).

Byte discipline (spec 4.1, same lineage as CleanedRecord): UTF-8 without
BOM, ``\\n`` only, exactly one trailing newline; attribute order fixed to
the spec's order of appearance; no pretty indentation — header elements
are separated by single newlines, body text nodes are embedded raw.
``to_xml`` is deterministic (same model, same bytes) and ``parse_xml``
round-trips it with model equality (spec 4.2, the readback gate).
Unknown elements and attributes are ignored on parse (spec 4.3 additive
evolution).

Vocabularies (spec 2.3/2.4/3.2) are frozen: evidence, date types and
division types live here exactly as the spec spells them.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from typing import Annotated, Any, Literal
from xml.sax.saxutils import escape as _xml_escape

from pydantic import AfterValidator, BaseModel, Field

__all__ = [
    "Authority",
    "Body",
    "DateFact",
    "Division",
    "Header",
    "Identifier",
    "Language",
    "Lineage",
    "TextBlock",
    "TypeLabel",
    "UnifiedDocument",
    "default_header",
    "parse_xml",
    "to_xml",
]

SCHEMA_VERSION = "1.0"

#: evidence vocabulary (spec 2.3) — shared by dates and authority.
#: ``text``/``title``/``computed`` are stage-two values (produced with
#: rule/quote attributes by the mining rules; defined now, unused in v1.0).
EVIDENCE_VOCAB = ("native", "absent", "text", "title", "computed")

#: date type vocabulary (spec 2.4). Everything else rides as
#: ``other:{native_key}`` — raw transcription, never a forced parse.
DATE_TYPE_VOCAB = (
    "published", "effective", "effective_until", "enacted", "registered",
)

#: division type vocabulary (spec 3.2). Off-vocabulary structures are
#: ``other`` — hard classification is a forbidden rewrite.
DIVISION_TYPE_VOCAB = (
    "part", "chapter", "section", "article", "paragraph", "point", "item",
    "annex", "preamble", "other",
)

_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

_YY_MM_DD = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _no_cr(value: str) -> str:
    """XML byte discipline at the model boundary: ``\\r`` in any text
    field is a loud construction error (same lineage as the CleanedRecord
    content contract — the file must carry ``\\n`` only)."""
    if "\r" in value:
        raise ValueError("text fields must not contain CR (XML byte discipline: \\n only)")
    return value


#: Every free-text field of every model carries this guard.
Text = Annotated[str, AfterValidator(_no_cr)]


class Identifier(BaseModel):
    """One native document number (spec 2.2): ``scheme`` is the country's
    short name for its numbering system (``Dz.U.``, ``NOR``…), ``native``
    is the raw string as published."""

    scheme: Text
    native: Text


class TypeLabel(BaseModel):
    """Two-level type (spec 2.2): ``native`` = the source's own type
    string, ``controlled`` = the country pack's controlled vocabulary
    value. Both optional; both never guessed."""

    native: Text | None = None
    controlled: Text | None = None


class Authority(BaseModel):
    """Issuing authority in the original language; ``evidence`` per spec
    2.3 (v1.0 produces ``native`` only)."""

    native: Text
    evidence: Literal["native", "absent", "text", "title", "computed"] = "native"


class Language(BaseModel):
    """One ISO 639 language code; the primary language also rides on the
    document root as ``xml:lang``."""

    code: Text


class DateFact(BaseModel):
    """One dated fact (spec 2.2/2.4). Standard types must be
    ``YYYY-MM-DD`` (the never-fabricate rule: source dates that do not
    fit ride as ``other:{native_key}`` with the raw string); ``absent``
    evidence means the element exists with no value (explicitly empty).

    value None ⇔ evidence "absent"; a value requires non-absent
    evidence."""

    type: Text
    evidence: Literal["native", "absent", "text", "title", "computed"]
    value: Text | None = None

    def model_post_init(self, context: Any, /) -> None:
        if self.evidence == "absent" and self.value is not None:
            raise ValueError("evidence='absent' must carry no value")
        if self.evidence != "absent" and (self.value is None or not self.value):
            raise ValueError("non-absent evidence requires a (non-empty) value")
        if (
            self.value is not None
            and self.type in DATE_TYPE_VOCAB
            and not _YY_MM_DD.match(self.value)
        ):
            raise ValueError(
                f"date type {self.type!r} requires YYYY-MM-DD "
                f"(got {self.value!r}); raw non-conforming dates ride as other:*"
            )


class Lineage(BaseModel):
    """Provenance, always engine-filled (spec 2.2): source URL, producing
    task, raw file path (country-root-relative), this clean's version and
    task id."""

    source_url: Text = ""
    produced_by: Text = ""
    raw_path: Text = ""
    clean_version: Text = ""
    clean_task: Text = ""


class Header(BaseModel):
    """The structured header (spec 2.2). ``title`` required; ``published``
    and ``effective`` date elements are mandatory (explicit ``absent``
    when unknown) — enforced loudly so a country's map_meta cannot ship
    an under-specified header."""

    title: Text
    identifiers: list[Identifier] = Field(default_factory=list)
    type: TypeLabel | None = None
    authority: Authority | None = None
    languages: list[Language] = Field(default_factory=list)
    dates: list[DateFact] = Field(default_factory=list)
    lineage: Lineage | None = None

    def model_post_init(self, context: Any, /) -> None:
        present = {fact.type for fact in self.dates}
        for required in ("published", "effective"):
            if required not in present:
                raise ValueError(
                    f"header must carry a {required!r} date element "
                    "(explicit evidence='absent' when unknown)"
                )


class TextBlock(BaseModel):
    """One ``<p>`` text block (spec 3.2): text byte-exact, zero rewrite."""

    text: Text


class Division(BaseModel):
    """One structural node of a native body (spec 3.2). Only the element
    NAME is mapped (``type`` from the spec vocabulary, off-vocabulary →
    ``other``); ``native-tag`` keeps the source label verbatim and ``n``
    the source's own numbering, so the source tree is always
    reconstructible. Children keep source order: text blocks and nested
    divisions are never reordered, merged or split."""

    type: Literal[
        "part", "chapter", "section", "article", "paragraph", "point",
        "item", "annex", "preamble", "other",
    ]
    n: Text | None = None
    native_tag: Text | None = None
    ps: list[TextBlock] = Field(default_factory=list)
    divisions: list[Division] = Field(default_factory=list)


class Body(BaseModel):
    """The document body (spec 3.1). ``flat`` = the cleaned text verbatim
    in one text node (byte-equal to the txt-era product); ``native`` =
    the source structure mapped per spec 3.2; ``derived`` = reserved
    stage-three value with no production path in v1.0. Exactly one
    content carrier — text XOR divisions."""

    structure: Literal["flat", "native", "derived"]
    text: Text | None = None
    divisions: list[Division] = Field(default_factory=list)

    def model_post_init(self, context: Any, /) -> None:
        if self.structure == "flat":
            if self.text is None or self.divisions:
                raise ValueError("flat body carries exactly one text node")
        elif self.text is not None:
            raise ValueError(
                f"{self.structure!r} body carries divisions, not a text node"
            )


class UnifiedDocument(BaseModel):
    """The whole document: root attributes + header + body. ``country`` /
    ``source`` / ``doc_id`` are engine context; ``lang`` is the primary
    language (root ``xml:lang``) when the ledger knows one."""

    country: Text
    source: Text
    doc_id: Text
    lang: Text | None = None
    header: Header
    body: Body


def default_header(doc_row: Mapping[str, Any]) -> Header:
    """The framework's default header for the content compat path (brief
    1.2): fixed ledger columns only — title, published (or absent) +
    effective (absent), languages. Identifier/type/authority are country
    knowledge (map_meta); lineage is always engine-filled."""
    language = (doc_row.get("language") or "").strip()
    publication = (doc_row.get("publication_date") or "").strip()
    return Header(
        title=(doc_row.get("title") or ""),
        languages=[Language(code=language)] if language else [],
        dates=[
            DateFact(
                type="published",
                evidence="native" if publication else "absent",
                value=publication or None,
            ),
            DateFact(type="effective", evidence="absent"),
        ],
    )


# -- serialization (spec 4.1) ---------------------------------------------------------


def _attr(value: str) -> str:
    return _xml_escape(value, {'"': "&quot;"})


def _division_xml(div: Division, out: list[str]) -> None:
    attrs = f' type="{_attr(div.type)}"'
    if div.n is not None:
        attrs += f' n="{_attr(div.n)}"'
    if div.native_tag is not None:
        attrs += f' native-tag="{_attr(div.native_tag)}"'
    out.append(f"<division{attrs}>")
    for block in div.ps:
        out.append(f"<p>{_xml_escape(block.text)}</p>")
    for child in div.divisions:
        _division_xml(child, out)
    out.append("</division>")


def to_xml(doc: UnifiedDocument) -> bytes:
    """Deterministic serialization (spec 4.1): fixed attribute order (the
    spec's order of appearance), no indentation — one element per line in
    the header, body text nodes embedded raw — UTF-8 without BOM, ``\\n``
    only, exactly one trailing newline. Same model in, same bytes out."""
    root_attrs = (
        f' schema-version="{SCHEMA_VERSION}"'
        f' country="{_attr(doc.country)}"'
        f' source="{_attr(doc.source)}"'
        f' doc-id="{_attr(doc.doc_id)}"'
    )
    if doc.lang is not None:
        root_attrs += f' xml:lang="{_attr(doc.lang)}"'
    out: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f"<document{root_attrs}>",
        "<header>",
        f"<title>{_xml_escape(doc.header.title)}</title>",
    ]
    for ident in doc.header.identifiers:
        out.append(
            f'<identifier scheme="{_attr(ident.scheme)}" native="{_attr(ident.native)}"/>'
        )
    if doc.header.type is not None:
        label = doc.header.type
        attrs = ""
        if label.native is not None:
            attrs += f' native="{_attr(label.native)}"'
        if label.controlled is not None:
            attrs += f' controlled="{_attr(label.controlled)}"'
        out.append(f"<type{attrs}/>")
    if doc.header.authority is not None:
        auth = doc.header.authority
        out.append(
            f'<authority native="{_attr(auth.native)}" evidence="{auth.evidence}"/>'
        )
    for language in doc.header.languages:
        out.append(f'<language code="{_attr(language.code)}"/>')
    out.append("<dates>")
    for fact in doc.header.dates:
        attrs = f' type="{_attr(fact.type)}" evidence="{fact.evidence}"'
        if fact.value is not None:
            out.append(f"<date{attrs}>{_xml_escape(fact.value)}</date>")
        else:
            out.append(f"<date{attrs}/>")
    out.append("</dates>")
    if doc.header.lineage is not None:
        lin = doc.header.lineage
        out.append(
            "<lineage"
            f' source-url="{_attr(lin.source_url)}"'
            f' produced-by="{_attr(lin.produced_by)}"'
            f' raw-path="{_attr(lin.raw_path)}"'
            f' clean-version="{_attr(lin.clean_version)}"'
            f' clean-task="{_attr(lin.clean_task)}"/>'
        )
    out.append("</header>")
    if doc.body.structure == "flat":
        assert doc.body.text is not None  # XOR is enforced on the model
        out.append('<body structure="flat">')
        out.append(f"<text>{_xml_escape(doc.body.text)}</text>")
    else:
        out.append(f'<body structure="{doc.body.structure}">')
        for div in doc.body.divisions:
            _division_xml(div, out)
    out.append("</body>")
    out.append("</document>")
    return ("\n".join(out) + "\n").encode("utf-8")


# -- parse (spec 4.3: additive evolution — unknown elements/attrs ignored) ------------


def _parse_division(el: ET.Element) -> Division:
    n = el.get("n")
    native_tag = el.get("native-tag")
    ps: list[TextBlock] = []
    divisions: list[Division] = []
    for child in el:
        if child.tag == "p":
            ps.append(TextBlock(text=child.text or ""))
        elif child.tag == "division":
            divisions.append(_parse_division(child))
    raw_type = el.get("type", "other")
    if raw_type not in DIVISION_TYPE_VOCAB:
        raw_type = "other"  # foreign files: never a hard guess, degrade loud-equivalent
    return Division(
        type=raw_type,  # type: ignore[arg-type]  # membership-checked above
        n=n,
        native_tag=native_tag,
        ps=ps,
        divisions=divisions,
    )


def parse_xml(data: bytes) -> UnifiedDocument:
    """Parse one unified-XML product back into the model. Standard
    library ElementTree; unknown elements and attributes are ignored
    (spec 4.3 — additive evolution never breaks old readers). Text nodes
    compare with whitespace exactness (the readback gate relies on it)."""
    root = ET.fromstring(data)
    header_el = root.find("header")
    if header_el is None:
        raise ValueError("unified XML: missing <header>")
    body_el = root.find("body")
    if body_el is None:
        raise ValueError("unified XML: missing <body>")
    title_el = header_el.find("title")
    identifiers = [
        Identifier(scheme=el.get("scheme", ""), native=el.get("native", ""))
        for el in header_el.findall("identifier")
    ]
    type_el = header_el.find("type")
    authority_el = header_el.find("authority")
    languages = [
        Language(code=el.get("code", "")) for el in header_el.findall("language")
    ]
    dates: list[DateFact] = []
    dates_el = header_el.find("dates")
    if dates_el is not None:
        for el in dates_el.findall("date"):
            dates.append(
                DateFact(
                    type=el.get("type", ""),
                    evidence=el.get("evidence", "native"),  # type: ignore[arg-type]
                    value=el.text,
                )
            )
    lineage_el = header_el.find("lineage")
    lineage = (
        Lineage(
            source_url=lineage_el.get("source-url", ""),
            produced_by=lineage_el.get("produced-by", ""),
            raw_path=lineage_el.get("raw-path", ""),
            clean_version=lineage_el.get("clean-version", ""),
            clean_task=lineage_el.get("clean-task", ""),
        )
        if lineage_el is not None
        else None
    )
    structure = body_el.get("structure", "flat")
    text_el = body_el.find("text")
    body = (
        Body(structure="flat", text=(text_el.text if text_el is not None else None) or "")
        if structure == "flat"
        else Body(
            structure=structure,  # type: ignore[arg-type]
            divisions=[_parse_division(el) for el in body_el.findall("division")],
        )
    )
    return UnifiedDocument(
        country=root.get("country", ""),
        source=root.get("source", ""),
        doc_id=root.get("doc-id", ""),
        lang=root.get(_XML_LANG),
        header=Header(
            title=(title_el.text if title_el is not None else None) or "",
            identifiers=identifiers,
            type=(
                TypeLabel(native=type_el.get("native"), controlled=type_el.get("controlled"))
                if type_el is not None
                else None
            ),
            authority=(
                Authority(
                    native=authority_el.get("native", ""),
                    evidence=authority_el.get("evidence", "native"),  # type: ignore[arg-type]
                )
                if authority_el is not None
                else None
            ),
            languages=languages,
            dates=dates,
            lineage=lineage,
        ),
        body=body,
    )
