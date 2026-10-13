"""Task type ``lovtidende_clean``: one gazette entry -> deterministic plain text.

Reads the stored file via ``RequestSpec.local_doc`` (no network) and routes
**by content, not by filename**: every corpus file is named ``doc.xml`` but
carries Lovdata's rendered HTML (``<!DOCTYPE html><html lang="…">``) — a
full-library census of all 39,143 files (2026-10-05, docs/tasks/
2026-09-03-nor/clean-probe/) routes 100% to ``detect_format() == 'html'``
and zero to xml/pdf/epub/unknown. The sniff therefore stays in the handler
as the task brief's loud guard: anything but HTML is a PermanentError that
names the measured format, never a silent detour into the XML engine.

The body rule is a pure whitelist (LVA-style minimal face; every number
below is a corpus census, not a sample): the document body is the single
``main.documentBody`` element — present in all 39,143 files, empty in
none — and the body has exactly two children (``header.documentHeader``
with the metadata definition list and the table of contents, then
``main``; nothing after it). Everything inside ``main`` is legal content
(class vocabulary: legalP / section / listArticle / footnotes /
gazettenote… — zero UI classes), so there are no drop selectors and no
drop_strings. Footnotes and gazette notes carry legal citations and stay
(user ruling 2026-10-05, clean-plan Q1).

Signatures for tests: the rendered text opens with the document title
(the ``h1``) and closes with the entry-into-force line ("…trer i kraft…")
or the signature block of a large act; the header's UI labels (Datokode /
DokumentID / RefID / Rettsområde) never appear inside ``main`` (corpus
census, zero hits) and must be absent from the output.

An empty render is a PermanentError (user ruling clean-plan Q3: the
corpus has no no-full-text marker shape — DNK's explained-empty branch
does not apply here; an empty body would be a shape mutation).
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
from runtime.stages.cleaning import detect_format, html_to_text

__all__ = ["CLEAN_VERSION", "KEEP_SELECTOR", "LovtidendeCleanHandler"]

CLEAN_VERSION = 1

#: The gazette body container — single whitelist, every era and both
#: document families (lov/forskrift use the same container).
KEEP_SELECTOR = "main.documentBody"


class LovtidendeCleanHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(local_doc=str(task.params["doc_id"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        doc_id = str(task.params["doc_id"])
        kind = str(task.params.get("kind", ""))
        if kind != "lt_pack":
            raise PermanentError(
                f"lovtidende_clean has no container rules for kind {kind!r}"
            )

        fmt = detect_format(response.content)
        if fmt != "html":
            raise PermanentError(
                f"{doc_id}: stored bytes sniff as {fmt!r}, not html — "
                "the corpus is 100% HTML (2026-10-05 census); any other "
                "format is a shape mutation to classify by hand"
            )

        try:
            text = html_to_text(response.content, keep=KEEP_SELECTOR)
        except ValueError as exc:
            raise PermanentError(f"{doc_id}: {exc}") from exc
        if not text.strip():
            raise PermanentError(
                f"{doc_id}: {KEEP_SELECTOR} rendered to empty text — shape "
                "mutation (corpus census: zero empty containers)"
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
