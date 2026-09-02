"""Commerce / NWS: the directives system (agency policy issuances).

weather.gov/directives/ is a numbered tree (verified 2026-08-31): the index
lists ~11 series (``/directives/010`` …); each series page carries its
directives as direct PDF links with the title in the anchor text, including
rescission notes ("… rescinded June 12, 2019") — the rescinded flag becomes
``status='withdrawn'``. One ``index_page`` task seeds one ``pdf_listing``
task per series.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from adapters.base import Response, TaskResult, TaskSeed, TaskView
from adapters.usa.sources.guidance.common import (
    AgencyProfile,
    department_of,
    guid_folder,
    register,
    response_text,
    strip_tags,
)

__all__ = ["NWS_INDEX_URL", "parse_nws_index", "parse_nws_series"]

NWS_INDEX_URL = "https://www.weather.gov/directives/"

_SERIES_RE = re.compile(r'href="(/directives/\d{3})"')
_CONTENT_RE = re.compile(r'<div class="cms-content">(.*?)</div>\s*</div>', re.DOTALL)
_NDS_RE = re.compile(r"NDS\s+(\d+-\d+)")
_PDF_LINK_RE = re.compile(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)


def parse_nws_index(response: Response, task: TaskView) -> TaskResult:
    html = response_text(response)
    params = dict(task.params)
    next_tasks: list[TaskSeed] = []
    for series in sorted(set(_SERIES_RE.findall(html))):
        chain = dict(params)
        chain["url"] = urljoin(NWS_INDEX_URL, series)
        next_tasks.append(TaskSeed(type="pdf_listing", params=chain))
    return TaskResult(next_tasks=next_tasks)


def parse_nws_series(response: Response, task: TaskView) -> TaskResult:
    html = response_text(response)
    base_url = str(task.params["url"])
    content = _CONTENT_RE.search(html)
    segment = content.group(1) if content else html
    rows: list[dict[str, Any]] = []
    next_tasks: list[TaskSeed] = []
    quota = task.params.get("quota_left")
    for match in _PDF_LINK_RE.finditer(segment):
        href, anchor = match.groups()
        title = strip_tags(anchor).strip()
        if not title:
            continue
        if quota is not None and len(rows) >= int(quota):
            break
        nds = _NDS_RE.search(title)
        stem = href.rsplit("/", 1)[-1]
        native_id = f"NDS {nds.group(1)}" if nds else stem.rsplit(".", 1)[0]
        status = "withdrawn" if "rescind" in title.lower() else None
        file_url = urljoin(base_url, href)
        folder = guid_folder("nws", re.sub(r"[^A-Za-z0-9._-]+", "_", native_id))
        rows.append(
            {
                "agency": "nws",
                "department": department_of("nws"),
                "native_id": native_id,
                "channel": "directives",
                "native_type": "NWS Directive",
                "doc_type": "DIRECTIVE",
                "title": title[:400],
                "issued_date": None,
                "status": status,
                "url": file_url,
                "file_url": file_url,
                "folder": folder,
                "text_extracted": None,
            }
        )
        next_tasks.append(
            TaskSeed(
                type="guid_file_dl",
                params={
                    "url": file_url,
                    "date": None,
                    "stem": "directive",
                    "folder": folder,
                    "meta_title": title,
                    "meta_authority": "National Weather Service",
                    "meta_doc_type": "DIRECTIVE",
                    "agency": "nws",
                    "native_type": "NWS Directive",
                    "entity_ref": f"guidance_documents:nws:{native_id}",
                },
            )
        )
    return TaskResult(
        upsert_rows={"guidance_documents": rows} if rows else {},
        next_tasks=next_tasks,
    )


NWS_PROFILE = AgencyProfile(
    agency="nws",
    matches=lambda url: False,
    parse_index=parse_nws_index,
    parse_listing=parse_nws_series,
)
register(NWS_PROFILE)
