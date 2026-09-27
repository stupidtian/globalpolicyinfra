"""Task type ``lawgokr_clean``: strip one collected document to plain text.

Reads the stored HTML via ``RequestSpec.local_doc`` (no network) and applies
the per-kind container rules probed 2026-09-19 across 30 samples × 5 decades
(docs/tasks/2026-08-28-kor/clean-probe/ — shapes stable since the 1960s):

===============  =====================================================
kind             keep / drop / drop_strings
===============  =====================================================
kor_body         keep ``#conTop, .cont_subtit, div.pgroup`` (law name
                 + promulgation line, ministry, article groups);
                 drop the blue ※ notice paragraph (``p.gtit``) and
                 the per-article icon lists (``ul.lawico01``)
kor_reason       keep ``#rvsConTop, #rvsConBody`` (title + reason body)
===============  =====================================================

Both kinds: the framework drops scripts/styles/hidden inputs/HTML comments
unconditionally; a zero ``keep`` match (shape mutation) raises ValueError,
converted to PermanentError here — loud, never silent.
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

__all__ = ["RULES", "LawgokrCleanHandler"]

CLEAN_VERSION = 1

_HINT_LINE = (
    "※ 본 법령은 공포 후 시행전 개정된 사항을 모두 포함한 법령이며, "
    "개별 시행일별로 공포된 내용은 상단 메뉴의 '연혁' 또는 조문 앞의 '' "
    "아이콘을 통해 확인할 수 있습니다."
)

#: kind → (keep, drop, drop_strings); kind = the producing task type name.
RULES: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "kor_body": (
        "#conTop, .cont_subtit, div.pgroup",
        ("p.gtit", "ul.lawico01"),
        (_HINT_LINE,),
    ),
    "kor_reason": ("#rvsConTop, #rvsConBody", (), ()),
}


class LawgokrCleanHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(local_doc=str(task.params["doc_id"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        kind = str(task.params["kind"])
        rule = RULES.get(kind)
        if rule is None:
            raise PermanentError(
                f"lawgokr_clean has no container rules for kind {kind!r}"
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
