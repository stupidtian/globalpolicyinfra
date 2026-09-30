"""Cleaning utilities: deterministic text extraction from raw bytes.

HTML (2026-09-19): raw HTML bytes → plain text — navigation, scripts,
styles, hidden inputs and site hint lines go; paragraph/article line
structure stays. XML (2026-09-29, framework increment ruled alongside the
PDF task): :func:`xml_to_text` renders schema-marked XML (legislative
vocabularies such as the Danish Linea/Paragraf/Stk) with the block
vocabulary declared by the country — parsed with stdlib ElementTree,
because HTML parsers mis-parse XML (``<Meta>`` collides with the void
``<meta>`` element and its children escape the subtree). PDF
(2026-09-28): :func:`measure_pdf` extracts the layout features a
country's routing table branches on, and :func:`geometry_pdf_to_text` is
the local geometry channel (pdfminer.six) — horizontal line assembly,
vertical (Japanese tategaki) column assembly, cross-page header/footer
removal. The MinerU network channel lives in
:mod:`runtime.stages.pdf_mineru`.

Out of scope for all of these: tokenizing, chunking, dedup, language
ID, cross-country normalization, semantic extraction, OCR (2026-09-19
user ruling; scanned PDFs fail loudly in the routing layer).

Country packs MAY import this module: it is a pure text tool with zero
I/O and no engine dependency (no pack→engine coupling).
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from collections.abc import Iterator, Sequence

from bs4 import BeautifulSoup, Comment, Tag
from pdfminer.high_level import extract_pages
from pdfminer.layout import (
    LAParams,
    LTChar,
    LTFigure,
    LTImage,
    LTPage,
    LTTextContainer,
    LTTextLine,
)

__all__ = [
    "geometry_pdf_to_text",
    "html_to_text",
    "measure_pdf",
    "run_cleaning",
    "xml_to_text",
]

#: Tags that force a line boundary in the rendered text. Besides the usual
#: block-level set this includes ``br``/``hr`` and the table/list row tags
#: (``tr``/``td``/``th``/``li``) — clause tables are common in legislation
#: and each cell deserves its own line.
_BLOCK_TAGS = frozenset({
    "address", "article", "aside", "blockquote", "br", "caption", "dd",
    "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form",
    "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav",
    "ol", "p", "pre", "section", "table", "tbody", "td", "tfoot", "th",
    "thead", "tr", "ul",
})

#: Removed unconditionally — framework default, not configurable.
_UNCONDITIONAL_DROP = ("script", "style", 'input[type="hidden"]')

_WHITESPACE_RUN = re.compile(r"[ \t\r\n\f\v\u00a0]+")


def html_to_text(
    html: bytes,
    *,
    keep: str | None = None,
    drop: Sequence[str] = (),
    drop_strings: Sequence[str] = (),
) -> str:
    """Convert raw HTML bytes to deterministic plain text.

    ``html``: raw bytes; BeautifulSoup sniffs the charset (windows-1257
    legacy pages decode correctly; KOR/LVA are UTF-8 today).

    ``keep``: whitelist CSS selector for the body container(s) — decoration
    is dynamic, the whitelist is the stable thing. Zero matches raises
    :class:`ValueError` (shape mutation must fail loudly — the country pack
    turns this into a PermanentError); multiple matches are ALL kept and
    concatenated in document order (2026-09-19 user ruling).

    ``drop``: selectors of decorative subtrees to remove inside the kept
    container(s).

    ``drop_strings``: whole lines (compared after stripping) to delete from
    the finished text — site hint lines such as the Korean "※ 본 법령은…".

    Output contract (byte-for-byte reproducible): ``\\n`` line breaks only,
    no BOM, exactly one trailing newline; block-tag boundaries become line
    breaks; inline tags never split words; runs of whitespace (including
    ``&nbsp;``) collapse to one space; blank runs collapse to one blank
    line. Leading indentation is intentionally not preserved — visual
    indentation lives in CSS, which text extraction cannot see; HTML
    source whitespace is formatting noise.
    """
    soup = BeautifulSoup(html, "html.parser")

    for selector in _UNCONDITIONAL_DROP:
        for node in soup.select(selector):
            node.decompose()

    if keep is not None:
        kept = soup.select(keep)
        if not kept:
            raise ValueError(f"keep selector {keep!r} matched nothing")
        containers = list(kept)
    else:
        containers = [soup]

    for selector in drop:
        for container in containers:
            for node in container.select(selector):
                node.decompose()

    wanted = set(drop_strings)
    lines: list[str] = []
    for container in containers:
        for raw_line in _render(container):
            folded = _WHITESPACE_RUN.sub(" ", raw_line).strip()
            if folded and folded not in wanted:
                lines.append(folded)
        lines.append("")  # blank line between kept containers

    return _finish_lines(lines)


def _finish_lines(lines: list[str]) -> str:
    """Shared output contract (both extraction engines): collapse runs of
    blank lines to one, drop leading/trailing blanks, exactly one trailing
    newline. Input lines must already be folded and filtered."""
    out: list[str] = []
    for line in lines:
        if line == "" and (not out or out[-1] == ""):
            continue
        out.append(line)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n" if out else ""


def _local_tag(tag: str) -> str:
    """Namespace-stripped, lowercased element name — the matching key for
    country-declared XML vocabularies (HTML parsers lowercase everything,
    so declarations are normalized the same way here)."""
    return tag.rpartition("}")[-1].lower()


def xml_to_text(
    xml: bytes,
    *,
    block_tags: Sequence[str],
    drop_tags: Sequence[str] = (),
    drop_strings: Sequence[str] = (),
) -> str:
    """Render schema-marked XML bytes to deterministic plain text
    (framework increment 2026-09-29, ruled together with the PDF task:
    one engine, two functions — countries declare vocabularies, never
    converters).

    ``block_tags`` (required): the country's block-level vocabulary —
    element names whose boundaries force a line break (e.g. the Danish
    Paragraf/Stk/Linea/Rubrica/Td). Required by design: block semantics
    are country knowledge, the framework must not guess. Names are
    matched case-insensitively and namespace-stripped (``{uri}Linea``
    matches ``linea``); an empty vocabulary is a loud ValueError.

    ``drop_tags``: element names whose whole subtrees are removed (e.g.
    the Danish ``Meta`` metadata block; a removed subtree's tail text goes
    with it). ``drop_strings``: whole folded lines to delete from the
    finished text (site hint lines).

    Parsed with stdlib ElementTree — HTML parsers mis-parse XML (a
    ``<Meta>`` element collides with HTML's void ``<meta>`` and its
    children escape the subtree). Malformed XML raises immediately
    (loud); standard and numeric entities are decoded by the parser.
    Output contract identical to :func:`html_to_text`.
    """
    blocks = {t.lower() for t in block_tags}
    if not blocks:
        raise ValueError(
            "block_tags is required — the block vocabulary is country knowledge"
        )
    drops = {t.lower() for t in drop_tags}
    wanted = set(drop_strings)
    root = ET.fromstring(xml)  # malformed input dies loudly right here
    lines: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            folded = _WHITESPACE_RUN.sub(" ", "".join(buffer)).strip()
            buffer.clear()
            if folded and folded not in wanted:
                lines.append(folded)

    def walk(element: ET.Element) -> None:
        tag = _local_tag(element.tag)
        if tag in drops:
            return  # subtree removed; its tail text goes with it
        is_block = tag in blocks
        if is_block:
            flush()
        buffer.append(element.text or "")
        for child in element:
            walk(child)
        buffer.append(element.tail or "")
        if is_block:
            flush()

    walk(root)
    flush()
    return _finish_lines(lines)


def _render(node: Tag) -> list[str]:
    """Render one subtree to raw lines: block boundaries split lines,
    inline text concatenates without breaking words."""
    pieces: list[str] = []
    current: list[str] = []

    def flush() -> None:
        pieces.append("".join(current))
        current.clear()

    def walk(element: Tag) -> None:
        for child in element.children:
            if not isinstance(child, Tag):  # text node (NavigableString)
                if isinstance(child, Comment):
                    continue  # site markers like <!-- 제목 --> are not content
                current.append(str(child))
                continue
            if child.name in _BLOCK_TAGS:
                flush()
                walk(child)
                flush()
            else:
                walk(child)

    walk(node)
    flush()
    return pieces


# -- PDF: feature measurement + local geometry channel (2026-09-28) --------------

_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def _iter_elements(obj: object) -> Iterator[object]:
    """Depth-first walk of a pdfminer layout tree: top-level walkers miss
    text inside Form XObjects (BGBl 2020 stores its whole body as raw
    LTChars inside LTFigure — probe finding, 2026-09-29)."""
    yield obj
    if isinstance(obj, (LTPage, LTFigure, LTTextContainer, LTTextLine)):
        for child in obj:
            yield from _iter_elements(child)


def _page_chars(page: LTPage) -> list[LTChar]:
    return [
        el
        for el in _iter_elements(page)
        if isinstance(el, LTChar) and el.get_text().strip()
    ]


def _page_images(page: LTPage) -> list[LTImage]:
    return [el for el in _iter_elements(page) if isinstance(el, LTImage)]


def _assemble_lines(chars: list[LTChar]) -> list[tuple[float, float, float, str]]:
    """Horizontal line assembly from raw chars: y-band grouping (3pt), x
    order inside a band, word gaps re-inserted as spaces (BGBl positions
    words without space glyphs — probe finding). Returns
    ``(x0, x1, y0, text)`` per line, top-down."""
    bands: dict[int, list[LTChar]] = defaultdict(list)
    for c in chars:
        bands[round(c.y0 / 3.0)].append(c)
    lines: list[tuple[float, float, float, str]] = []
    for _, band in sorted(bands.items(), key=lambda kv: -kv[0]):
        band.sort(key=lambda c: c.x0)
        runs: list[list[LTChar]] = [[band[0]]]
        for c in band[1:]:
            if c.x0 - runs[-1][-1].x1 > 12:  # same band, separate segment
                runs.append([c])
            else:
                runs[-1].append(c)
        for run in runs:
            pieces: list[str] = []
            prev: LTChar | None = None
            for ch in run:
                if prev is not None and ch.x0 - prev.x1 > max(0.8, 0.18 * ch.height):
                    pieces.append(" ")
                pieces.append(ch.get_text())
                prev = ch
            lines.append((run[0].x0, run[-1].x1, run[0].y0, "".join(pieces)))
    return lines


def _vertical_share(chars: list[LTChar]) -> float:
    """Share of CJK chars living in stacked x-bands (>= 4 chars spanning
    >= 40pt at ~constant x) — the tategaki signature. Char-bbox aspect
    ratios fail here because vertical text arrives as isolated
    single-char lines (probe finding)."""
    cjk = [c for c in chars if _CJK.search(c.get_text())]
    if len(cjk) < 20:
        return 0.0
    bands: dict[int, list[float]] = defaultdict(list)
    for c in cjk:
        bands[round(c.x0)].append(c.y0)
    stacked = sum(
        len(ys) for ys in bands.values() if len(ys) >= 4 and max(ys) - min(ys) > 40
    )
    return stacked / len(cjk)


def _column_modes(entries: list[tuple[float, float]], max_modes: int | None = 2) -> list[float]:
    """Left edges of text columns: x0 histogram peaks (8pt bins, peaks
    > 60pt apart). Plain gap thresholds break on bridging lines (POL 1990s
    gazettes — probe finding). ``max_modes=2`` for the two-column ordering
    pass; measurement passes ``None`` to count any column count."""
    if not entries:
        return []
    bins: Counter[int] = Counter(round(x0 / 8) for x0, _ in entries)
    modes: list[float] = []
    for peak in (bk * 8 for bk, _ in bins.most_common()):
        if all(abs(peak - m) > 60 for m in modes):
            modes.append(peak)
        if max_modes is not None and len(modes) == max_modes:
            break
    if len(modes) >= 2 and modes[0] > modes[1]:
        modes = sorted(modes)
    return modes


def _norm_repeats(text: str) -> str:
    return re.sub(r"\d+", "#", _WHITESPACE_RUN.sub(" ", text)).strip()


def _vertical_page_text(page: LTPage) -> list[str]:
    """Assemble one tategaki page: chars group into x-band columns,
    columns read right-to-left, lines top-down, runs broken on y-gaps."""
    chars = _page_chars(page)
    xs = sorted({round(c.x0) for c in chars})
    bands: list[list[int]] = []
    for x in xs:
        if bands and x - bands[-1][-1] <= 2:
            bands[-1].append(x)
        else:
            bands.append([x])
    band_of = {x: i for i, b in enumerate(bands) for x in b}
    cols: dict[int, list[LTChar]] = defaultdict(list)
    for c in chars:
        cols[band_of[round(c.x0)]].append(c)
    out: list[str] = []
    for i in sorted(cols, reverse=True):
        col = sorted(cols[i], key=lambda c: -c.y0)
        run: list[str] = []
        prev: LTChar | None = None
        for c in col:
            if prev is not None and (
                prev.y0 - c.y1 > 1.5 * max(c.height, 6) or c.x0 - prev.x0 > 2
            ):
                out.append("".join(run))
                run = []
            run.append(c.get_text())
            prev = c
        if run:
            out.append("".join(run))
    return out


def _horizontal_pages_text(pages: list[LTPage]) -> list[list[str]]:
    """Assemble horizontal pages: shared header/footer removed (lines whose
    digit-normalized text repeats on >= max(3, 60% of pages)), columns
    ordered by x0 modes with full-width lines first. Returns the line list
    per input page (same order, same count)."""
    page_lines = [_assemble_lines(_page_chars(p)) for p in pages]
    n_pages = max(1, len(page_lines))
    counter: Counter[str] = Counter(
        _norm_repeats(t) for lines in page_lines for _, _, _, t in lines if t
    )

    def is_chrome(text: str) -> bool:
        return counter[_norm_repeats(text)] >= max(3, n_pages * 0.6)

    def _column_sort_key(
        modes: list[float], entry: tuple[float, float, float, str]
    ) -> tuple[float, ...]:
        """Reading order within one page: full-width lines first, then the
        nearest column's lines top-down (loop-free so ruff B023 can't
        bite; modes is passed, never captured)."""
        x0, x1, y0, _ = entry
        if len(modes) == 2 and (x1 - x0) > (modes[1] - modes[0]) * 1.4:
            return (0, -y0, x0)  # full-width line reads before columns
        near = (
            min(range(len(modes)), key=lambda i: abs(x0 - modes[i])) if modes else 0
        )
        return (near + 1, -y0, x0)

    result: list[list[str]] = []
    for lines in page_lines:
        kept = [(x0, x1, y0, t) for x0, x1, y0, t in lines if t and not is_chrome(t)]
        page_out: list[str] = []
        if kept:
            modes = _column_modes([(x0, x1) for x0, x1, _, _ in kept])
            key = lambda entry, _modes=modes: _column_sort_key(_modes, entry)
            for _, _, _, t in sorted(kept, key=key):
                page_out.append(t)
        result.append(page_out)
    return result


def measure_pdf(data: bytes) -> dict[str, float | int]:
    """Layout features of one PDF (bytes in, dict out; pure function).

    Keys: ``pages``, ``chars`` (deep — includes Form-XObject text),
    ``text_coverage`` (char bbox area / page area), ``columns`` (max x0
    mode count), ``vertical_share`` (tategaki signature, 0.0 when no CJK),
    ``image_coverage``, ``cjk_share``. This is the measurement half of the
    routing contract: country declarations branch on these keys.
    """
    pages = list(extract_pages(io.BytesIO(data), laparams=LAParams()))
    chars = 0
    cjk = 0
    vertical_chars = 0
    char_area = 0.0
    image_area = 0.0
    page_area = 0.0
    columns_max = 0
    for page in pages:
        pw, ph = page.width, page.height
        page_area += pw * ph
        pcs = _page_chars(page)
        for img in _page_images(page):
            image_area += min((img.x1 - img.x0) * (img.y1 - img.y0), pw * ph)
        for c in pcs:
            chars += len(c.get_text().strip())
            char_area += (c.x1 - c.x0) * (c.y1 - c.y0)
            if _CJK.search(c.get_text()):
                cjk += 1
        lines = _assemble_lines(pcs)
        columns_max = max(
            columns_max,
            len(_column_modes([(x0, x1) for x0, x1, _, _ in lines], max_modes=None)),
        )
        vs = _vertical_share(pcs)
        vertical_chars += round(vs * len([c for c in pcs if _CJK.search(c.get_text())]))
    return {
        "pages": len(pages),
        "chars": chars,
        "text_coverage": round(char_area / page_area, 4) if page_area else 0.0,
        "columns": columns_max,
        "vertical_share": round(vertical_chars / cjk, 3) if cjk else 0.0,
        "image_coverage": round(image_area / page_area, 3) if page_area else 0.0,
        "cjk_share": round(cjk / chars, 3) if chars else 0.0,
    }


def geometry_pdf_to_text(data: bytes) -> str:
    """Local geometry channel (pdfminer.six): PDF bytes → deterministic
    UTF-8 plain text. Per-page vertical/horizontal detection (Japanese
    gazettes mix tategaki and horizontal on facing pages); horizontal
    pages get cross-page header/footer removal and column ordering;
    output contract identical to :func:`html_to_text` (\\n only, no BOM,
    exactly one trailing newline, same bytes for same input).

    Structurally broken PDFs raise (pdfminer parse errors propagate) —
    the engine classifies unknown exceptions as needs_agent, which is the
    loud outcome a corrupt file deserves.
    """
    pages = list(extract_pages(io.BytesIO(data), laparams=LAParams()))
    vertical_flags = [_vertical_share(_page_chars(p)) >= 0.5 for p in pages]
    horizontal_pages = [p for p, v in zip(pages, vertical_flags) if not v]
    horizontal_per_page = iter(_horizontal_pages_text(horizontal_pages))
    lines: list[str] = []
    for page, is_vertical in zip(pages, vertical_flags):
        if is_vertical:
            lines.extend(_vertical_page_text(page))
        else:
            lines.extend(next(horizontal_per_page))
        lines.append("")  # page boundary
    out: list[str] = []
    for line in lines:
        folded = _WHITESPACE_RUN.sub(" ", line).strip()
        if folded:
            out.append(folded)
    return "\n".join(out) + "\n" if out else ""


def run_cleaning() -> None:
    """Not implemented — and never will be a standalone function: cleaning
    rides the task engine (``cli.py clean``; a cleaning step is just a
    task, ARCHITECTURE.md section 6). Kept raising NotImplementedError for
    interface stability with the original skeleton tests."""
    raise NotImplementedError(
        "Cleaning runs as engine tasks (python cli.py clean); there is no "
        "standalone cleaning loop."
    )
