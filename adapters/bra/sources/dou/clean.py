"""Task type ``dou_clean``: one document -> deterministic plain text.

Every document carries exactly one full-text carrier (probed 2026-10-19,
300-doc whole-corpus survey in the task folder's clean-probe/): the
server-rendered article page, stored as ``doc.html.gz``. The page's
``<article id="materia">`` container holds the entry's as-published text
(``div.texto-dou`` plus the ``p.assina`` signature block, which is the
container's *sibling* outside the text div) surrounded by four pieces of
page furniture, each with its own stable class and dropped whole:

- ``.cabecalho-dou`` — the republic's coat-of-arms placeholder and the
  "Diário Oficial da União" masthead;
- ``.detalhes-dou`` — the ``Publicado em / Edição / Seção / Página /
  Órgão`` line: pure metadata, the ledger already carries every field;
- ``.informacao-conteudo-dou`` — the legal notice "Este conteúdo não
  substitui o publicado na versão certificada.";
- ``.rodape-dou`` — footer decoration (``Borda do rodapé`` /
  ``Logo da Imprensa`` image alt-texts).

A zero ``keep`` match raises PermanentError — loud, never silent (shape
mutation must fail loudly; hit rate probed 400/400 + 300/300 across
2013-2025). Rendered-empty output is an explained empty, not a fault.

Two era-bound source defects survive cleaning by design and are recorded
in the country notes (§8), not repaired here: 2013-2017 pages carry
scattered source-side missing spaces (PDF→HTML conversion artifact), and
old-era tables (2013-2017, ~3% of documents) are server-rendered images
with no text layer, so their content stays a hole in the cleaned text.
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

__all__ = ["CLEAN_VERSION", "DouCleanHandler"]

CLEAN_VERSION = 1

#: The as-published text container and the furniture dropped inside it
#: (classes probed stable across 2013-2025; clean-plan.md §1).
_KEEP = "#materia"
_DROP = (
    ".cabecalho-dou",
    ".detalhes-dou",
    ".informacao-conteudo-dou",
    ".rodape-dou",
)


class DouCleanHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(local_doc=str(task.params["doc_id"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        doc_id = str(task.params["doc_id"])
        # A handful of source pages embed UTF-8 BOM sequences inside the
        # markup (probed 2026-10-20: one 2022 page carries 11, one lands as
        # the first character of the rendered text). U+FEFF is a byte-order
        # signature, never Portuguese content — strip it before rendering so
        # the output meets the engine's determinism contract (run 1: the
        # unstripped BOM was correctly refused as a contract violation).
        content = response.content.replace(b"\xef\xbb\xbf", b"")
        if not content.strip():
            raise PermanentError(f"clean {doc_id}: stored file is empty")
        try:
            text = html_to_text(content, keep=_KEEP, drop=_DROP)
        except ValueError as exc:
            raise PermanentError(f"clean {doc_id}: {exc}") from exc
        if not text.strip():
            return TaskResult(
                expected_empty=(
                    f"clean {doc_id}: article container carries no text "
                    "(image-only rendition, no text layer on the source)"
                )
            )
        return TaskResult(
            cleaned=[
                CleanedRecord(
                    doc_id=doc_id, version=CLEAN_VERSION, content=text.encode("utf-8")
                )
            ]
        )
