"""Cleaning utilities: raw HTML bytes → deterministic UTF-8 plain text.

Scope (user ruling 2026-09-19): format conversion + decoration stripping
only — navigation, scripts, styles, hidden inputs and site hint lines go;
paragraph/article line structure stays. Out of scope: tokenizing,
chunking, dedup, language ID, cross-country normalization, semantic
extraction, OCR.

Country packs MAY import this module: it is a pure text tool with zero
I/O and no engine dependency (no pack→engine coupling).

``pdf_to_text`` is deliberately absent: adding digital-PDF support later
means adding a pypdf dependency and this one function — the contract
needs no change. Scanned-document OCR is out (2026-09-19 user ruling).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from bs4 import BeautifulSoup, Comment, Tag

__all__ = ["html_to_text", "run_cleaning"]

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

    # Collapse runs of blank lines to one; drop leading/trailing blanks.
    out: list[str] = []
    for line in lines:
        if line == "" and (not out or out[-1] == ""):
            continue
        out.append(line)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n" if out else ""


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


def run_cleaning() -> None:
    """Not implemented — and never will be a standalone function: cleaning
    rides the task engine (``cli.py clean``; a cleaning step is just a
    task, ARCHITECTURE.md section 6). Kept raising NotImplementedError for
    interface stability with the original skeleton tests."""
    raise NotImplementedError(
        "Cleaning runs as engine tasks (python cli.py clean); there is no "
        "standalone cleaning loop."
    )
