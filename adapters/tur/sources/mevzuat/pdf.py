"""Task type ``mev_pdf``: the file-only entity's text PDF.

Every record whose Datatable row carries ``fileType=2`` has **no iframe
text** — the consolidated body exists only as the ``/MevzuatMetin/
{tur}.{tertip}.{no}.pdf`` file (probed 2026-09-28: the whole CB Kararı
corpus, tur 20 / 4,321 records, answers the iframe endpoint with an
empty page and links the PDF from the detail page). For those entities
the PDF is not a redundant rendering but the only text, so the catalogue
seeds them here instead of :mod:`metin` — the user-ruled "no pdf where
the iframe text exists" (2026-09-28, Q4) is untouched.

The bytes are stored verbatim as the document's primary file
``metin.pdf``; bibliographic fields all come from the seed (a PDF has no
machine-readable header). The **magic check is mandatory**: the file
endpoint answers missing numbers with HTTP 200 + an HTML error page
(probed 2026-09-27), so a non-``%PDF-`` body fails loudly instead of
silently archiving an error page as legislation.
"""

from __future__ import annotations

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.tur.sources.mevzuat import API_BASE
from adapters.tur.sources.mevzuat.metin import map_doc_type
from core.document import DocumentRecord, compute_doc_id

__all__ = ["MevPdfHandler"]

_PDF_MAGIC = b"%PDF-"


class MevPdfHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        tur = int(task.params["tur"])
        no = str(task.params["no"])
        tertip = int(task.params["tertip"])
        return RequestSpec(url=f"{API_BASE}/MevzuatMetin/{tur}.{tertip}.{no}.pdf")

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = task.params
        tur = int(params["tur"])
        no = str(params["no"])
        tertip = int(params["tertip"])
        adi = str(params["adi"])
        seed_rg = str(params["rg_tarihi"]) if params.get("rg_tarihi") else None

        if not response.content.startswith(_PDF_MAGIC):
            raise ValueError(
                f"mev_pdf tur={tur} no={no}: body is not a PDF "
                f"(magic={response.content[:8]!r}, {len(response.content)} bytes) "
                "— the file endpoint answers unknown numbers with an HTML page"
            )

        meta: dict[str, str] = {
            "mevzuat_tur": str(tur),
            "mevzuat_tertip": str(tertip),
            "text_channel": "file",
        }
        meta["pdf_url"] = f"{API_BASE}/MevzuatMetin/{tur}.{tertip}.{no}.pdf"
        meta["doc_url"] = f"{API_BASE}/MevzuatMetin/{tur}.{tertip}.{no}.doc"
        meta["files"] = "metin.pdf"

        path = f"01_raw/mevzuat/{tur}/{no}/metin.pdf"
        source_url = f"{API_BASE}/mevzuat?MevzuatNo={no}&MevzuatTur={tur}&MevzuatTertip={tertip}"
        document = DocumentRecord(
            title=adi,
            source_url=source_url,
            publication_date=seed_rg,
            doc_type=map_doc_type(tur),
            language="tur",
            entity_ref=f"mevzuat:{tur}:{no}:{tertip}",
            raw_metadata=meta,
        )
        doc_id = compute_doc_id("TUR", source_url, seed_rg)
        return TaskResult(
            documents=[document],
            files=[FileOut(path=path, content=response.content, doc_id=doc_id)],
        )
