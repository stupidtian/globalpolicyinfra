"""Task type ``lovtidende_clean``: one gazette entry -> unified XML (v2).

**v2 (unified-xml pilot 2026-10-28)** — the native-path exit: the corpus
files are named ``doc.xml`` but carry Lovdata's rendered HTML, so the
bytes are content-sniffed (100% html, corpus census 2026-10-05) and the
body is built as a :class:`core.unified.Body` with
``structure="native"`` per unified-xml-spec §3.2 — the DOM under
``main.documentBody`` walked once, block nodes mapped through
``STRUCTURE_RULES`` (name mapping only), inline nodes flattened into the
text stream in document order. The v1 decoration contract is unchanged:
everything outside the whitelist container (the metadata definition
list, the table of contents) never enters the walk, and the v1 guards
stay — non-HTML bytes, a missing container, an empty body and a wrong
``kind`` are all loud PermanentErrors.

STRUCTURE_RULES and the consumption conventions (unified-pilot-plan §2,
user ruling 2026-10-28 — semantic block mapping):

- ``section.section`` → chapter, ``n`` = its heading numeral (the ``h2``
  child consumed into ``n``, convention ①);
- ``article.legalArticle`` / ``article.futureLegalArticle`` → article,
  ``n`` = the header's ``legalArticleValue`` span and the first ``p`` =
  its ``legalArticleTitle`` span (header consumed, convention ②);
- ``article.legalP`` / ``numberedLegalP`` / ``marginIdArticle`` /
  ``defaultP`` / ``centeredP`` and ``p.leddfortsettelse`` → paragraph
  (the ledd rank; ``numberedLegalP`` keeps its number in the text — the
  source renders it inline as ``(1) …``);
- ``article.listArticle`` → item (``n`` = the ``data-name`` attribute);
  ``ul`` / ``li`` wrappers are transparent (convention ③);
- ``article.footnote`` → other with ``n`` = its ``footnoteLabel`` span
  (``footer.footnotes`` transparent);
- ``table``/``tr``/``td``/``th`` and every off-table node (change,
  futuretitle at block position, gazettenote, h1, …) → other — the
  vocabulary has no table rank and hard classification is forbidden;
  an unknown block node is ``other`` with its tag/class verbatim in
  ``native_tag``, never dropped or guessed;
- inline tags (span/sup/sub/i/strong/…) flatten into the surrounding
  text run in document order (convention ④); ``br`` ends the current
  run (a ``p`` boundary, no character lost); ``img`` has no text and is
  skipped (2,429 corpus-wide, census 2026-10-05).

Text semantics (plan §2.3, anchored by the golden fixtures): one run =
direct text plus inline children concatenated in document order, runs
of whitespace collapsed to one space, stripped at the ends — the same
inline rule the v1 ``html_to_text`` established (HTML source
indentation is formatting noise, not document text).

``map_meta`` (spec §5.3): ledger row -> unified header. Three parallel
identifier schemes (NOR = the official datokode, journal = the gazette
journal number, dokid = Lovdata's internal id), two-level type, the
ministry as native authority, and the full date mapping (user ruling
2026-10-28): published (= the ledger publication_date) + effective
(native ``in_force_date`` or explicitly absent) + enacted
(``adoption_date``) + ``other:dateInForce`` for the free-text force
lines ("Kongen bestemmer" — the never-fabricate rule) +
``other:kunngjort`` when the gazette timestamp carries a time part.
Lineage is always engine-filled.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Literal

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from adapters.base import (
    CleanedRecord,
    RequestSpec,
    Response,
    TaskResult,
    TaskView,
)
from core.unified import (
    Authority,
    Body,
    DateFact,
    Division,
    Header,
    Identifier,
    Language,
    TextBlock,
    TypeLabel,
)
from runtime.errors import PermanentError
from runtime.stages.cleaning import detect_format

__all__ = [
    "CLEAN_VERSION",
    "KEEP_SELECTOR",
    "STRUCTURE_RULES",
    "LovtidendeCleanHandler",
    "map_meta",
]

CLEAN_VERSION = 2

#: The gazette body container — single whitelist, every era and both
#: document families (probed v1, corpus census 2026-10-05).
KEEP_SELECTOR = "main.documentBody"

#: (tag, class) -> division type (plan §2.1; class "" = classless tag).
#: Lookup falls back to "other" with the tag/class verbatim in
#: native_tag — off-table nodes are never dropped or hard-classified.
#: The spec's division-type vocabulary (mirrors core.unified.Division's
#: frozen Literal) so the rule table's values type-check into the model.
_DivisionType = Literal[
    "part", "chapter", "section", "article", "paragraph", "point",
    "item", "annex", "preamble", "other",
]

STRUCTURE_RULES: dict[tuple[str, str], _DivisionType] = {
    ("section", "section"): "chapter",
    ("article", "legalArticle"): "article",
    ("article", "futureLegalArticle"): "article",
    ("article", "legalP"): "paragraph",
    ("article", "numberedLegalP"): "paragraph",
    ("article", "marginIdArticle"): "paragraph",
    ("article", "footnoteLegalP"): "paragraph",
    ("p", "leddfortsettelse"): "paragraph",
    ("article", "defaultP"): "paragraph",
    ("article", "centeredP"): "paragraph",
    ("article", "listArticle"): "item",
    ("article", "change"): "other",
    ("article", "document-change"): "other",
    ("article", "changesToParent"): "other",
    ("article", "gazettenote"): "other",
    ("article", "footnote"): "other",
    ("article", "miscHeadline"): "other",
    ("table", ""): "other",
    ("tr", ""): "other",
    ("td", ""): "other",
    ("th", ""): "other",
    ("h1", ""): "other",
    ("h2", ""): "other",
    ("h3", ""): "other",
    ("h4", ""): "other",
    ("h5", ""): "other",
    ("h6", ""): "other",
    ("blockquote", ""): "other",
}

#: Inline tags flatten into the surrounding text run (convention ④).
_INLINE_TAGS = frozenset({
    "span", "sup", "sub", "i", "strong", "b", "em", "a", "u", "small",
    "tt", "code", "abbr", "cite", "q", "mark", "s", "big",
})

#: Spans that carry standalone content and sit at a block position get
#: their own ``other`` division (futuretitle / miscHeadline); inside
#: running text they still flatten.
_BLOCK_SPANS = frozenset({"futuretitle", "miscHeadline"})

#: Mechanical wrappers whose children sink into the parent (convention ③).
_TRANSPARENT_TAGS = frozenset({"ul", "li", "tbody", "thead", "tfoot"})
_TRANSPARENT_CLASSES = frozenset({"footnotes"})  # footer.footnotes

#: Article-header wrappers consumed into n + first p (convention ②).
_HEADER_CLASSES = frozenset({"legalArticleHeader", "futureLegalArticleHeader"})

#: Unconditional framework-parity drops (v1 contract; none occur inside
#: the container in this corpus, the guard stays for parity).
_UNCONDITIONAL_DROP = ("script", "style", 'input[type="hidden"]')


def _class_of(el: Tag) -> str:
    classes: list[str] | str | None = el.get("class")
    if isinstance(classes, list):
        return classes[0] if classes else ""
    return classes or ""


def _native_tag(el: Tag) -> str:
    """The source's own label: its class when it carries one, else the
    tag name — Lovdata's classes are the structural vocabulary."""
    classes = _class_of(el)
    return classes or el.name


