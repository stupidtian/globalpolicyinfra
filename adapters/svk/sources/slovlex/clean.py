"""Task type ``slovlex_clean``: strip one collected page to plain text.

Reads the stored HTML via ``RequestSpec.local_doc`` (no network) and
applies the container rules probed 2026-10-03 across 28 samples spanning
2000–2025 × both document families (docs/tasks/2026-09-03-svk/clean-probe/).
The whole corpus is one site template: the body lives in ``#content``,
everything else is portal chrome.

===============  =====================================================
rule             value
===============  =====================================================
keep             ``#content`` (28/28 samples; ~98% of page words)
drop             ``#Historia`` (version-navigation table — the timeline
                 already lives in meta.historia), ``.historia-table``,
                 ``.tooltip-sidebar-buttons``, ``.sidebar-buttons``,
                 ``.ucinnost_header`` (version banner "Vyhlásené
                 znenie"/"Časová verzia…" — the version identity is
                 already in doc_id/verzia)
drop_strings     the informative-character notices (both the two-sentence
                 and legacy one-sentence variants) and the expand/
                 collapse buttons ("Otvoriť všetky"/"Zavrieť všetky")
===============  =====================================================

Kept on purpose: the InfoTable metadata rows (number/title/type/dates/
authority — Slovak originals), the relation panel (amendment references),
the attachment list ("Obsah", "Príloha…") and the full text.

Probe finding baked into the drop list: the version-table container is
``#Historia`` with a capital H — the lowercase selector does not match
(css selectors are case-sensitive), which shipped in the test suite.
The 57 PDFs in the corpus are sibling files (meta.files), not document
main files — no pdf_rules, nothing PDF-shaped ever reaches this handler.
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

__all__ = ["CLEAN_VERSION", "RULES", "SlovlexCleanHandler"]

CLEAN_VERSION = 1

_KEEP = "#content"

_DROP = (
    "#Historia",
    ".historia-table",
    ".tooltip-sidebar-buttons",
    ".sidebar-buttons",
    ".ucinnost_header",
)

_DROP_STRINGS = (
    # informative-character notices (current two-sentence + legacy one-line)
    ("Obsah zobrazeného právneho predpisu má informatívny charakter, "
     "právne záväzný obsah sa nachádza v pdf verzii právneho predpisu."),
    "Obsah zobrazeného právneho predpisu má informatívny charakter.",
    # expand/collapse UI buttons
    "Otvoriť všetky",
    "Zavrieť všetky",
)

#: One rule for the whole corpus — event pages (vyhlasene_znenie alias)
#: and dated version pages share the template (probed 28/28). Keyed by
#: kind (= the producing task type) for the framework's seeding contract.
RULES: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "svk_doc": (_KEEP, _DROP, _DROP_STRINGS),
}


class SlovlexCleanHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(local_doc=str(task.params["doc_id"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        kind = str(task.params["kind"])
        rule = RULES.get(kind)
        if rule is None:
            raise PermanentError(
                f"slovlex_clean has no container rules for kind {kind!r}"
            )
        keep, drop, drop_strings = rule
        try:
            text = html_to_text(
                response.content, keep=keep, drop=drop, drop_strings=drop_strings
            )
        except ValueError as exc:
            raise PermanentError(f"{task.params['doc_id']}: {exc}") from exc
        record = CleanedRecord(
            doc_id=str(task.params["doc_id"]),
            version=CLEAN_VERSION,
            content=text.encode("utf-8"),
        )
        return TaskResult(cleaned=[record])
