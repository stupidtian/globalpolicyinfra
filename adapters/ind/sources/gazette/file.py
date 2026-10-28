"""Task type ``gz_file``: one gazette issue, one request, one document.

GET ``/WriteReadData/{year}/{serial}.pdf`` — the session-free static
path derived from the row's UGID (``CG-DL-E-13102026-277126`` ->
``/WriteReadData/2026/277126.pdf``; mapping probed live 2026-10-04/15,
multi-node and through the portal itself). The entry came from a grid
fetched moments ago, so a 404 or a non-PDF body is an unexplained shape
and fails loud (never declared as data).

``source_url`` is the canonical PDF address (session-free, stable), so
re-crawls of the same issue converge on one doc_id. The row metadata
(ministry/department/subject/dates) rides in the task params and lands
in the documents row.
"""

from __future__ import annotations

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.ind.sources.gazette import SITE, parse_ugid
from core.document import DocumentRecord, compute_doc_id

__all__ = ["GzFileHandler"]

_KIND_LABELS = {"E": "Extraordinary", "W": "Weekly"}


class GzFileHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        ugid = str(task.params["ugid"])
        parsed = parse_ugid(ugid)
        return RequestSpec(
            url=f"{SITE}/WriteReadData/{parsed['year']}/{parsed['serial']}.pdf",
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = task.params
        ugid = str(params["ugid"])
        parsed = parse_ugid(ugid)
        if not response.content.startswith(b"%PDF"):
            head = response.content[:80]
            raise ValueError(
                f"gazette {ugid}: response is not a PDF "
                f"(status {response.status_code}, head {head!r})"
            )

        pub = str(params.get("pub") or parsed["date"])
        kind_label = _KIND_LABELS.get(parsed["kind"], parsed["kind"])
        source_url = f"{SITE}/WriteReadData/{parsed['year']}/{parsed['serial']}.pdf"
        subject = str(params.get("subject", ""))
        title = subject if subject else f"Gazette of India {kind_label}, {pub} ({ugid})"

        meta = {
            "ugid": ugid,
            "region": parsed["region"],
            "native_type": parsed["kind"],
            "kind_label": kind_label,
            "category": str(params.get("category", "")),
            "part_section": str(params.get("part", "")),
            "ministry": str(params.get("ministry", "")),
            "department": str(params.get("department", "")),
            "office": str(params.get("office", "")),
            "issue_date": str(params.get("issue", "")),
            "file_size": str(params.get("file_size", "")),
            "source": "egazette",
        }

        record = DocumentRecord(
            title=title,
            source_url=source_url,
            publication_date=pub,
            issuing_authority="Department of Publication, Ministry of Housing and Urban Affairs",
            doc_type="OTHER",
            language="eng",
            raw_metadata=meta,
        )
        doc_id = compute_doc_id("IND", source_url, pub)
        path = f"01_raw/gazette/{parsed['year']}/{ugid}.pdf"
        return TaskResult(
            documents=[record],
            files=[FileOut(path=path, content=response.content, doc_id=doc_id)],
        )
