"""Task type ``uradnilist_clean``: strip one collected act to plain text.

Reads the stored file via ``RequestSpec.local_doc`` (no network) and
sniffs the carrier by magic bytes — this corpus is mixed-carrier by
design (the ISL precedent), so the clean task targets the *registering*
task type (``ul_date``) and routes by content:

- HTML (the pre-ZOUL archival page, the primary carrier): whitelist
  container rule probed 2026-10-12 across 2000-2025 sample pages (state
  and municipal) — the act's published text lives in a single
  ``div#divSection`` and every decoration (search area, basket/login
  chrome, e-news signup, footer) sits OUTSIDE it. A pure whitelist, no
  drop rules (decoration is dynamic; the whitelist is the stable thing
  — the LVA precedent).
- PDF (the post-ZOUL primary carrier): explained empty — PDF-text
  extraction is the geometry channel's business, a separate country
  subtask (JPN/ISL precedent); ``expected_empty`` marks the task done
  so the seeding skips it from then on.

The act text is self-contained: the published act opens with its own
official header ("Na podlagi … člena Ustave … izdajam", "UKAZ o
razglasitvi …") and closes with the signature lines; issuer/publish-date
metadata is outside the container and lives in the ledger.

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

__all__ = ["CLEAN_VERSION", "KEEP_SELECTOR", "UradnilistCleanHandler"]

CLEAN_VERSION = 2
#: v1→v2 (2026-10-15): the cleanable-carrier definition changed — the
#: first collected documents (the 1991-01-18 probe window) originally
#: carried the whole-issue PDF as their primary file and answered
#: explained-empty at v1; the archival HTML carrier conversion re-pointed
#: their local_path at cleanable pages, and the version bump is the
#: parameterized-reopen channel that re-seeds them (§6.5 refresh family).

#: The act body container — single whitelist, all pre-ZOUL page shapes.
KEEP_SELECTOR = "div#divSection"

_PDF_MAGIC = b"%PDF-"


class UradnilistCleanHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(local_doc=str(task.params["doc_id"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        doc_id = str(task.params["doc_id"])
        if str(task.params["kind"]) != "ul_date":
            raise PermanentError(
                f"uradnilist_clean has no container rules for kind "
                f"{task.params['kind']!r}"
            )
        if response.content.startswith(_PDF_MAGIC):
            return TaskResult(
                expected_empty=(
                    f"{doc_id}: post-ZOUL act whose primary carrier is the "
                    "as-published PDF — plain text is the PDF cleaning "
                    "subtask's business, not the HTML whitelist"
                )
            )
        try:
            text = html_to_text(response.content, keep=KEEP_SELECTOR)
        except ValueError as exc:
            raise PermanentError(f"{doc_id}: {exc}") from exc
        record = CleanedRecord(
            doc_id=doc_id,
            version=CLEAN_VERSION,
            content=text.encode("utf-8"),
        )
        return TaskResult(cleaned=[record])
