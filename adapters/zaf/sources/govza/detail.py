"""Task type ``govza_detail``: one document record, one request.

``GET`` the document's own portal page (``/documents/{type}/{slug}`` —
the listing row's href; probed 2026-10-10, three era samples in the
task folder). The page's own markup carries none of the bibliographic
fields reliably (no repeated document date, and titles only in page
chrome), so the listing row — which is the portal's own index of the
document — is the bibliographic authority: title, publication date,
native type and the gazette codes all travel in the task params and go
straight into the ledger. The page contributes what only it has:

- the identity check: Drupal's ``<link rel="canonical">`` must name the
  same href the listing row pointed at (verified present and matching
  on 2025/2005/1995 samples) — a redirect or a re-slug is a loud
  listing/detail drift, not a silent mis-attribution;
- the PDF links (``/sites/default/files/gcis_document/{YYYYMM}/…pdf``,
  first one under the file store wins): the primary ``doc.pdf`` is
  fetched by the govza_file task seeded here, carrying the doc_id so
  the bytes land as that document's artifact (section 6.9: one file
  per doc_id carries it);
- a page with no PDF at all (the early non-gazette layers, e.g. 1995
  white papers) stores its own HTML as the primary file: the inline
  body in ``div.field--name-body`` is that document's only carrier.
"""

from __future__ import annotations

import re

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.zaf.sources.govza import (
    BASE_URL,
    map_doc_type,
    site_url_for,
    slug_for,
)
from core.document import DocumentRecord, compute_doc_id

__all__ = ["DetailHandler"]

_CANONICAL_RE = re.compile(r'<link rel="canonical" href="([^"]+)"')
_PDF_RE = re.compile(r'<a href="([^"]+\.pdf(?:\?[^"]*)?)"', re.IGNORECASE)
_FILE_STORE = "/sites/default/files/"


def _primary_pdf(pdf_urls: list[str]) -> str | None:
    """First PDF under the portal's file store, else the first PDF."""
    for url in pdf_urls:
        if _FILE_STORE in url:
            return url
    return pdf_urls[0] if pdf_urls else None


class DetailHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=site_url_for(str(task.params["href"])))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        href = str(task.params["href"])
        doc_date = str(task.params["doc_date"])
        if not doc_date:
            raise ValueError(
                f"govza_detail {href}: empty document date in the seed — the "
                "listing row is the date authority and must carry it"
            )
        label = href.rsplit("/", 1)[-1]

        html = response.content.decode("utf-8", errors="replace")
        head = html[:2048].lower()
        if "<!doctype html" not in head and "<html" not in head:
            raise ValueError(
                f"govza_detail {label}: response is not an HTML page "
                f"(HTTP {response.status_code}, {len(response.content)} bytes)"
            )
        canonical = _CANONICAL_RE.search(html)
        if not canonical:
            raise ValueError(
                f"govza_detail {label}: no canonical link — page shape may "
                "have changed"
            )
        if canonical.group(1).rstrip("/") != site_url_for(href).rstrip("/"):
            raise ValueError(
                f"govza_detail {label}: canonical says {canonical.group(1)!r} "
                f"but the listing row pointed at {href!r} — listing/detail "
                "identity drift"
            )

        meta: dict[str, str] = dict(task.params.get("meta") or {})
        pdf_urls = [
            u if u.startswith("http") else f"{BASE_URL}{u}"
            for u in dict.fromkeys(_PDF_RE.findall(html))
        ]
        if pdf_urls:
            meta["pdf_urls"] = ",".join(pdf_urls)

        native_type = meta.get("native_type", "")
        record = DocumentRecord(
            title=str(task.params["title"]),
            source_url=site_url_for(href),
            publication_date=doc_date,
            doc_type=map_doc_type(native_type),
            language="eng",
            raw_metadata=meta,
        )
        doc_id = compute_doc_id("ZAF", record.source_url, doc_date)
        folder = f"01_raw/govza/{doc_date[:4]}/{doc_date[5:7]}/{slug_for(href)}"

        pdf_url = _primary_pdf(pdf_urls)
        if pdf_url is not None:
            return TaskResult(
                documents=[record],
                next_tasks=[
                    TaskSeed(
                        type="govza_file",
                        params={
                            "href": href,
                            "pdf_url": pdf_url,
                            "path": f"{folder}/doc.pdf",
                            "doc_id": doc_id,
                        },
                    )
                ],
            )
        # No PDF: the detail page itself is the primary carrier (the
        # div.field--name-body inline body is all there is).
        return TaskResult(
            documents=[record],
            files=[
                FileOut(path=f"{folder}/page.html", content=response.content, doc_id=doc_id)
            ],
        )
