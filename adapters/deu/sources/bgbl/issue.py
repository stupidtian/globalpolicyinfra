"""Task type ``bgbl_issue``: one issue's Inhaltsverzeichnis, all entries.

A single text.xav deep link on the *issue* node returns the whole table of
contents — order number, the act's own date, title, start page, PDF file
name and entry node id per row (P0: one request replaces per-entry tree
walking). Non-policy rows are filtered by title, exactly the three the old
spider excluded: ``Komplette Ausgabe`` (whole-issue PDF),
``Inhaltsverzeichnis`` (the TOC page itself), ``Hinweis: …`` (pointers to
the Bundesanzeiger / EU Official Journal, not legal text).

Row shape (2026-08-27 probe, identical 1994-2022)::

    <tr><td class="odd" valign="top">3</td><td class="odd">
      [<div>08.12.2019</div>]
      <div href="bgbl120s0002.pdf"><span ...><a href="text.xav?...node_id%3D%271226094%27...#bgbl120s0002.pdf">Title</a></span></div>
      <div class="line2">aus Nr. 1 vom 07.01.2020, Seite 2</div>
    </td></tr>
"""

from __future__ import annotations

import html as html_mod
import re
from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.deu.sources.bgbl import BASE_URL, USER_AGENT

__all__ = ["BgblIssueHandler", "issue_folder", "to_iso_date"]

_HEADER_RE = re.compile(
    r'class="inh_title">Nr\.\s*(\d+)\s+vom\s+(\d{2}\.\d{2}\.\d{4}),\s+Seite\s+(\d+)\s+–\s+(\d+)'
)
_ROW_RE = re.compile(r"<tr><td[^>]*>(\d+)</td><td[^>]*>(.*?)</td></tr>", re.DOTALL)
_ENTRY_RE = re.compile(
    r'<div href="([^"]+?\.pdf)"><span[^>]*><a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL
)
_ENTRY_DATE_RE = re.compile(r"^\s*<div>(\d{2}\.\d{2}\.\d{4})</div>")
_PAGE_RE = re.compile(r"Seite\s+(\d+)</div>")
_DID_RE = re.compile(r"node_id%3D%27(\d+)%27")

_EXCLUDED_TITLES = {"Komplette Ausgabe", "Inhaltsverzeichnis"}


def to_iso_date(german: str) -> str:
    """'07.01.2020' -> '2020-01-07'."""
    day, month, year = german.split(".")
    return f"{year}-{month}-{day}"


def issue_folder(part: str, year: int | str, issue_nr: int | str) -> str:
    """Raw-folder path below the country root, e.g. ``01_raw/bgbl/I/2020/Nr_01``."""
    return f"01_raw/bgbl/{part}/{year}/Nr_{int(issue_nr):02d}"


class BgblIssueHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        did = str(task.params["did"])
        return RequestSpec(
            url=f"{BASE_URL}/text.xav",
            params={
                "SID": "",
                "tocf": "",
                "tf": "",
                "qmf": "",
                "hlf": "",
                "start": f"//*[@node_id='{did}']",
                "tocide": "0",
                "tocid": "",
                "bk": "",
            },
            headers={"User-Agent": USER_AGENT},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        payload = response.json()
        inner = payload.get("innerhtml")
        if not isinstance(inner, str) or "inh_title" not in inner:
            raise ValueError("issue response carries no Inhaltsverzeichnis table")

        params = dict(task.params)
        header = _HEADER_RE.search(inner)
        if header is None:
            raise ValueError(f"issue table header not found for did={params['did']}")
        header_nr = int(header.group(1))
        if header_nr != int(params["issue_nr"]):
            raise ValueError(
                f"issue table says Nr. {header_nr} but the task targeted "
                f"Nr. {params['issue_nr']} (did={params['did']})"
            )
        issue_date = to_iso_date(header.group(2))
        page_range = f"{header.group(3)}-{header.group(4)}"

        seeds: list[TaskSeed] = []
        skipped = 0
        for order_str, cell in _ROW_RE.findall(inner):
            entry = _ENTRY_RE.search(cell)
            if entry is None:
                continue
            pdf_name, a_href, raw_title = entry.group(1), entry.group(2), entry.group(3)
            title = html_mod.unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()
            if title in _EXCLUDED_TITLES or title.startswith("Hinweis"):
                skipped += 1
                continue

            page = _PAGE_RE.search(cell)
            did_match = _DID_RE.search(a_href)
            if page is None or did_match is None:
                raise ValueError(f"row {order_str} ({title!r}) lacks page or entry did")

            entry_date_match = _ENTRY_DATE_RE.match(cell)
            medianame = (
                f"bgbl/Bundesgesetzblatt Teil {params['part']}/"
                f"{params['year']}/{params['issue_label']}/{pdf_name}"
            )
            pdf_params: dict[str, Any] = {
                "nonce": params["nonce"],
                "csrf": params["csrf"],
                "part": params["part"],
                "year": params["year"],
                "issue_nr": int(params["issue_nr"]),
                "issue_label": params["issue_label"],
                "issue_date": issue_date,
                "page_range": page_range,
                "entry_order": int(order_str),
                "page_start": int(page.group(1)),
                "pdf_name": pdf_name,
                "medianame": medianame,
                "title": title,
                "did": did_match.group(1),
            }
            if entry_date_match is not None:
                pdf_params["entry_date"] = to_iso_date(entry_date_match.group(1))
            seeds.append(TaskSeed(type="bgbl_pdf", params=pdf_params))

        if not seeds:
            return TaskResult(
                expected_empty=f"issue {params['issue_label']} holds no real gazette entries "
                f"({skipped} non-policy rows filtered)"
            )
        return TaskResult(next_tasks=seeds)
