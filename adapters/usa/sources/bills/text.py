"""Task types ``bill_text`` / ``bill_text_dl``: a bill's text versions.

``bill_text`` lists the versions (Introduced in House / Engrossed / Enrolled
/ Public Law …) and registers each as a **document** (entity_ref points at
the bill row) plus spawns one ``bill_text_dl`` per version.

``bill_text_dl`` fetches the artifact (XML preferred) into the bill's
folder; the file's doc_id linkage lets the framework fill in
local_path/file_hash/content_length on the documents row.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.usa.schema import bill_folder, bill_identity
from adapters.usa.sources.bills.enumerate import API_BASE
from core.document import DocumentRecord, compute_doc_id

_VERSION_RE = re.compile(r"BILLS-\d+[a-z]+\d+([a-z0-9]+)\.(?:xml|htm|pdf)", re.IGNORECASE)


def _identity(task: TaskView) -> tuple[str, str, str, str]:
    bill_id, type_lower, number_str = bill_identity(
        int(task.params["congress"]), str(task.params["type"]), str(task.params["number"])
    )
    folder = bill_folder(int(task.params["congress"]), type_lower, number_str)
    return bill_id, type_lower, number_str, folder


def _version_suffix(url: str) -> str:
    match = _VERSION_RE.search(url)
    return match.group(1) if match else "version"


class BillTextHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        _, type_lower, number_str, _ = _identity(task)
        return RequestSpec(
            url=f"{API_BASE}/bill/{task.params['congress']}/{type_lower}/{number_str}/text",
            key_env="CONGRESS_API_KEY",
            key_param="api_key",
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        payload = response.json()
        bill_id, _, _, folder = _identity(task)
        bill_title = (payload.get("bill") or {}).get("title") or bill_id
        documents: list[DocumentRecord] = []
        next_tasks: list[TaskSeed] = []
        for version in payload.get("textVersions", []):
            formats = {f.get("type"): f.get("url") for f in (version.get("formats") or [])}
            url = (
                formats.get("Formatted XML")
                or formats.get("Formatted Text")
                or formats.get("PDF")
            )
            if not url:
                continue
            url = str(url)
            suffix = _version_suffix(url)
            publication_date = str(version.get("date") or "")[:10] or None
            documents.append(
                DocumentRecord(
                    title=f"{bill_title} [{version.get('type', 'version')}]",
                    source_url=url,
                    publication_date=publication_date,
                    issuing_authority="U.S. Congress",
                    doc_type="BILL_TEXT",
                    entity_ref=f"bills:{bill_id}",
                    language="en",
                    raw_metadata={
                        "version_type": str(version.get("type", "")),
                        "version_suffix": suffix,
                        "htm_url": str(formats.get("Formatted Text", "")),
                        "pdf_url": str(formats.get("PDF", "")),
                    },
                )
            )
            next_tasks.append(
                TaskSeed(
                    type="bill_text_dl",
                    params={
                        "url": url,
                        "date": publication_date or "",
                        "suffix": suffix,
                        "folder": folder,
                    },
                )
            )
        if not documents:
            return TaskResult(expected_empty="bill has no text versions on the API")
        return TaskResult(documents=documents, next_tasks=next_tasks)


class BillTextDownloadHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=str(task.params["url"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        url = str(task.params["url"])
        suffix = str(task.params.get("suffix") or _version_suffix(url))
        folder = str(task.params["folder"])
        extension = PurePosixPath(urlsplit(url).path).suffix.lstrip(".").lower() or "xml"
        if extension == "htm":
            extension = "html"
        doc_id = compute_doc_id("USA", url, str(task.params.get("date") or "") or None)
        return TaskResult(
            files=[
                FileOut(
                    path=f"{folder}/text/{suffix}.{extension}",
                    content=response.content,
                    doc_id=doc_id,
                )
            ]
        )
