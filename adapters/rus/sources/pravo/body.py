"""Task type ``pravo_body``: one document's text, one request, one document.

GET ``redtext`` for the initial (as-published) redaction. The bank
answers ``{"redtext": "<!DOCTYPE html>…", "error": ""}`` — a Word-export
HTML document whose head carries Office namespaces and a large CSS block
(a 25 KB document is roughly half decoration) and whose body is a flat
run of ``<p>`` paragraphs. The HTML string itself — not the JSON
envelope — is stored verbatim as the primary file, so the cleaned layer
reads it with the plain html engine (``keep="body"``, probed clean
2026-10-12: 25,485 B -> 3,227 chars, zero CSS leakage, deterministic).

Document identity stays anchored to the official publication: the
``source_url`` is the publication portal's document page and the
``doc_id`` derives from it — the text bank only supplies the artifact.
Should the bank ever disappear, a PDF leg can be added later without
touching identity.
"""

from __future__ import annotations

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.rus.sources.pravo import BANK_API, PORTAL_BASE
from core.document import DocumentRecord, compute_doc_id
from runtime.errors import PermanentError, TransientError

__all__ = ["PravoBodyHandler"]


class PravoBodyHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=f"{BANK_API}/redtext",
            params={
                "bpa": "ebpi",
                "t": str(task.params["redid"]),
                "ttl": "2",
            },
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        pnum = str(task.params["номер"])
        if response.status_code >= 500:
            raise TransientError(
                f"pravo_body {pnum}: text-bank answered HTTP "
                f"{response.status_code} (test-mode system flake)"
            )
        if response.status_code != 200:
            raise PermanentError(
                f"pravo_body {pnum}: unexpected HTTP {response.status_code}"
            )
        payload = response.json()

        error = str(payload.get("error") or "")
        html = payload.get("redtext")
        if error:
            raise PermanentError(f"pravo_body {pnum}: bank refused: {error}")
        if not isinstance(html, str) or "<html" not in html[:4000].lower():
            raise ValueError(
                f"pravo_body {pnum}: redtext is not an HTML document "
                "— envelope shape mutated"
            )

        pub_date = str(task.params["pub_date"])
        ymd = pub_date.replace("-", "")
        source_url = f"{PORTAL_BASE}/document/{pnum}"

        meta: dict[str, str] = {"номер": pnum, "files": "text.html"}
        for key in (
            "doc_number",
            "doc_date",
            "pdf_pages",
            "scope",
            "docid",
            "redid",
            "ebpi_docstate",
            "ebpi_versions",
        ):
            bank_key = "ebpi_docid" if key == "docid" else key
            value = str(task.params.get(key, ""))
            if value:
                meta[bank_key] = value

        document = DocumentRecord(
            title=str(task.params["title"]),
            source_url=source_url,
            publication_date=pub_date,
            issuing_authority=str(task.params["issuing_authority"])
            if str(task.params.get("issuing_authority", ""))
            else None,
            doc_type=str(task.params.get("doc_type", "OTHER")) or "OTHER",
            language="rus",
            raw_metadata=meta,
        )
        doc_id = compute_doc_id("RUS", source_url, pub_date)
        path = f"01_raw/pravo/{ymd[:4]}/D{ymd}/{pnum}/text.html"

        return TaskResult(
            documents=[document],
            files=[
                FileOut(
                    path=path,
                    content=html.encode("utf-8"),
                    doc_id=doc_id,
                )
            ],
        )
