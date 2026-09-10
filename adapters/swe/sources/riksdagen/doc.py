"""Task type ``sfs_doc``: one statute's HTML page — the document itself.

One request yields the whole document (byte-true shapes probed
2026-09-09, samples in the task folder's probe archive)::

    <h2>Förordning (2026:1776) om ärendehanteringssystem …</h2>
    <style>…</style>
    <b>SFS nr</b>:        2026:1776<br />
    <b>Departement/myndighet</b>: Landsbygds- och …departementet SPN<br />
    <b>Utfärdad</b>:      2026-09-03<br />
    [<b>Ändrad</b>:       t.o.m. SFS 2026:1636<br />]      — amended only
    <b>Ändringsregister</b>: <a href="…/sfsr?bet=…">SFSR …</a><br />
    <b>Källa</b>:         <a href="…/sfst?bet=…">Fulltext …</a><br />
    <hr />
    …anchored consolidated text; a fresh law opens with the in-force
    rubrik ``/Träder i kraft I:{date}/``…

Register notices (``N2026:3``) carry the same header block and **no
body at all** — the metadata is the document. The response carries no
charset declaration; the bytes are UTF-8 and are decoded explicitly.

Semantics guarded here (all probed 2026-09-09):

- the listing row rides in task params and is cross-checked against the
  page header (SFS number, promulgation date) — a mismatch is a shape
  change and escalates loudly;
- ``Ändrad: t.o.m. SFS {y:n}`` marks a consolidated text (amended
  through that statute); its absence means the bytes are the
  promulgation-day original (34.1% of the corpus, never amended);
- the in-force rubrik is parsed **only for never-amended statutes**: in
  a consolidated text the leading rubrik belongs to the *latest
  amendment* (Skollagen 2010:800 opens with ``/Träder i kraft
  I:2027-07-01/`` from a 2026 amendment — not the law's own 2010 date),
  so extracting it there would mislabel; amended statutes honestly
  carry no in-force field instead.

A 404 here is not declared as data: the id came from a listing fetched
moments ago, so not-found means something truly broke and must fail loud
(the number space also has genuine holes — registry-nonmember numbers —
which the listing never emits).
"""

from __future__ import annotations

import html as html_mod
import re
from datetime import date

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.swe.sources.riksdagen import (
    canonical_doc_url,
    html_path,
    map_doc_type,
    sfs_parts,
)
from core.document import DocumentRecord, compute_doc_id

__all__ = ["SfsDocHandler", "parse_header"]


def _clean(fragment: str) -> str:
    """Tag-free, entity-resolved, whitespace-collapsed field text."""
    text = html_mod.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"\s+", " ", text).strip()


def _header_field(page: str, label: str) -> str | None:
    """One header-block value by its ``<b>label</b>:`` lead-in, or None."""
    pattern = rf"<b>\s*{label}\s*</b>\s*:\s*(.*?)<br"
    match = re.search(pattern, page, re.DOTALL)
    if match is None:
        return None
    value = _clean(match.group(1))
    return value or None


def _header_href(page: str, label: str) -> str | None:
    """The link target of a header field (Ändringsregister / Källa)."""
    pattern = rf"<b>\s*{label}\s*</b>\s*:\s*(.*?)<br"
    match = re.search(pattern, page, re.DOTALL)
    if match is None:
        return None
    href = re.search(r'<a\s+href="([^"]+)"', match.group(1))
    return href.group(1).strip() if href else None


def parse_header(page: str) -> dict[str, str]:
    """The header block as native-label → cleaned-value pairs.

    Labels read generically (known ones consumed by the parser, the rest
    observable in tests) so a new optional row — e.g. a future Omtryck
    (reprint) line — neither breaks parsing nor is silently guessed at.
    """
    header: dict[str, str] = {}
    for label in (
        "SFS nr",
        "Departement/myndighet",
        "Utfärdad",
        "Ändrad",
        "Ändringsregister",
        "Källa",
    ):
        value = _header_field(page, label)
        if value is not None:
            header[label] = value
    return header


