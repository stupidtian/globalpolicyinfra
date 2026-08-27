"""Task type ``bgbl_pdf``: fetch one gazette entry's PDF and record it.

media.xav is session-bound (cookie + this session's csrf token, both
required — P0 matrix experiment). The request URL carries the medianame
with slashes turned into underscores; the transport follows the 302 to the
public delivery URL and hands back the bytes.

One task yields exactly one document and one file: the flat-path shape this
pilot exists to validate. ``doc_id`` is computed with the shared rule
(core.document.compute_doc_id) so the FileOut can point at its document.
"""

from __future__ import annotations

from urllib.parse import quote

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.deu.sources.bgbl import BASE_URL, BOOK, USER_AGENT
from adapters.deu.sources.bgbl.issue import issue_folder
from core.document import DocumentRecord, compute_doc_id

__all__ = ["BgblPdfHandler", "canonical_source_url"]


def canonical_source_url(medianame: str) -> str:
    """Stable, rebuildable URL of one PDF: media.xav form without session
    params (doc_id hashes this; the real request adds SID/_csrf)."""
    slashed = quote(medianame.replace("/", "_"), safe="")
    return f"{BASE_URL}/media.xav/{slashed}?medianame={quote(medianame, safe='')}"


class BgblPdfHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        medianame = str(task.params["medianame"])
        return RequestSpec(
            url=f"{BASE_URL}/media.xav/{quote(medianame.replace('/', '_'), safe='')}",
            params={
                "SID": "",
                "bk": BOOK,
                "medianame": medianame,
                "_csrf": str(task.params["csrf"]),
            },
            headers={"User-Agent": USER_AGENT},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = dict(task.params)
        content = response.content
        if not content.startswith(b"%PDF-"):
            raise ValueError(
                f"expected a PDF for {params['pdf_name']}, got "
                f"{content[:40]!r} (HTTP {response.status_code})"
            )

        title = str(params["title"])
        publication_date = str(params["issue_date"])
        source_url = canonical_source_url(str(params["medianame"]))
        doc_id = compute_doc_id("DEU", source_url, publication_date)

        raw_metadata: dict[str, str] = {
            "part": str(params["part"]),
            "year": str(params["year"]),
            "issue_nr": str(params["issue_nr"]),
            "issue_label": str(params["issue_label"]),
            "issue_date": publication_date,
            "page_range": str(params["page_range"]),
            "entry_order": str(params["entry_order"]),
            "page_start": str(params["page_start"]),
            "pdf_name": str(params["pdf_name"]),
            "title_head": title.split(" ", 1)[0],
            "did": str(params["did"]),
        }
        if params.get("entry_date"):
            raw_metadata["entry_date"] = str(params["entry_date"])

        record = DocumentRecord(
            title=title,
            source_url=source_url,
            publication_date=publication_date,
            doc_type="OTHER",
            language="deu",
            raw_metadata=raw_metadata,
        )
        file_path = (
            f"{issue_folder(str(params['part']), params['year'], params['issue_nr'])}/"
            f"{params['pdf_name']}"
        )
        return TaskResult(
            documents=[record],
            files=[FileOut(path=file_path, content=content, doc_id=doc_id)],
        )