def _norm(text: str) -> str:
    """Whitespace runs collapse to one space, ends stripped (plan §2.3 —
    HTML source indentation is formatting noise, not document text)."""
    return " ".join(text.split())


def _is_transparent(el: Tag) -> bool:
    if el.name in _TRANSPARENT_TAGS:
        return True
    return el.name == "footer" and _class_of(el) in _TRANSPARENT_CLASSES


def _consume_article_header(header: Tag) -> tuple[str | None, str | None]:
    """Convention ②: the legalArticleHeader / futureLegalArticleHeader
    wrapper dissolves — its value span becomes ``n``, its title span the
    division's first ``p``. Returns (n, title)."""
    value = next(
        (s for s in header.find_all("span") if _class_of(s) == "legalArticleValue"),
        None,
    )
    title = header.find("span", class_="legalArticleTitle")
    n = _norm(value.get_text()) if value is not None else _norm(header.get_text()) or None
    title_text = _norm(title.get_text()) if title is not None else ""
    return n, title_text or None


def _collect(
    children: Iterable[Any],
    ps: list[TextBlock],
    divisions: list[Division],
) -> None:
    """Walk one container's children: text runs accumulate into ``ps``
    (``br`` ends a run), block children become divisions in order,
    transparent wrappers sink their children into this same walk."""
    run: list[str] = []

    def flush() -> None:
        if run:
            text = _norm("".join(run))
            if text:
                ps.append(TextBlock(text=text))
            run.clear()

    for child in children:
        if isinstance(child, NavigableString):
            run.append(str(child))
            continue
        if not isinstance(child, Tag):
            continue
        name = child.name
        if name == "br":
            flush()
        elif name == "img":
            continue  # no text content (census 2,429; plan §2.2 ④)
        elif name in _INLINE_TAGS and not (name == "span" and _class_of(child) in _BLOCK_SPANS):
            run.append(child.get_text())
        elif _is_transparent(child):
            before = len(divisions)
            _collect(child.children, ps, divisions)
            if child.name == "li":
                # The list numbering (data-name) rides on the consumed
                # li wrapper — lift it onto the item divisions it spawned.
                raw = child.get("data-name")
                if raw:
                    for div in divisions[before:]:
                        if div.type == "item" and div.n is None:
                            div.n = str(raw)
        else:
            flush()
            divisions.append(_to_division(child))
    flush()


