"""Task type ``govza_file``: one document's PDF, one request.

``GET`` the PDF link extracted from the document page (first link under
``/sites/default/files/`` — probed 2026-10-10 on the 2002/2005/2025
samples; the bytes carry a real text layer on all three, so this is the
digital-native carrier, not a scan). The response must start with the
``%PDF`` magic — anything else (an HTML error page behind a 200, say)
dies loud. A 404 keeps the default permanent semantics: the portal
linked the file, so a missing one is real link rot, archived to
``failures/`` by the engine.

The seed carries the ``doc_id`` computed by the detail task, so the
bytes land as that document's primary artifact (local_path / file_hash /
raw_format=pdf on the documents row).
"""

from __future__ import annotations

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView

__all__ = ["FileHandler"]


class FileHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=str(task.params["pdf_url"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        href = str(task.params["href"])
        path = str(task.params["path"])
        if not response.content.startswith(b"%PDF"):
            head = response.content[:64]
            raise ValueError(
                f"govza_file {href}: body is not a PDF (starts {head!r}) — "
                "delivery shape may have changed"
            )
        doc_id = str(task.params.get("doc_id") or "") or None
        return TaskResult(files=[FileOut(path=path, content=response.content, doc_id=doc_id)])
