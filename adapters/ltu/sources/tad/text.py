"""Task type ``tad_text``: one document's original text, one request.

GET ``/rs/legalact/TAD/{tadId}/`` — the resource-service layer behind
the portal page's text iframe — and store the response bytes verbatim
as the ``text.html`` primary file (the as-adopted original edition,
both TAIS-era and hash-id documents answered, probed 2026-09-15). The
bibliographic record already exists (``tad_doc`` ran moments before):
this task only attaches path, hash, format and collection date to its
doc_id via the framework's file-carrying update.

A 404 here is *not* declared as data: the tadId came from the detail
page fetched moments ago, so not-found means something truly broke and
must fail loud (the /rs/ error page answers HTTP 404 with a "SIPIS"
body — the transport raises permanent before parse ever sees it).
"""

from __future__ import annotations

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.ltu.sources.tad import PORTAL_BASE, source_url_for
from core.document import compute_doc_id

__all__ = ["TadTextHandler"]


def _text_path(pid: str, pub_iso: str) -> str:
    ymd = pub_iso.replace("-", "")
    return f"01_raw/tad/{pub_iso[:4]}/D{ymd}/{pid}/text.html"


class TadTextHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        tad_id = str(task.params["tad_id"])
        return RequestSpec(url=f"{PORTAL_BASE}/rs/legalact/TAD/{tad_id}/")

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        pid = str(task.params["pid"])
        pub_iso = str(task.params["pub_date"])
        source_url = source_url_for(pid)
        return TaskResult(
            files=[
                FileOut(
                    path=_text_path(pid, pub_iso),
                    content=response.content,
                    doc_id=compute_doc_id("LTU", source_url, pub_iso),
                )
            ]
        )