def _to_division(el: Tag) -> Division:
    name, cls = el.name, _class_of(el)
    div_type: _DivisionType = STRUCTURE_RULES.get((name, cls), "other")
    ps: list[TextBlock] = []
    divisions: list[Division] = []
    n: str | None = None
    consumed: set[int] = set()

    if div_type == "chapter":
        # Convention ①: the heading numeral (a classless h2 child) is
        # the chapter's source-given number; the wrapper dissolves.
        numeral = next(
            (
                child
                for child in el.children
                if isinstance(child, Tag) and child.name == "h2" and not _class_of(child)
            ),
            None,
        )
        if numeral is not None:
            consumed.add(id(numeral))
            n = _norm(numeral.get_text()) or None

    if div_type == "article":
        header = next(
            (
                child
                for child in el.children
                if isinstance(child, Tag) and _class_of(child) in _HEADER_CLASSES
            ),
            None,
        )
        if header is not None:
            consumed.add(id(header))
            n, title = _consume_article_header(header)
            if title:
                ps.append(TextBlock(text=title))
    elif div_type == "other" and (name, cls) == ("article", "footnote"):
        label = next(
            (
                child
                for child in el.children
                if isinstance(child, Tag) and _class_of(child) == "footnoteLabel"
            ),
            None,
        )
        if label is not None:
            consumed.add(id(label))
            n = _norm(label.get_text()) or None
    elif (name, cls) == ("article", "listArticle"):
        raw = el.get("data-name")
        if raw:
            n = str(raw)

    _collect(
        (child for child in el.children if id(child) not in consumed),
        ps,
        divisions,
    )
    return Division(
        type=div_type,
        n=n,
        native_tag=_native_tag(el),
        ps=ps,
        divisions=divisions,
    )


