"""Task type ``diario_pdf``: one gazette issue's file.

GET the dynamic-content URL extracted from the viewer page — a
session-bound PrimeFaces resource (``pfdrid`` token), fetched on the
same run's cookie jar. The response must be the whole-issue PDF; the
``%PDF-`` magic is verified loudly. The bytes go to disk verbatim as the
issue's primary file and the issue registers as a document:

- ``publication_date`` = the issue's publication date (the gazette
  publication event — the time-series anchor);
- ``source_url`` = the canonical ``?numero={N}`` address on the searcher
  (the searcher has no static per-issue URL; the number parameter keeps
  every doc_id hash distinct without touching session state);
- title = "Diario Oficial No. {numero} de {date}" — constructed from the
  masthead's own self-description ("Año CLXII No. 53.662"), there being
  no per-issue title element on the site.
"""

from __future__ import annotations

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.col.sources.diario import ISSUE_URL_TEMPLATE, SEARCHER_URL
from core.document import DocumentRecord, compute_doc_id

__all__ = ["DiarioPdfHandler"]


class DiarioPdfHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=_absolute(str(task.params["dyn_url"])))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        day = str(task.params["date"])
        numero = str(task.params["numero"])
        if response.status_code != 200:
            raise ValueError(
                f"diario issue {numero} ({day}): PDF answered HTTP {response.status_code}"
            )
        if not response.content.startswith(b"%PDF-"):
            raise ValueError(
                f"diario issue {numero} ({day}): body is not a PDF "
                f"(magic {response.content[:8]!r})"
            )

        numero_diario = numero  # original string, dots preserved ("53.659")
        meta: dict[str, str] = {
            "numero_diario": numero_diario,
            "tipo_edicion": str(task.params.get("tipo_edicion", "")),
            "dynamic_query": str(task.params.get("dyn_url", ""))[:512],
            "files": "diario.pdf",
        }
        publication_date = day
        source_url = ISSUE_URL_TEMPLATE.format(numero=numero_diario)
        document = DocumentRecord(
            title=f"Diario Oficial No. {numero_diario} de {day}",
            source_url=source_url,
            publication_date=publication_date,
            issuing_authority="Imprenta Nacional de Colombia",
            doc_type="OTHER",
            language="spa",
            raw_metadata=meta,
        )
        doc_id = compute_doc_id("COL", source_url, publication_date)

        path = f"01_raw/diario/{day[:4]}/D{day.replace('-', '')}/{numero_diario.replace('.', '')}/diario.pdf"
        return TaskResult(
            documents=[document],
            files=[FileOut(path=path, content=response.content, doc_id=doc_id)],
        )


def _absolute(dyn_url: str) -> str:
    """The viewer's object data is site-relative (starts with ``/diario/…``);
    join it onto the site root (no trailing slash — a doubled slash made
    the trial run's first download 404)."""
    root = SEARCHER_URL[: -len("diario/")].rstrip("/")
    return f"{root}{dyn_url}"
