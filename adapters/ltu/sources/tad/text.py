"""Task type ``tad_text``: one document's original text, one request.

GET ``/rs/legalact/TAD/{tadId}/`` — the resource-service layer behind
the portal page's text iframe — and store the response bytes verbatim
as the ``text.html`` primary file (the as-adopted original edition,
both TAIS-era and hash-id documents answered, probed 2026-09-15). The
bibliographic record already exists (``tad_doc`` ran moments before):
this task only attaches path, hash, format and collection date to its
doc_id via the framework's file-carrying update.

The request declares ``accept_not_found``: the /rs/ layer answers HTTP
404 with a small "SIPIS" error page for acts that have NO electronic
original text at all (scan-era acts and acts the register never
digitised; probed across the 2000-2003 backfill, 2026-09-19). Such a
document stays registered metadata-only — the act is in the corpus,
its text is a source-side data boundary — and the task is an explained
empty. A 404 whose body is NOT the known SIPIS page, however, means
something truly broke and fails loud; so does a 404 whose tadId came
from a hash-era detail page (those always have /rs/ text).
"""

from __future__ import annotations

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.ltu.sources.tad import PORTAL_BASE, decode_response, source_url_for
from core.document import compute_doc_id

__all__ = ["TadTextHandler"]


def _text_path(pid: str, pub_iso: str) -> str:
    ymd = pub_iso.replace("-", "")
    return f"01_raw/tad/{pub_iso[:4]}/D{ymd}/{pid}/text.html"


class TadTextHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        tad_id = str(task.params["tad_id"])
        return RequestSpec(
            url=f"{PORTAL_BASE}/rs/legalact/TAD/{tad_id}/",
            accept_not_found=True,
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        pid = str(task.params["pid"])
        pub_iso = str(task.params["pub_date"])

        if response.status_code in (404, 410):
            body = decode_response(response.content)
            if "SIPIS" not in body:
                raise ValueError(
                    f"tad_text {pid}: HTTP {response.status_code} with an unexpected "
                    "body — not the known /rs/ SIPIS error page"
                )
            return TaskResult(
                expected_empty=(
                    f"tad_text {pid}: the /rs/ text service carries no electronic "
                    f"text for this act (HTTP {response.status_code}, scan era or "
                    "not digitised) — document registered without a text file"
                )
            )

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
