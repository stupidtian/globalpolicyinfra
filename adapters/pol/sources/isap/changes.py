"""Task type ``isap_changes``: one page of the ELI change feed.

``GET /eli/changes/acts?since={cursor}&limit=100[&offset=N]`` — every act
whose data changed since ``since``, sorted by changeDate (probed
2026-09-20: the bare request answers 403; with ``since`` it answers 200 —
the paramless rejection is a load-balancer rule, not an auth wall).
Rows are full act-info shapes; DU rows spawn one isap_act each with
signal = changeDate, so a done act task reopens only when the source
changed it again (section 6.5). MP rows are consumed but not collected.

Pagination: a page holding ``limit`` rows chains the next offset (a ROW
offset in the API — probed live 2026-09-21, paging by page number walks
one row per request); the terminal page (fewer than ``limit`` rows,
including an empty one) advances the kv cursor ``isap_last_change`` to the
sweep watermark — the greatest changeDate seen across the whole sweep,
carried forward in ``prev_max`` because only the terminal page learns it
is terminal. The cursor is the feed-position watermark, so it advances
past MP rows too. An inclusive ``since`` at worst re-reports the boundary
item; the act task's done-skip absorbs that.
"""

from __future__ import annotations

from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.pol.sources.isap import CHANGES_PAGE_LIMIT, CURSOR_KEY, ELI_BASE, PUBLISHER

__all__ = ["IsapChangesHandler"]


class IsapChangesHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        params: dict[str, Any] = {
            "since": str(task.params["since"]),
            "limit": CHANGES_PAGE_LIMIT,
        }
        offset = int(task.params.get("offset", "0"))
        if offset:
            params["offset"] = offset
        return RequestSpec(url=f"{ELI_BASE}/changes/acts", params=params)

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        since = str(task.params["since"])
        prev_max = str(task.params.get("prev_max", "")) or since
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(f"isap_changes since={since}: body is not JSON: {exc}") from exc
        items = payload.get("items")
        if not isinstance(items, list) or "count" not in payload:
            raise ValueError(
                f"isap_changes since={since}: unexpected response shape "
                f"(keys={sorted(payload)!r}) — the change feed may have moved"
            )

        seeds: list[TaskSeed] = []
        watermark = prev_max
        for item in items:
            change_date = str(item.get("changeDate") or "")
            if not change_date:
                raise ValueError(
                    f"isap_changes since={since}: row without changeDate "
                    f"({item.get('displayAddress')!r}) — row shape may have changed"
                )
            watermark = max(watermark, change_date)
            if str(item.get("publisher") or "") != PUBLISHER:
                continue
            year, pos = item.get("year"), item.get("pos")
            if year is None or pos is None:
                raise ValueError(
                    f"isap_changes since={since}: DU row without year/pos "
                    f"({item.get('displayAddress')!r})"
                )
            seeds.append(
                TaskSeed(
                    type="isap_act",
                    params={
                        "publisher": PUBLISHER,
                        "year": str(int(year)),
                        "pos": str(int(pos)),
                    },
                    signal=change_date,
                )
            )

        result = TaskResult(next_tasks=seeds)
        if len(items) < CHANGES_PAGE_LIMIT:
            result.cursor_updates = {CURSOR_KEY: watermark}
            if not seeds:
                result.expected_empty = (
                    f"isap_changes since={since}: change feed exhausted "
                    f"({len(items)} row(s) total, none from {PUBLISHER})"
                    if items
                    else f"isap_changes since={since}: no changes to replay"
                )
        else:
            # ``offset`` is a ROW offset in the API (probed): advance by the
            # rows this page consumed — paging by page number would replay
            # an almost-full window each round (first seen live 2026-09-21:
            # a 223-row feed walked one row per request).
            consumed = int(task.params.get("offset", "0")) + len(items)
            result.next_tasks.append(
                TaskSeed(
                    type="isap_changes",
                    params={"since": since, "offset": str(consumed),
                            "prev_max": watermark},
                )
            )
        return result
