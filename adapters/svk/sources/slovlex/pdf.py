"""Task type ``svk_pdf``: one instrument's official PDF (the binding form).

The HTML page itself warns that its display is informative and the PDF is
the legally binding text, so the PDF is captured as a sibling file. The
one-request-per-task contract makes this fetch a task of its own, placed
BEFORE ``svk_doc``: whether the PDF exists decides ``pdf_ok``, which the
doc task carries into ``meta.files`` — the ledger never claims a file
that is not on disk.

URL: derived from the page-native link skeleton with the stale
``/static/pdf`` prefix corrected to the live ``/pdf`` (probed 2026-09-08;
both prefix variants download-verified). 404/410 is declared
not-found data: the PDF is simply absent and the HTML remains the
document; any other failure escalates.
"""

from __future__ import annotations

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.svk.sources.slovlex import canonical_pdf_url, iri_parts

__all__ = ["SvkPdfHandler", "pdf_path"]


def pdf_path(iri: str) -> str:
    """Raw-folder path of the PDF below the country root."""
    rocnik, number, ver = iri_parts(iri)
    return f"01_raw/slovlex/{rocnik}/{int(number):03d}/{rocnik}_{int(number):03d}_{ver}.pdf"


class SvkPdfHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=canonical_pdf_url(str(task.params["iri"])),
            accept_not_found=True,  # a missing PDF is data, not a failure
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = dict(task.params)
        iri = str(params["iri"])
        if response.status_code in (404, 410):
            return TaskResult(
                next_tasks=[TaskSeed(type="svk_doc", params={**params, "pdf_ok": 0})],
                expected_empty=f"no PDF served for {iri} (HTML remains the document)",
            )
        if response.status_code != 200:
            raise ValueError(f"PDF of {iri} returned HTTP {response.status_code}")
        if not response.content.startswith(b"%PDF-"):
            raise ValueError(f"PDF of {iri} does not start with %PDF-")
        return TaskResult(
            files=[FileOut(path=pdf_path(iri), content=response.content)],
            next_tasks=[TaskSeed(type="svk_doc", params={**params, "pdf_ok": 1})],
        )