def _body_from_html(content: bytes) -> Body:
    # from_encoding pinned to UTF-8: the whole corpus is strict UTF-8
    # (collection census), but two files carry no charset declaration and
    # bs4's fallback guess mojibakes them (EØS -> EĂS, probed in the
    # pilot run — v1 txt carries the same latent defect on those two).
    soup = BeautifulSoup(content, "html.parser", from_encoding="utf-8")
    for selector in _UNCONDITIONAL_DROP:
        for node in soup.select(selector):
            node.decompose()
    main = soup.select_one(KEEP_SELECTOR)
    if main is None:
        raise ValueError(f"zero matches for container {KEEP_SELECTOR!r}")
    ps: list[TextBlock] = []
    divisions: list[Division] = []
    _collect(main.children, ps, divisions)
    if not any(block.text for div in divisions for block in div.ps) and not any(
        block.text for block in ps
    ):
        raise ValueError(f"{KEEP_SELECTOR} carries no text at all")
    return Body(structure="native", divisions=divisions)


def map_meta(doc_row: Mapping[str, Any], domain_row: Mapping[str, Any] | None) -> Header:
    """Ledger row -> unified header (plan §3, user ruling 2026-10-28:
    the full date mapping — no native date is left behind)."""
    meta = doc_row.get("meta") or {}

    identifiers = [
        Identifier(scheme=scheme, native=str(meta[key]))
        for scheme, key in (
            ("NOR", "legacyID"),
            ("journal", "journalNumber"),
            ("dokid", "dokid"),
        )
        if meta.get(key)
    ]
    native_type = (meta.get("nativeType") or "").strip() or None
    controlled = (doc_row.get("doc_type") or "").strip() or None
    type_label = (
        TypeLabel(native=native_type, controlled=controlled)
        if native_type or controlled
        else None
    )
    authority_raw = (doc_row.get("issuing_authority") or "").strip()
    language = (doc_row.get("language") or "").strip()

    publication = (doc_row.get("publication_date") or "").strip()
    in_force = (meta.get("in_force_date") or "").strip()
    adoption = (meta.get("adoption_date") or "").strip()
    in_force_raw = (meta.get("dateInForce") or "").strip()
    kunngjort_raw = (meta.get("kunngjort") or "").strip()

    dates = [
        DateFact(
            type="published",
            evidence="native" if publication else "absent",
            value=publication or None,
        ),
        DateFact(
            type="effective",
            evidence="native" if in_force else "absent",
            value=in_force or None,
        ),
    ]
    if adoption:
        dates.append(DateFact(type="enacted", evidence="native", value=adoption))
    if not in_force and in_force_raw:
        # The never-fabricate rule: free-text force lines ("Kongen
        # bestemmer") ride verbatim on an other:* date row.
        dates.append(
            DateFact(type="other:dateInForce", evidence="native", value=in_force_raw)
        )
    if len(kunngjort_raw) > 10:
        # A timestamp with a time part carries more than the published
        # date already in the header — keep it verbatim.
        dates.append(
            DateFact(type="other:kunngjort", evidence="native", value=kunngjort_raw)
        )

    return Header(
        title=(doc_row.get("title") or ""),
        identifiers=identifiers,
        type=type_label,
        authority=Authority(native=authority_raw, evidence="native")
        if authority_raw
        else None,
        languages=[Language(code=language)] if language else [],
        dates=dates,
    )


class LovtidendeCleanHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(local_doc=str(task.params["doc_id"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        doc_id = str(task.params["doc_id"])
        kind = str(task.params.get("kind", ""))
        if kind != "lt_pack":
            raise PermanentError(
                f"lovtidende_clean has no container rules for kind {kind!r}"
            )

        fmt = detect_format(response.content)
        if fmt != "html":
            raise PermanentError(
                f"{doc_id}: stored bytes sniff as {fmt!r}, not html — "
                "the corpus is 100% HTML (2026-10-05 census); any other "
                "format is a shape mutation to classify by hand"
            )

        try:
            body = _body_from_html(response.content)
        except ValueError as exc:
            raise PermanentError(f"{doc_id}: {exc}") from exc
        return TaskResult(
            cleaned=[
                CleanedRecord(doc_id=doc_id, version=CLEAN_VERSION, body=body)
            ]
        )
