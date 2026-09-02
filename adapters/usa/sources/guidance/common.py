"""Shared machinery for the guidance source: the generic task handlers.

Five task shapes cover every first-batch channel (guidance-zh.md section 3);
agency-specific knowledge lives in small profiles::

    gz_index       official-gazette index page (IRB year listing)
    gz_issue       one gazette issue (IRB weekly) -> document rows
    sitemap_page   one sitemap.xml -> filter -> guid_page tasks
    guid_page      one agency document page -> row + download tasks
    guid_file_dl   one file (pdf/doc/html) -> documents ledger entry

``guid_page``/``gz_*`` dispatch on ``task.params["agency"]`` to a
:class:`AgencyProfile` contributed by each agency module — the two-function
discipline still holds, just expressed as profile hooks.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree as ET

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskSeed, TaskView
from core.document import DocumentRecord, compute_doc_id

__all__ = [
    "DEPARTMENTS",
    "AgencyProfile",
    "GuidFileDownloadHandler",
    "GuidPageHandler",
    "IndexPageHandler",
    "PdfListingHandler",
    "SitemapPageHandler",
    "department_of",
    "guid_folder",
    "native_id_from_url",
    "response_text",
    "strip_tags",
]

#: agency -> parent department (layout spec 2026-09-01). Standalone
#: department-rank agencies map to themselves — their folder path has no
#: parent segment. Reorganizations change this table in one place only.
DEPARTMENTS: dict[str, str] = {
    "irs": "treasury",
    "ofac": "treasury",
    "occ": "treasury",
    "bis": "commerce",
    "nist": "commerce",
    "nws": "commerce",
    "epa": "epa",
}


def department_of(agency: str) -> str:
    department = DEPARTMENTS.get(agency)
    if department is None:
        raise ValueError(f"agency {agency!r} is not in DEPARTMENTS — add it there first")
    return department


def response_text(response: Response) -> str:
    """UTF-8 view of a response body (lossy on bad bytes — HTML tolerant)."""
    return response.content.decode("utf-8", "replace")


def strip_tags(fragment: str) -> str:
    """Visible text of an HTML fragment, whitespace-collapsed."""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", fragment, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def native_id_from_url(url: str) -> str:
    """Stable fallback id when the source has no native one (rule R1: never
    invent a semantic id — a content-free hash is honest)."""
    return "url-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]


def guid_folder(agency: str, native_id: str, year: str | None = None) -> str:
    """Per-document folder: 01_raw/guidance/{department}/{agency}/{year}/{native_id}/
    (layout spec 2026-09-01 — the department layer mirrors the doc-site
    grouping; standalone agencies like epa map to themselves and get no
    extra segment. Year-sharded like bills/FR folders; undated -> 'undated')."""
    safe_id = re.sub(r"[^A-Za-z0-9._-]+", "_", native_id)[:80] or "doc"
    department = department_of(agency)
    if department != agency:
        return f"01_raw/guidance/{department}/{agency}/{year or 'undated'}/{safe_id}"
    return f"01_raw/guidance/{agency}/{year or 'undated'}/{safe_id}"


@dataclass(frozen=True)
class AgencyProfile:
    """What one agency contributes to the generic handlers."""

    agency: str
    # sitemap URL filter; sources without a sitemap chain pass a never-match
    matches: Callable[[str], bool]
    # one agency document page -> row + mirrors
    parse_page: Callable[[Response, TaskView], TaskResult] | None = None
    # an index/listing page -> follow-up tasks (e.g. NWS series listing)
    parse_index: Callable[[Response, TaskView], TaskResult] | None = None
    # a listing page whose entries ARE files (BIS guidance PDFs, NWS directives)
    parse_listing: Callable[[Response, TaskView], TaskResult] | None = None


_REGISTRY: dict[str, AgencyProfile] = {}


def register(profile: AgencyProfile) -> None:
    _REGISTRY[profile.agency] = profile


def profile_for(agency: str) -> AgencyProfile:
    return _REGISTRY[agency]


class SitemapPageHandler:
    """One sitemap document: child sitemaps chain on, target URLs become
    guid_page tasks (quota-capped like the bills vote chain)."""

    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=str(task.params["url"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = task.params
        agency = str(params["agency"])
        profile = profile_for(agency)
        # wide window: EPA-style sitemaps carry stylesheet PIs and comments
        # before the root element (verified 2026-08-31)
        head = response.content.lstrip()[:1000].lower()
        if b"<urlset" not in head and b"<sitemapindex" not in head:
            # some sitemap-lookalike URLs return HTML pages; skip cleanly
            return TaskResult(expected_empty="response is not a sitemap document")
        root = ET.fromstring(response.content)
        entries: list[tuple[str, str | None]] = []
        for url_el in root.iter():
            # <url> children (urlset documents) or <sitemap> children
            # (sitemapindex documents, e.g. EPA's root) both carry loc/lastmod
            if not (url_el.tag.endswith("url") or url_el.tag.endswith("sitemap")):
                continue
            loc_text = lastmod = None
            for child in url_el:
                if child.tag.endswith("loc"):
                    loc_text = (child.text or "").strip()
                elif child.tag.endswith("lastmod"):
                    lastmod = (child.text or "").strip()[:10] or None
            if loc_text:
                entries.append((loc_text, lastmod))

        page = int(params.get("page", 1))
        max_pages = params.get("max_pages")
        quota_left = params.get("quota_left")
        next_tasks: list[TaskSeed] = []
        spawned = 0
        for url, lastmod in entries:
            last_segment = url.rsplit("/", 1)[-1].lower()
            is_sitemap = "sitemap" in last_segment and (
                last_segment.endswith(".xml") or ".xml?" in last_segment
            )
            if is_sitemap:
                if max_pages is None or page < int(max_pages):
                    chain = dict(params)
                    chain["url"] = url
                    chain["page"] = page + 1
                    if quota_left is not None:
                        # the quota is a whole-run budget, not per page: hand
                        # the remainder down the chain
                        chain["quota_left"] = int(quota_left) - spawned
                    next_tasks.append(TaskSeed(type="sitemap_page", params=chain))
            elif profile.matches(url) and (quota_left is None or spawned < int(quota_left)):
                page_params: dict[str, Any] = {"agency": agency, "url": url}
                if lastmod:
                    page_params["lastmod"] = lastmod
                next_tasks.append(TaskSeed(type="guid_page", params=page_params))
                spawned += 1
        return TaskResult(next_tasks=next_tasks)


class GuidPageHandler:
    """One agency document page; parsing is the agency profile's job."""

    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=str(task.params["url"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        profile = profile_for(str(task.params["agency"]))
        if profile.parse_page is None:
            raise ValueError(f"agency {profile.agency!r} has no guid_page parser")
        return profile.parse_page(response, task)


class IndexPageHandler:
    """One index page whose entries become follow-up tasks (agency-parsed)."""

    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=str(task.params["url"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        profile = profile_for(str(task.params["agency"]))
        if profile.parse_index is None:
            raise ValueError(f"agency {profile.agency!r} has no index parser")
        return profile.parse_index(response, task)


class PdfListingHandler:
    """One listing page whose entries ARE the documents (PDFs with titles);
    the agency profile turns them into rows + download tasks."""

    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=str(task.params["url"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        profile = profile_for(str(task.params["agency"]))
        if profile.parse_listing is None:
            raise ValueError(f"agency {profile.agency!r} has no listing parser")
        return profile.parse_listing(response, task)


class GuidFileDownloadHandler:
    """One artifact download; doc_id linkage fills the documents row."""

    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=str(task.params["url"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        url = str(task.params["url"])
        stem = str(task.params.get("stem") or "file")
        folder = str(task.params["folder"])
        extension = re.sub(r"[^A-Za-z0-9]", "", url.rsplit(".", 1)[-1])[:8] or "bin"
        doc_id = compute_doc_id("USA", url, str(task.params.get("date") or "") or None)
        record = None
        if task.params.get("meta_title"):
            record = DocumentRecord(
                title=str(task.params["meta_title"]),
                source_url=url,
                publication_date=str(task.params.get("date") or "") or None,
                issuing_authority=str(task.params.get("meta_authority") or "") or None,
                doc_type=str(task.params.get("meta_doc_type") or "") or None,
                entity_ref=str(task.params.get("entity_ref") or "") or None,
                language="en",
                raw_metadata={
                    "agency": str(task.params.get("agency") or ""),
                    "native_type": str(task.params.get("native_type") or ""),
                },
            )
        return TaskResult(
            documents=[record] if record else [],
            files=[
                FileOut(
                    path=f"{folder}/files/{stem}.{extension}",
                    content=response.content,
                    doc_id=doc_id,
                )
            ],
        )
