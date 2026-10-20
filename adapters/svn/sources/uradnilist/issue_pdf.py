"""Task type ``ul_pdf``: one as-published gazette PDF, verbatim.

GET ``/api/uradni-list/objava/{name}.pdf`` and store the bytes verbatim as
``01_raw/uradnilist/{year}/{name}``. Two modes, set by whether the seed
carries ``doc_ids`` (the ul_date handler branches on the ZOUL boundary):

- **primary mode** (post-ZOUL: one act = one PDF): one FileOut per
  doc_id — write_batch's file attachment sets each document row's
  local_path/file_hash, so the PDF *is* the document's file.
- **secondary mode** (pre-ZOUL: one whole-issue file shared by N acts):
  no ``doc_ids`` — a single FileOut without doc_id stores the file once;
  the acts' rows point at it through ``meta.ul_pdf_path`` (recorded at
  listing time), while the archival HTML page carries the doc_id. The
  path is ledgered either way (multi-file convention, FRA precedent).

Probed 2026-10-12: plain 200 application/pdf, no session, no key;
1991-1994 files are whole-issue scans, 1995+ digital with a text layer.
See docs/countries/svn/uradnilist-zh.md.
"""

from __future__ import annotations

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.svn.sources.uradnilist import objava_url_for, pdf_rel_path

__all__ = ["UlPdfHandler"]

_MAGIC = b"%PDF-"


class UlPdfHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=objava_url_for(str(task.params["pdf"])))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        pdf_name = str(task.params["pdf"])
        day = str(task.params["date"])
        doc_ids: list[str] = [str(d) for d in task.params.get("doc_ids", [])]
        if "/" in pdf_name or "\\" in pdf_name or ".." in pdf_name:
            raise ValueError(
                f"ul_pdf {pdf_name!r}: path separators in the source file name — "
                "refusing to build a storage path from it"
            )
        if response.status_code != 200:
            raise ValueError(
                f"ul_pdf {pdf_name}: unexpected status {response.status_code} — "
                "published gazette files must answer 200"
            )
        if not response.content.startswith(_MAGIC):
            raise ValueError(
                f"ul_pdf {pdf_name}: response is not a PDF (bad magic) — the "
                "objava endpoint may have moved or returned an error page"
            )
        path = pdf_rel_path(day, pdf_name)
        files: list[FileOut] = (
            [FileOut(path=path, content=response.content, doc_id=d) for d in doc_ids]
            if doc_ids
            else [FileOut(path=path, content=response.content)]
        )
        return TaskResult(files=files)
