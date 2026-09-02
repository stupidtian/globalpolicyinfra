"""Treasury / OCC: bank-practice bulletins via sitemap.

occ.gov's sitemap inlines detail URLs; filtering
``/news-issuances/bulletins/{year}/bulletin-{year}-{n}.html`` yields the
bulletin library. Each ``guid_page`` extracts the title (the <title> tag
minus the site suffix), the issuing date (several OCC markups, lenient),
and archives the page — bulletins are full-text HTML, no separate PDF.
"""

from __future__ import annotations

import re
from typing import Any

from adapters.base import FileOut, Response, TaskResult, TaskView
from adapters.usa.sources.guidance.common import (
    AgencyProfile,
    department_of,
    guid_folder,
    register,
    response_text,
    strip_tags,
)

__all__ = ["OCC_PROFILE", "OCC_SITEMAP", "parse_bulletin_page"]

OCC_SITEMAP = "https://www.occ.gov/sitemap.xml"

_BULLETIN_URL_RE = re.compile(
    r"^https://www\.occ\.gov/news-issuances/bulletins/(\d{4})/bulletin-(\d{4})-(\d+)\.html$"
)
_TITLE_RE = re.compile(r"<title>([^<]+)</title>", re.DOTALL)
_DATE_PATTERNS = (
    re.compile(r"(?:Date\s+Issued|Publish(?:ed)?\s*Date|Bulletin\s*Date)\s*[:>]?\s*([A-Z][a-z]+ \d{1,2}, \d{4})", re.IGNORECASE),
    re.compile(r"(\d{4}-\d{2}-\d{2})", ),
    re.compile(r'datetime="(\d{4}-\d{2}-\d{2})"'),
)
_SUMMARY_RE = re.compile(
    r'(?:class="[^"]*(?:bulletin|highlight|summary|description)[^"]*"|name="description"\s+content=)"?\s*>\s*([^<]{20,600})', re.IGNORECASE
)


def _normalize_date(raw: str) -> str:
    raw = raw.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    months = {
        m: f"{i:02d}"
        for i, m in enumerate(
            ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"], 1
        )
    }
    m = re.fullmatch(r"([A-Z][a-z]+) (\d{1,2}), (\d{4})", raw)
    if m and m.group(1) in months:
        return f"{m.group(3)}-{months[m.group(1)]}-{int(m.group(2)):02d}"
    return raw[:10]


def parse_bulletin_page(response: Response, task: TaskView) -> TaskResult:
    url = str(task.params["url"])
    match = _BULLETIN_URL_RE.match(url)
    year = match.group(1) if match else None
    seq = match.group(3) if match else None
    native_id = f"Bulletin {year}-{seq}" if match else "url-" + url[-40:]
    html = response_text(response)

    title = None
    title_match = _TITLE_RE.search(html)
    if title_match:
        title = re.sub(r"\s+", " ", title_match.group(1)).strip()
        title = re.split(r"\s*\|\s*", title)[0].strip() or None

    issued = task.params.get("lastmod")
    for pattern in _DATE_PATTERNS:
        date_match = pattern.search(html)
        if date_match:
            issued = _normalize_date(date_match.group(1))
            break

    body_match = re.search(r"<main[^>]*>(.*?)</main>", html, re.DOTALL)
    text = strip_tags(body_match.group(1)) if body_match else ""

    row: dict[str, Any] = {
        "agency": "occ",
        "department": department_of("occ"),
        "native_id": native_id,
        "channel": "bulletin",
        "native_type": "OCC Bulletin",
        "doc_type": "BULLETIN",
        "title": title or native_id,
        "issued_date": issued,
        "revised_date": task.params.get("lastmod"),
        "url": url,
        "folder": guid_folder("occ", native_id.replace(" ", "-"), year),
        "text_extracted": text[:30000] or None,
    }
    return TaskResult(
        upsert_rows={"guidance_documents": [row]},
        files=[FileOut(path=f"{row['folder']}/page.html", content=response.content)],
    )


OCC_PROFILE = AgencyProfile(
    agency="occ",
    matches=lambda url: bool(_BULLETIN_URL_RE.match(url)),
    parse_page=parse_bulletin_page,
)
register(OCC_PROFILE)