#: In-force rubrik; two real forms in the 2026 corpus (probed 2026-09-09):
#: "/Träder i kraft I:2027-01-01/" and — sfs-2026-1601 — without the
#: closing slash, the next tag following directly.
_IKRAFT_RE = re.compile(r"/Träder i kraft I:\s*(\d{4}-\d{2}-\d{2})\s*/?")


class SfsDocHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=canonical_doc_url(str(task.params["dok_id"])))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = dict(task.params)
        sfs_nr = str(params["sfs_nr"])
        dok_id = str(params["dok_id"])
        if response.status_code != 200:
            raise ValueError(f"document {dok_id} returned HTTP {response.status_code}")
        page = response.content.decode("utf-8", errors="replace")

        title_match = re.search(r"<h2>(.*?)</h2>", page, re.DOTALL)
        if title_match is None:
            raise ValueError(f"document {dok_id} carries no <h2> title")
        title = _clean(title_match.group(1))
        if not title:
            raise ValueError(f"document {dok_id} has an empty title")

        header = parse_header(page)

        page_nr = header.get("SFS nr")
        if page_nr is None:
            raise ValueError(f"document {dok_id} carries no 'SFS nr' header field")
        if page_nr != sfs_nr:
            raise ValueError(
                f"document {dok_id} numbers itself {page_nr!r}, listing said {sfs_nr!r}"
            )

        utfardad = header.get("Utfärdad")
        if utfardad is None:
            raise ValueError(f"document {dok_id} carries no 'Utfärdad' header field")
        try:
            date.fromisoformat(utfardad)
        except ValueError:
            raise ValueError(
                f"document {dok_id} has a non-ISO Utfärdad {utfardad!r}"
            ) from None
        if utfardad != str(params["datum"]):
            raise ValueError(
                f"document {dok_id} was promulgated {utfardad!r}, "
                f"listing said {params['datum']!r}"
            )

        year, serial = sfs_parts(sfs_nr)
        meta: dict[str, str] = {
            "sfs_nr": sfs_nr,
            "ar": year,
            "lopnummer": serial,
            "riksdagen_dok_id": dok_id,
            "files": "doc.html",
        }
        organ = str(params.get("organ", "")).strip()
        if organ:
            meta["organ"] = organ

        andrad = header.get("Ändrad")
        if andrad is not None:
            stamp = re.search(r"(\d{4}:\d+)", andrad)
            if stamp is None:
                raise ValueError(
                    f"document {dok_id} has an Ändrad line without an SFS "
                    f"number: {andrad!r}"
                )
            meta["andrad_tom"] = stamp.group(1)
            amended = True
        else:
            amended = False

        andringsregister = _header_href(page, "Ändringsregister")
        if andringsregister:
            meta["andringsregister_url"] = andringsregister
        kalla = _header_href(page, "Källa")
        if kalla:
            meta["kalla_url"] = kalla

        if not amended:
            # In-force rubrik only on never-amended statutes — see module
            # docstring: a consolidated text's leading rubrik belongs to its
            # latest amendment, not to the law itself.
            ikraft = _IKRAFT_RE.search(page)
            if ikraft is not None:
                meta["ikrafttradande"] = ikraft.group(1)

        if dok_id.startswith("sfs-N"):
            meta["notis"] = "1"

        source_url = canonical_doc_url(dok_id)
        document = DocumentRecord(
            title=title,
            source_url=source_url,
            publication_date=utfardad,
            issuing_authority=header.get("Departement/myndighet"),
            doc_type=map_doc_type(title),
            language="swe",
            raw_metadata=meta,
        )
        doc_id_computed = compute_doc_id("SWE", source_url, utfardad)

        return TaskResult(
            documents=[document],
            files=[
                FileOut(path=html_path(sfs_nr), content=response.content,
                        doc_id=doc_id_computed)
            ],
        )
