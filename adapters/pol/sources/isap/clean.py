"""Task type ``isap_clean``: strip one collected HTML text to plain text.

Reads the stored ``text.html`` via ``RequestSpec.local_doc`` (no network)
and converts it with the framework's deterministic extractor. The ELI HTML
is a bare document body — h1 (head-type/head-date), h2 part headings,
article structure, no site chrome — so the whitelist container is simply
``body`` (single match; zero matches would mean a shape change and fail
loudly). One UI leftover rides in the source HTML and is dropped by line:
"Pokaż całość" (an expand-control caption at the body end, first seen on
the real DU/2024/1 text). Only HTML carriers are cleanable: the clean
declaration targets ``isap_act`` exclusively (PDF-primary documents are
out of cleaning scope until OCR is decided). Polish diacritics ride
through as UTF-8.
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

__all__ = ["CLEAN_VERSION", "IsapCleanHandler"]

CLEAN_VERSION = 1

_DROP_LINES = ("Pokaż całość",)


class IsapCleanHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(local_doc=str(task.params["doc_id"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        kind = str(task.params["kind"])
        if kind != "isap_act":
            raise PermanentError(
                f"isap_clean has no container rules for kind {kind!r} "
                "(only HTML texts are cleanable)"
            )
        try:
            text = html_to_text(response.content, keep="body", drop_strings=_DROP_LINES)
        except ValueError as exc:
            raise PermanentError(f"{task.params['doc_id']}: {exc}") from exc
        record = CleanedRecord(
            doc_id=str(task.params["doc_id"]),
            version=CLEAN_VERSION,
            content=text.encode("utf-8"),
        )
        return TaskResult(cleaned=[record])
