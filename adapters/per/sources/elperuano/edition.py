"""Task type ``per_day_edition``: one whole-edition PDF of the legacy era.

The listing groups the day's legacy entries by edition URL; this task
downloads that one file and attaches it to **every** norm document of the
day — one FileOut per doc_id, all sharing the same path and bytes. That
is the gazette's honest as-published shape (a day's norms ship as one
combined issue; the old per-norm endpoint returns malformed-encrypted
PDFs no reader accepts), and the engine's write_batch fills each
document's ``local_path``/``file_hash`` from its own doc_id-marked
FileOut.
"""

from __future__ import annotations

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.per.sources.elperuano import edition_pdf_path, old_source_url
from core.document import compute_doc_id

__all__ = ["PerDayEditionHandler"]


class PerDayEditionHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=str(task.params["url"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        date_iso = str(task.params["date"])
        code = str(task.params["code"])
        ymd = str(task.params["ymd"])
        data_ids = list(task.params["data_ids"])
        if not data_ids:
            raise ValueError(f"edition {code}{ymd}: no data_ids attached by the listing")
        if not response.content.startswith(b"%PDF-"):
            raise ValueError(
                f"edition {code}{ymd}: response is not a PDF "
                f"(head={response.content[:8]!r})"
            )
        path = edition_pdf_path(code, ymd)
        files = [
            FileOut(
                path=path,
                content=response.content,
                doc_id=compute_doc_id("PER", old_source_url(code, ymd, data_id), date_iso),
            )
            for data_id in data_ids
        ]
        return TaskResult(files=files)
