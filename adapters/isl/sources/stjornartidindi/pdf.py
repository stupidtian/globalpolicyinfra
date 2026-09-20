"""Task type ``stjornartidindi_pdf``: one advert's PDF, one request.

``GET`` the ``pdfUrl`` direct link from the advert detail
(``https://adverts.stjornartidindi.is/{A|B|C}_nr_{number}_{year}.pdf``,
probed 2026-09-17: HTTP 200, ``application/pdf``, ``%PDF-`` magic,
sample 25). Only ever seeded as the stub-era fallback (1995-2000 sparse
era, where the inline HTML is a one-line digitisation stub and the PDF
is the only body carrier; modern adverts never produce this task).

When the seed carries a ``doc_id`` (the no-HTML-at-all case) the PDF is
that document's *primary* file; otherwise it lands as the sibling of
the stub ``doc.html``. Either way the bytes must start with the ``%PDF``
magic — anything else (an HTML error page behind a 200, say) dies loud.
A 404 keeps the default permanent semantics: the PDF is the only body
carrier for exactly the era this task exists for, so a missing one is a
real gap, not data.
"""

from __future__ import annotations

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView

__all__ = ["PdfHandler"]


class PdfHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=str(task.params["pdf_url"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        advert_id = str(task.params["id"])
        path = str(task.params["path"])
        if not response.content.startswith(b"%PDF"):
            head = response.content[:64]
            raise ValueError(
                f"stjornartidindi_pdf {advert_id}: body is not a PDF "
                f"(starts {head!r}) — delivery shape may have changed"
            )
        doc_id = str(task.params.get("doc_id") or "") or None
        return TaskResult(files=[FileOut(path=path, content=response.content, doc_id=doc_id)])
