"""Commerce / BIS: export-control guidance PDFs on listing pages.

BIS (Bureau of Industry and Security) publishes its interpretive guidance
as PDFs linked from a handful of server-rendered listing pages (verified
2026-08-31: e.g. country-guidance carries "Guidance on Advanced Computing
Items" and its FAQ). One ``pdf_listing`` task per listing page: every PDF
link becomes a row plus a download task. The site also carries site-legal
oddities on the same pages (SORN, information-quality guidelines) — those
are skipped by filename.
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

__all__ = ["BIS_LISTING_PAGES", "parse_bis_listing"]

BIS_LISTING_PAGES: tuple[str, ...] = (
    "https://www.bis.doc.gov/index.php/licensing/country-guidance",
    "https://www.bis.doc.gov/index.php/licensing/guidance-on-end-user-and-end-use-controls-and-us-person-controls",
)

#: same-page files that are site administration, not policy guidance
_SKIP_FILES = ("sorn", "qualityguidelines")

_PDF_LINK_RE = re.compile(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)


def parse_bis_listing(response: Response, task: TaskView) -> TaskResult:
    html = response_text(response)
    base_url = str(task.params["url"])
    rows: list[dict[str, Any]] = []
    next_tasks: list[TaskSeed] = []
    quota = task.params.get("quota_left")
    for match in _PDF_LINK_RE.finditer(html):
        href, anchor = match.groups()
        filename = href.rsplit("/", 1)[-1]
        stem = filename.rsplit(".", 1)[0]
        if any(skip in filename.lower() for skip in _SKIP_FILES):
            continue
        if quota is not None and len(rows) >= int(quota):
            break
        title = strip_tags(anchor).strip()
        file_url = urljoin(base_url, href)
        native_id = stem
        rows.append(
            {
                "agency": "bis",
                "department": department_of("bis"),
                "native_id": native_id,
                "channel": "listing",
                "native_type": "BIS guidance PDF",
                "doc_type": "GUIDANCE",
                "title": (title or native_id)[:400],
                "issued_date": None,
                "url": base_url,
                "file_url": file_url,
                "folder": guid_folder("bis", native_id),
                "text_extracted": None,
            }
        )
        next_tasks.append(
            TaskSeed(
                type="guid_file_dl",
                params={
                    "url": file_url,
                    "date": None,
                    "stem": "doc",
                    "folder": guid_folder("bis", native_id),
                    "meta_title": title or native_id,
                    "meta_authority": "Bureau of Industry and Security",
                    "meta_doc_type": "GUIDANCE",
                    "agency": "bis",
                    "native_type": "BIS guidance PDF",
                    "entity_ref": f"guidance_documents:bis:{native_id}",
                },
            )
        )
    return TaskResult(
        upsert_rows={"guidance_documents": rows} if rows else {},
        next_tasks=next_tasks,
    )


BIS_PROFILE = AgencyProfile(
    agency="bis",
    matches=lambda url: False,  # no sitemap chain; listing pages are seeded
    parse_listing=parse_bis_listing,
)
register(BIS_PROFILE)
