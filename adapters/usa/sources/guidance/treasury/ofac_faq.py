"""Treasury / OFAC: the sanctions FAQ library via sitemap.

``sitemap_page`` on ofac.treasury.gov/sitemap.xml enumerates the whole FAQ
library (991 entries verified 2026-08-31); each ``guid_page`` parses the
server-rendered question/answer block from the content region and archives
the page. FAQ dates: pages carry none, so the sitemap's <lastmod> (passed
through task params by the sitemap handler) becomes revised_date.
"""

from __future__ import annotations

import re
from typing import Any

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.usa.sources.guidance.common import (
    AgencyProfile,
    department_of,
    guid_folder,
    register,
    response_text,
    strip_tags,
)

__all__ = ["OFAC_PROFILE", "OFAC_SITEMAP", "OfacFaqPageHandler", "parse_faq_page"]

OFAC_SITEMAP = "https://ofac.treasury.gov/sitemap.xml"

_FAQ_URL_RE = re.compile(r"^https://ofac\.treasury\.gov/faqs/\d+$")
_TOPIC_RE = re.compile(r'views-field-field-topic.*?field-content[^>]*>(.*?)</div>', re.DOTALL)


def _faq_id(url: str) -> str:
    return "FAQ " + url.rsplit("/", 1)[-1]


def parse_faq_page(response: Response, task: TaskView) -> TaskResult:
    url = str(task.params["url"])
    faq_id = _faq_id(url)
    html = response_text(response)

    topic = None
    topic_match = _TOPIC_RE.search(html)
    if topic_match:
        topic = strip_tags(topic_match.group(1))[:200] or None

    body = ""
    start = html.find("ofac-faq-item")
    if start > 0:
        end = html.find("</main>", start)
        body = strip_tags(html[start : end if end > 0 else start + 20000])

    title = f"{topic or 'OFAC FAQ'} — {faq_id}"
    row: dict[str, Any] = {
        "agency": "ofac",
        "department": department_of("ofac"),
        "native_id": faq_id,
        "channel": "faq",
        "native_type": "FAQ entry",
        "doc_type": "FAQ",
        "title": title,
        "issued_date": None,
        "revised_date": task.params.get("lastmod"),
        "product_area": topic,
        "url": url,
        "folder": guid_folder("ofac", faq_id.replace(" ", "-")),
        "text_extracted": body or None,
    }
    return TaskResult(
        upsert_rows={"guidance_documents": [row]},
        files=[FileOut(path=f"{row['folder']}/page.html", content=response.content)],
    )


class OfacFaqPageHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=str(task.params["url"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        return parse_faq_page(response, task)


OFAC_PROFILE = AgencyProfile(
    agency="ofac",
    matches=lambda url: bool(_FAQ_URL_RE.match(url)),
    parse_page=parse_faq_page,
)
register(OFAC_PROFILE)
