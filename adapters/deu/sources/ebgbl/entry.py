"""Task type ``ebgbl_entry``: one entry page — metadata plus download area.

The entry page (``/bgbl/{part}/{year}/{nr}/VO.html``) carries everything:
a citation heading (``BGBl. 2023 I Nr. 1 vom 04.01.2023``), a metadata
block of ``role="listitem"`` field pairs (Typ, dates, lead ministry,
subject areas, index numbers) and a download area whose PDF links are the
Verkündung's files — ``regelungstext.pdf`` plus optional ``anlage1.pdf``,
``anlage2.pdf``… (official naming, site's Datenabruf page). One task per
file is spawned so a failed download retries without re-parsing metadata.

Row shapes (2026-09-07 probed, see docs/countries/deu/ebgbl-zh.md)::

    <h1 …>{title}</h1>
    …BGBl. 2023 I Nr. 1 vom 04.01.2023</h2>
    <div role="listitem"><strong>Typ:</strong> <span>Verordnung</span></div> …
    <div class="c-downloads__text"> <h3> <a href="/bgbl/1/2023/1/regelungstext.pdf?__blob=publicationFile&amp;v=1" …>
"""

from __future__ import annotations

import html as html_mod
import re
from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.deu.sources.ebgbl import BASE_URL, USER_AGENT

__all__ = ["EbgblEntryHandler", "to_iso_date"]

_CITATION_RE = re.compile(
    r"BGBl\.\s*(\d{4})\s*(I{1,2})\s*Nr\.\s*(\w+)\s*vom\s+(\d{2}\.\d{2}\.\d{4})"
)
_FIELD_RE = re.compile(r'<div role="listitem">\s*<strong>([^<]+):</strong>\s*(.*?)</div>', re.DOTALL)
_FIELD_VALUE_RE = re.compile(r"<span[^>]*>(.*?)</span>", re.DOTALL)
_DOWNLOAD_RE = re.compile(r'<div class="c-downloads__text">\s*<h3>\s*<a href="([^"]+)"', re.DOTALL)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.DOTALL)

_PART_ROMAN = {"1": "I", "2": "II"}


def to_iso_date(german: str) -> str:
    """'04.01.2023' -> '2023-01-04'."""
    day, month, year = german.split(".")
    return f"{year}-{month}-{day}"


def _strip_tags(fragment: str) -> str:
    return html_mod.unescape(re.sub(r"<[^>]+>", " ", fragment)).strip()


def entry_folder(part: str, year: int | str, nr: str) -> str:
    """Raw-folder path below the country root, e.g. ``01_raw/bgbl/I/2023/Nr_001``.

    The digit part of the number is zero-padded to three places; a letter
    suffix stays verbatim (``101a`` -> ``Nr_101a``)."""
    match = re.match(r"(\d+)([a-zA-Z]?)$", str(nr))
    if match is None:
        raise ValueError(f"unexpected Verkündung number {nr!r}")
    return f"01_raw/bgbl/{_PART_ROMAN[part]}/{year}/Nr_{int(match.group(1)):03d}{match.group(2)}"


class EbgblEntryHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        params = task.params
        return RequestSpec(
            url=f"{BASE_URL}/bgbl/{params['part']}/{params['year']}/{params['nr']}/VO.html",
            headers={"User-Agent": USER_AGENT},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        if response.status_code != 200:
            raise ValueError(f"entry page returned HTTP {response.status_code}")
        page = response.content.decode("utf-8", errors="replace")

        params = dict(task.params)
        part, year, nr = str(params["part"]), str(params["year"]), str(params["nr"])

        citation = _CITATION_RE.search(_strip_tags_only(page))
        if citation is None:
            raise ValueError(f"no BGBl citation found on the entry page of {year}/{nr}")
        cite_year, cite_part, cite_nr, publish_date = citation.groups()
        if (cite_year, cite_part, cite_nr) != (year, _PART_ROMAN[part], nr):
            raise ValueError(
                f"entry page cites BGBl {cite_year} {cite_part} Nr. {cite_nr} but the "
                f"task targeted {year} {part} Nr. {nr}"
            )

        fields: dict[str, str] = {}
        for label, body in _FIELD_RE.findall(page):
            value = _FIELD_VALUE_RE.search(body)
            if value is not None:
                fields[_strip_tags(label)] = _strip_tags(value.group(1))
        if "Typ" not in fields or "Veröffentlichungsdatum" not in fields:
            raise ValueError(f"entry page of {year}/{nr} lacks the metadata block")

        titles = [
            _strip_tags(h)
            for h in _H1_RE.findall(page)
            if _strip_tags(h) and "Navigation und Service" not in _strip_tags(h)
        ]
        if not titles:
            raise ValueError(f"no title heading found on the entry page of {year}/{nr}")
        title = titles[0]

        pdf_files: list[tuple[str, str]] = []  # (file_kind, href)
        for href in _DOWNLOAD_RE.findall(page):
            href = html_mod.unescape(href)
            if "view=zipdownload" in href:
                continue
            name_match = re.search(r"/(regelungstext|anlage\d+)\.pdf(?:\?|$)", href)
            if name_match is None:
                continue
            pdf_files.append((name_match.group(1), href))
        if not pdf_files:
            raise ValueError(
                f"entry page of {year}/{nr} lists no regelungstext.pdf "
                "(every Verkündung must have at least the main document)"
            )

        base_meta: dict[str, Any] = {
            "part": part,
            "year": params["year"],
            "nr": nr,
            "citation": _strip_tags(citation.group(0)),
            "typ": fields.get("Typ", ""),
            "publication_date": to_iso_date(publish_date),
        }
        for meta_key, field_label in (
            ("ausfertigungsdatum", "Ausfertigungsdatum"),
            ("federfuehrung", "Federführung"),
            ("sachgebiete", "Sachgebiet"),
            ("fna", "FNA"),
            ("gesta", "GESTA"),
        ):
            if field_label in fields:
                base_meta[meta_key] = fields[field_label]

        seeds = []
        for file_kind, href in pdf_files:
            file_title = title if file_kind == "regelungstext" else f"{title} – Anlage {file_kind[6:]}"
            seeds.append(
                TaskSeed(
                    type="ebgbl_pdf",
                    params={**base_meta, "title": file_title, "file_kind": file_kind, "href": href},
                )
            )
        return TaskResult(next_tasks=seeds)


def _strip_tags_only(page: str) -> str:
    """Citation lives inside a heading; strip tags so one regex reads it."""
    return re.sub(r"<[^>]+>", " ", page)
