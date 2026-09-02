"""EPA: guidance documents behind a JS portal, enumerated via sitemap.

EPA's guidance portal (epa.gov/guidance) renders its lists client-side, but
the site sitemap exposes every content URL (~75k; 1,318 contain "guidance").
This channel therefore walks the sitemap and classifies each candidate with
a three-stage funnel (user-approved 2026-08-31, details in
guidance-epa-zh.md):

1. URL level    /newsreleases/, learn/faq sections, question-shaped slugs,
                /web-policies-and-procedures/ -> negative classes, slim row;
2. title level  news verbs ("EPA Announces …"), "Report:", "Comments
                from/of" -> negative classes, slim row;
3. positive     title keywords (Guidance/Memorandum/Directive/PRN codes),
                attached PDFs, or body keyword -> GUIDANCE: full parse with
                PDF downloads (capped at 10 per page).

Every URL the sitemap yields becomes a row — negative classes stay as slim
rows so the ledger can answer "what did we see and why wasn't it deep
crawled".
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from adapters.base import FileOut, Response, TaskResult, TaskSeed, TaskView
from adapters.usa.sources.guidance.common import (
    AgencyProfile,
    department_of,
    guid_folder,
    register,
    response_text,
    strip_tags,
)

__all__ = [
    "EPA_SITEMAP",
    "classify_epa_url",
    "parse_epa_page",
]

EPA_SITEMAP = "https://www.epa.gov/sitemap.xml"

_MAX_PDFS_PER_PAGE = 10

# -- stage 1: URL-level classification ------------------------------------------

_QUESTION_HEADS = (
    "what", "how", "are", "is", "can", "does", "do", "where", "why",
    "which", "should", "there",
)
_LEARN_SECTIONS = ("/learn-about", "what-you-can-do", "/faq")
_SITE_POLICY_SECTIONS = ("/web-policies-and-procedures/", "/webguide/")

_PDF_RE = re.compile(r'href="([^"]+\.pdf)"', re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>([^<]{4,160})")
_DATE_RE = re.compile(r"(?:Last updated on|Updated|Published)[^<]{0,10}([A-Z][a-z]+ \d{1,2}, 20\d\d)")
_MONTHS = {m: f"{i:02d}" for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}

#: stage 2 negative title prefixes (news about guidance, not guidance)
_NEWS_VERB_RE = re.compile(
    r"^(?:EPA|FDA|New EPA)\s+(?:Announces|Proposes|Rescinds|Issues|Releases|Publishes|Finalizes)\b"
)
_REPORT_RE = re.compile(r"^Report:")
_COMMENT_RE = re.compile(r"^Comments?\s+(?:from|of)\b")
#: stage 3 positive title markers
_POSITIVE_RE = re.compile(r"\b(guidance|memorandum|directive)\b", re.IGNORECASE)
_PRN_RE = re.compile(r"\bPRN\s*\d{4}-\d+", re.IGNORECASE)


def classify_epa_url(url: str) -> str | None:
    """Stage 1: negative classes detectable from the URL alone."""
    path = urlparse(url).path.lower()
    if path.startswith("/newsreleases/"):
        return "NEWS"
    if any(section in path for section in _LEARN_SECTIONS):
        return "LEARN"
    if any(section in path for section in _SITE_POLICY_SECTIONS):
        return "SITE_POLICY"
    tail = path.rstrip("/").rsplit("/", 1)[-1]
    if tail.split("-")[0] in _QUESTION_HEADS:
        return "FAQ_PAGE"
    return None  # candidate: needs the page


def _normalize_date(raw: str) -> str | None:
    m = re.fullmatch(r"([A-Z][a-z]+) (\d{1,2}), (20\d\d)", raw.strip())
    if m and m.group(1) in _MONTHS:
        return f"{m.group(3)}-{_MONTHS[m.group(1)]}-{int(m.group(2)):02d}"
    return None


def _slug(url: str) -> str:
    tail = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    return tail or "page"


def _slim_row(url: str, page_class: str, title: str | None) -> dict[str, Any]:
    return {
        "agency": "epa",
        "department": department_of("epa"),
        "native_id": _slug(url),
        "channel": "sitemap",
        "native_type": "EPA web page",
        "doc_type": "OTHER",  # channel rows, not semantic claims (rule R2)
        "title": (title or _slug(url))[:400],
        "url": url,
        "folder": guid_folder("epa", _slug(url)),
        "page_class": page_class,
        "text_extracted": None,
    }


def parse_epa_page(response: Response, task: TaskView) -> TaskResult:
    url = str(task.params["url"])
    html = response_text(response)

    title = None
    title_match = _TITLE_RE.search(html)
    if title_match:
        title = re.sub(r"\s+", " ", title_match.group(1)).split("|")[0].strip()

    url_class = classify_epa_url(url)
    if url_class is None:
        # stage 2: title-level negatives
        if title and _NEWS_VERB_RE.match(title):
            url_class = "NEWS"
        elif title and _REPORT_RE.match(title):
            url_class = "REPORT"
        elif title and _COMMENT_RE.match(title):
            url_class = "COMMENT"

    if url_class is not None:
        return TaskResult(upsert_rows={"guidance_documents": [_slim_row(url, url_class, title)]})

    # stage 3: positive signals -> full guidance parse
    pdfs = [urljoin(url, href) for href in dict.fromkeys(_PDF_RE.findall(html))]
    body_head = strip_tags(html[:60000])
    is_guidance = bool(
        (title and (_POSITIVE_RE.search(title) or _PRN_RE.search(title)))
        or pdfs
        or re.search(r"\bguidance\b", body_head, re.IGNORECASE)
    )
    if not is_guidance:
        return TaskResult(upsert_rows={"guidance_documents": [_slim_row(url, "OTHER", title)]})

    date = None
    date_match = _DATE_RE.search(html)
    if date_match:
        date = _normalize_date(date_match.group(1))

    native_id = _slug(url)
    folder = guid_folder("epa", native_id, date[:4] if date else None)
    row: dict[str, Any] = {
        "agency": "epa",
        "department": department_of("epa"),
        "native_id": native_id,
        "channel": "sitemap",
        "native_type": "EPA guidance page",
        "doc_type": "GUIDANCE",
        "title": (title or native_id)[:400],
        "issued_date": date,
        "url": url,
        "folder": folder,
        "page_class": "GUIDANCE",
        "text_extracted": body_head[:30000] or None,
    }
    next_tasks = [
        TaskSeed(
            type="guid_file_dl",
            params={
                "url": pdf_url,
                "date": date,
                "stem": f"att{i + 1}",
                "folder": folder,
                "meta_title": f"{title or native_id} (attachment {i + 1})",
                "meta_authority": "Environmental Protection Agency",
                "meta_doc_type": "GUIDANCE",
                "agency": "epa",
                "native_type": "EPA guidance attachment",
                "entity_ref": f"guidance_documents:epa:{native_id}",
            },
        )
        for i, pdf_url in enumerate(pdfs[:_MAX_PDFS_PER_PAGE])
    ]
    return TaskResult(
        upsert_rows={"guidance_documents": [row]},
        next_tasks=next_tasks,
        files=[FileOut(path=f"{folder}/page.html", content=response.content)],
    )


EPA_PROFILE = AgencyProfile(
    agency="epa",
    matches=lambda url: "guidance" in urlparse(url).path.lower(),
    parse_page=parse_epa_page,
)
register(EPA_PROFILE)
