"""Task type ``pravo_clean``: one text.html -> deterministic plain text.

Single-carrier corpus (the legal-text bank's Word-exported HTML):
``<html>`` with an Office-namespaced head and a large CSS block, body a
flat run of ``<p>`` paragraphs (heading classes C/T/Z/I/H are styling
only — the words themselves are ordinary text), inline ``<span>``
carrying superscripts and cross-reference links whose text belongs to
the sentence. The whitelist ``keep="body"`` is the whole rule (probed on
the 2012-02-29 federal law sample, 2026-10-12: 25,485 B -> 3,227 chars,
signature block intact, zero CSS leakage, byte-for-byte deterministic).

An empty extraction is a shape mutation and dies loudly — a bank-missed
document never reaches this handler (pravo_text already screened it).
"""

from __future__ import annotations

from adapters.base import (
    CleanedRecord,
    RequestSpec,
    Response,
    TaskResult,
    TaskView,
)
from runtime.errors import PermanentError
from runtime.stages.cleaning import html_to_text

__all__ = ["CLEAN_VERSION", "PravoCleanHandler"]

CLEAN_VERSION = 1


class PravoCleanHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(local_doc=str(task.params["doc_id"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        doc_id = str(task.params["doc_id"])
        try:
            text = html_to_text(response.content, keep="body")
        except ValueError as exc:
            raise PermanentError(
                f"pravo_clean {doc_id}: shape mutation — {exc}"
            ) from exc
        if not text.strip():
            raise PermanentError(
                f"pravo_clean {doc_id}: extraction produced no text "
                "(empty body — never legitimate for bank-delivered HTML)"
            )
        return TaskResult(
            cleaned=[
                CleanedRecord(
                    doc_id=doc_id,
                    version=CLEAN_VERSION,
                    content=text.encode("utf-8"),
                )
            ]
        )
