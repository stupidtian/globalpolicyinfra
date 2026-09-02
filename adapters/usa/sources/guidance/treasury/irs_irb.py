"""Treasury / IRS: the Internal Revenue Bulletin (IRB) gazette chain.

``gz_index`` — GET irs.gov/irb lists the recent weekly issues
(server-rendered links); spawns one ``gz_issue`` per qualifying issue.

``gz_issue`` — one weekly issue. Its table of contents is two-level per
document (verified against the live page 2026-08-31): an outer entry
carries the title (``<a href="#idN">Title</a>``) and the nested entry right
after it carries the official identifier with a semantic anchor
(``<a href="#NOT-2026-48">Notice 2026-48</a>``). Each pair becomes a
guidance_documents row whose doc_type comes from the identifier (tagging
R1); per-document text is sliced from the identifier's body anchor. A
whole-issue PDF download follows, and documents have no standalone files —
they live inside the issue, so the issue folder holds the mirrors.
"""

from __future__ import annotations

import re
from typing import Any

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.usa.sources.guidance.common import (
    department_of,
    guid_folder,
    response_text,
    strip_tags,
)
from adapters.usa.sources.guidance.tagging import irb_doc_type

__all__ = ["IRB_INDEX_URL", "IrbIndexHandler", "IrbIssueHandler"]

IRB_INDEX_URL = "https://www.irs.gov/irb"

_ISSUE_RE = re.compile(r'href="https://www\.irs\.gov/irb/(\d{4}-\d{2})_irb"')
#: outer title entry + nested identifier entry, as the live TOC marks them up
_TOC_PAIR_RE = re.compile(
    r'<a href="#(id\d+)" class="text-overflow xmlbc-link">([^<]*)</a>'
    r'<ul[^>]*><li><a href="#([A-Z0-9-]+)" class="text-overflow xmlbc-link">'
    r"((?:Treasury Decision|T\.D\.|Revenue Ruling|Rev\. Rul\.|Revenue Procedure|"
    r"Rev\. Proc\.|Notice|Announcement)[^<]{0,40})</a></li></ul>"
)
_BODY_ANCHOR_RE = re.compile(r'<a (?:name|id)="([A-Z0-9-]+)"')


def _issue_url(issue: str) -> str:
    return f"https://www.irs.gov/irb/{issue}_irb"


def _issue_pdf_url(issue: str) -> str:
    yy, ww = issue.split("-")
    return f"https://www.irs.gov/pub/irs-irbs/irb{yy[2:]}-{ww}.pdf"


def _in_scope(issue: str, params: dict[str, Any]) -> bool:
    window = params.get("window")
    if window:
        from_str, _, to_str = str(window).partition(":")
        if not (from_str <= issue <= to_str):
            return False
    year = params.get("year")
    return not (year and not issue.startswith(str(year)))


class IrbIndexHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=IRB_INDEX_URL)

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = dict(task.params)
        issues = sorted(set(_ISSUE_RE.findall(response_text(response))))
        max_issues = params.get("max_docs")
        next_tasks: list[TaskSeed] = []
        for issue in issues:
            if not _in_scope(issue, params):
                continue
            if max_issues is not None and len(next_tasks) >= int(max_issues):
                break
            issue_params: dict[str, Any] = {"agency": "irs", "issue": issue}
            if params.get("window"):
                issue_params["window"] = params["window"]
            next_tasks.append(TaskSeed(type="gz_issue", params=issue_params))
        return TaskResult(next_tasks=next_tasks)


class IrbIssueHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=_issue_url(str(task.params["issue"])))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        html = response_text(response)
        issue = str(task.params["issue"])
        year = issue.split("-")[0]
        issue_folder = guid_folder("irs", issue, year)

        body_anchors = [(m.start(), m.group(1)) for m in _BODY_ANCHOR_RE.finditer(html)]
        rows: list[dict[str, Any]] = []
        fragments: list[FileOut] = []
        for match in _TOC_PAIR_RE.finditer(html):
            _outer_id, title, doc_anchor, raw_identifier = match.groups()
            native_id = re.sub(r"\s+", " ", raw_identifier).strip().rstrip(".")
            positions = [p for p, a in body_anchors if a == doc_anchor]
            segment = ""
            if positions:
                later = [p for p, _ in body_anchors if p > positions[-1]]
                segment = html[positions[-1] : later[0] if later else positions[-1] + 30000]
            rows.append(
                {
                    "agency": "irs",
                    "department": department_of("irs"),
                    "native_id": native_id,
                    "channel": "irb",
                    "native_type": native_id,
                    "doc_type": irb_doc_type(native_id),
                    "title": (title.strip() or native_id)[:400],
                    "issued_date": None,
                    "url": f"{_issue_url(issue)}#{doc_anchor}",
                    "folder": issue_folder,
                    "text_extracted": strip_tags(segment)[:20000] or None,
                }
            )
            if segment:
                # per-document fragment: the slicer already runs for
                # text_extracted, so persisting the slice costs nothing and
                # saves every downstream consumer from re-implementing it
                safe = re.sub(r"[^A-Za-z0-9._-]+", "_", native_id)
                fragments.append(
                    FileOut(
                        path=f"{issue_folder}/docs/{safe}.html",
                        content=segment.encode("utf-8"),
                    )
                )
        next_tasks = [
            TaskSeed(
                type="guid_file_dl",
                params={
                    "url": _issue_pdf_url(issue),
                    "date": None,
                    "stem": "irb-issue",
                    "folder": issue_folder,
                    "meta_title": f"Internal Revenue Bulletin {issue} (whole issue)",
                    "meta_authority": "Internal Revenue Service",
                    "meta_doc_type": "OTHER",
                    "agency": "irs",
                    "native_type": issue,
                },
            )
        ]
        return TaskResult(
            upsert_rows={"guidance_documents": rows} if rows else {},
            next_tasks=next_tasks,
            files=[
                FileOut(path=f"{issue_folder}/page.html", content=response.content),
                *fragments,
            ],
        )
