"""Task type ``gongbao_clean``: strip one collected article to plain text.

Reads the stored HTML via ``RequestSpec.local_doc`` (no network) and keeps
the single probed body container — ``#UCAP-CONTENT`` (probed 2026-10-02 on
both page generations: decree, ministerial rule, office notification, and a
2000-era CPC document all inline their full text there; the surrounding
page is site furniture — search boxes, related-article lists, footer).

The framework drops scripts/styles/hidden inputs/HTML comments
unconditionally; a zero ``keep`` match (shape mutation) raises ValueError,
converted to PermanentError here — loud, never silent.

Output discipline for the first simplified-Chinese corpus: the text is
kept character-faithful — full-width punctuation preserved, no word
segmentation, no punctuation rewriting (determinism beats prettiness).
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

__all__ = ["CLEAN_VERSION", "GongbaoCleanHandler"]

CLEAN_VERSION = 1

_KEEP = "#UCAP-CONTENT"


class GongbaoCleanHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(local_doc=str(task.params["doc_id"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        try:
            text = html_to_text(response.content, keep=_KEEP)
        except ValueError as exc:
            raise PermanentError(f"{task.params['doc_id']}: {exc}") from exc
        if not text.strip():
            # Probed live (2026-10-03, 财政部 PPP 通知 2017 年第 64 号): a few
            # gazette articles publish their body as a full-page image (scan)
            # inside the container — no machine text exists at the source.
            raise PermanentError(
                f"{task.params['doc_id']}: article body carries no text "
                "(image-only page; OCR is out of scope)"
            )
        record = CleanedRecord(
            doc_id=str(task.params["doc_id"]),
            version=CLEAN_VERSION,
            content=text.encode("utf-8"),
        )
        return TaskResult(cleaned=[record])
