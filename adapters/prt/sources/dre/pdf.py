"""Task type ``dre_pdf``: one gazette issue's whole-issue PDF.

GET ``https://dre.pt/application/file/{fileId}`` — the portal's stable
legacy redirector (probed alive on 2014 and 2026 samples, 2026-09-17);
it 302s onto the S3 files host (``files.diariodarepublica.pt``). The
bytes become the issue document's primary file (the document carries
``doc_id`` on the FileOut, so local_path / file_hash / content_length
land on the documents row).

The body must start with the PDF magic; anything else (an HTML error
shell, an empty body) is a broken download and dies loud rather than
registering a corrupt artifact.
"""

from __future__ import annotations

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView

__all__ = ["DrePdfHandler"]

_PDF_MAGIC = b"%PDF"


class DrePdfHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        file_id = str(task.params["file_id"])
        return RequestSpec(url=f"https://dre.pt/application/file/{file_id}")

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        file_id = str(task.params["file_id"])
        doc_id = str(task.params["doc_id"])
        path = str(task.params["path"])
        if not response.content.startswith(_PDF_MAGIC):
            head = response.content[:60]
            raise ValueError(
                f"dre_pdf {file_id}: body does not look like a PDF "
                f"({len(response.content)} bytes, head={head!r})"
            )
        return TaskResult(files=[FileOut(path=path, content=response.content, doc_id=doc_id)])
