"""Task type ``kor_hist_list``: one page of the historical-corpus list (연혁법령).

The historical corpus (연혁, ~3,298 pages × 50 rows ≈ 165k version rows) is
the *discovery layer for repealed laws*: a law repealed in, say, 2008 is
absent from the current list, but every version it ever had lives here.

Same row shape and anchor logic as the current list (KorListHandler.parse,
inherited verbatim) — the corpus difference is entirely in the request:
probed 2026-08-31, the 연혁 corpus is selected by the menu query string
(menuId=1&subMenuId=17&tabMenuId=93) plus a *minimal* form (q/outmax/pg).
The full current-corpus form overrides the corpus server-side, which is why
early probes concluded the menu parameters were ignored.

Discovery value (phase 2, user-approved 2026-09-17): versions already
fetched by the current-law pass (their histories included) dedup by task_id,
so a full walk re-fetches only the repealed laws' versions.
"""

from __future__ import annotations

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.kor.sources.lawgokr import BASE_URL, xhr_headers
from adapters.kor.sources.lawgokr.list import KorListHandler

__all__ = ["KorHistListHandler"]

_HIST_REFERER = f"{BASE_URL}/lsSc.do?menuId=1&subMenuId=17&tabMenuId=93"


class KorHistListHandler(KorListHandler):
    _SPAWN_TYPE = "kor_hist_list"

    def build_request(self, task: TaskView) -> RequestSpec:
        # Minimal form + 연혁 query string: the probed corpus selector. The
        # full current-corpus form would override the corpus back to 현행.
        return RequestSpec(
            url=f"{BASE_URL}/lsScListR.do?menuId=1&subMenuId=17&tabMenuId=93",
            params={"q": "*", "outmax": "50", "pg": str(int(task.params["pg"]))},
            headers=xhr_headers(_HIST_REFERER),
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        # Anchor semantics differ from the current corpus: every discovery
        # here is a historical version of a (mostly repealed) law, and the
        # site legitimately refuses to serve some of them. Bodies spawn
        # tagged ``from_versions`` — the SAME tag phase 1's timeline spawns
        # used, so current laws' rows on these pages dedup by task_id
        # (a from_hist tag would create a third identity and refetch
        # ~120k versions). The tag also routes unserved shapes to the
        # graceful skip in body.parse.
        result = super().parse(response, task)
        result.next_tasks = [
            TaskSeed(
                type=seed.type,
                params={**seed.params, "from_versions": True} if seed.type == "kor_body" else seed.params,
                signal=seed.signal,
            )
            for seed in result.next_tasks
        ]
        # Research window (user ruling 2026-09-18): the repealed-law walk
        # covers 1949-2026, but only versions effective in the window matter
        # (``min_ef``, e.g. 20000101). Server-side sort is unreliable, so the
        # filter is client-side: out-of-window rows are never fetched; the
        # page walk itself continues (row order is not chronological).
        min_ef = str(task.params.get("min_ef", ""))
        if min_ef:
            in_window = [
                seed for seed in result.next_tasks
                if seed.type != "kor_body" or seed.params.get("ef_yd", "") >= min_ef
            ]
            skipped = len(result.next_tasks) - len(in_window)
            result.next_tasks = in_window
            if not result.next_tasks and not result.expected_empty:
                result.expected_empty = (
                    f"list page {task.params['pg']}: all {skipped} rows outside the "
                    f"window (efYd < {min_ef})"
                )
        return result
