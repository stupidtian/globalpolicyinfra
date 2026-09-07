"""Task type ``ebgbl_pdf``: fetch one PDF of a Verkündung and record it.

One task per file (Regelungstext or an Anlage) — a failed download retries
without re-parsing the entry page. The download uses the page's href
verbatim; ``source_url`` for the ledger is the official ELI direct form
with the transient ``&v=N`` version parameter stripped (deterministic,
rebuildable, and on a different domain than the bgbl source so doc_ids
never collide).
"""

from __future__ import annotations

from urllib.parse import quote

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.deu.sources.ebgbl import BASE_URL, USER_AGENT
from adapters.deu.sources.ebgbl.entry import entry_folder, to_iso_date
from core.document import DocumentRecord, compute_doc_id

__all__ = ["EbgblPdfHandler", "canonical_source_url", "map_doc_type"]

#: Official Typ vocabulary → the cross-country soft enum (kor precedent:
#: map what is known, keep the German word verbatim in meta.typ).
_TYPE_MAP: dict[str, str] = {
    "Gesetz": "STATUTE",
    "Verordnung": "REGULATION",
}

_ELI_PART = {"1": "BGBl-1", "2": "BGBl-2"}
_PART_ROMAN = {"1": "I", "2": "II"}


def map_doc_type(typ: str) -> str:
    return _TYPE_MAP.get(typ, "OTHER")


def canonical_source_url(part: str, year: int | str, nr: str, file_kind: str) -> str:
    """``…/eli/bund/BGBl-1/2023/1/regelungstext.pdf?__blob=publicationFile``."""
    return (
        f"{BASE_URL}/eli/bund/{_ELI_PART[part]}/{year}/{nr}/"
        f"{quote(file_kind)}.pdf?__blob=publicationFile"
    )


class EbgblPdfHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        href = str(task.params["href"])
        url = href if href.startswith("http") else BASE_URL + href
        return RequestSpec(url=url, headers={"User-Agent": USER_AGENT})

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = dict(task.params)
        content = response.content
        if not content.startswith(b"%PDF-"):
            raise ValueError(
                f"expected a PDF for {params['year']}/{params['nr']}/{params['file_kind']}, "
                f"got {content[:40]!r} (HTTP {response.status_code})"
            )

        part = str(params["part"])
        file_kind = str(params["file_kind"])
        publication_date = str(params["publication_date"])
        source_url = canonical_source_url(part, params["year"], str(params["nr"]), file_kind)
        doc_id = compute_doc_id("DEU", source_url, publication_date)

        raw_metadata: dict[str, str] = {
            "part": _PART_ROMAN[part],
            "year": str(params["year"]),
            "nr": str(params["nr"]),
            "eli": f"{BASE_URL}/eli/bund/{_ELI_PART[part]}/{params['year']}/{params['nr']}",
            "citation": str(params["citation"]),
            "typ": str(params["typ"]),
            "file_kind": file_kind,
        }
        for key in ("ausfertigungsdatum", "federfuehrung", "sachgebiete", "fna", "gesta"):
            value = params.get(key)
            if value:
                if key == "ausfertigungsdatum":
                    value = to_iso_date(str(value))
                raw_metadata[key] = str(value)

        record = DocumentRecord(
            title=str(params["title"]),
            source_url=source_url,
            publication_date=publication_date,
            issuing_authority=(str(params["federfuehrung"]) if params.get("federfuehrung") else None),
            doc_type=map_doc_type(str(params["typ"])),
            language="deu",
            raw_metadata=raw_metadata,
        )
        file_path = f"{entry_folder(part, params['year'], str(params['nr']))}/{file_kind}.pdf"
        return TaskResult(
            documents=[record],
            files=[FileOut(path=file_path, content=content, doc_id=doc_id)],
        )
