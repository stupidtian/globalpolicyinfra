"""Task type ``vestnesis_clean``: strip one collected gazette page to plain text.

Reads the stored page via ``RequestSpec.local_doc`` (no network; the engine
decompresses ``.gz`` automatically) and applies the container rule probed
2026-09-19 across 10 era/type samples plus a 200-page random sweep
(docs/tasks/2026-09-14-lva/clean-probe/): the gazette body lives in a single
``div.docContent`` on both page generations (legacy direct pages and /op/
redirect targets), and every decoration — the search area with its issuer
dropdown, the cross-link block, the citation popup, the issuer lists, the
footer motto, the date-navigation sidebar that grows with every issue —
sits OUTSIDE that container. The rule is therefore a pure whitelist: no
drop selectors, no drop_strings (decoration is dynamic; the whitelist is
the stable thing).

The bibliographic block (``div.taPase``, "PAR DOKUMENTU") is also outside
the container: issuer/adoption/OP metadata lives in the ledger. The text
stays self-contained anyway — the published act opens with its own official
header ("Ministru kabineta rīkojums Nr. 616", "Saeima ir pieņēmusi un
Valsts prezidents izsludina šādu likumu:", "Precizējot iepriekš publicēto")
and closes with the signature lines, and those are part of the gazette body.

A zero ``keep`` match (shape mutation) raises ValueError, converted to
PermanentError here — loud, never silent.
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

__all__ = ["CLEAN_VERSION", "KEEP_SELECTOR", "VestnesisCleanHandler"]

CLEAN_VERSION = 1

#: The gazette body container — single whitelist, both page generations.
KEEP_SELECTOR = "div.docContent"


class VestnesisCleanHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(local_doc=str(task.params["doc_id"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        kind = str(task.params["kind"])
        if kind != "vestnesis_doc":
            raise PermanentError(
                f"vestnesis_clean has no container rules for kind {kind!r}"
            )
        try:
            text = html_to_text(response.content, keep=KEEP_SELECTOR)
        except ValueError as exc:
            raise PermanentError(f"{task.params['doc_id']}: {exc}") from exc
        record = CleanedRecord(
            doc_id=str(task.params["doc_id"]),
            version=CLEAN_VERSION,
            content=text.encode("utf-8"),
        )
        return TaskResult(cleaned=[record])
