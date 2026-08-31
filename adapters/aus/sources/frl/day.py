"""Task type ``frl_day``: one registration day of the register's event feed.

``/Versions?$filter=registeredAt ge {day}T00:00:00 and le {day}T23:59:59``
returns every version event of that calendar day — new titles (their
as-made registration), fresh compilations of existing titles and
uncompiled amendment markers alike, which is why this one feed drives all
incremental updates (probed 2026-08-25..30: 19–33 events on weekdays, 0
on a Saturday, 1 on a Sunday).

Each distinct titleId yields one ``frl_title`` seeded with the title's
newest registeredAt as its signal (second precision — the store compares
signals as strings). A full page of 100 chains to the next ``$skip``;
the *last* page of the day — the only task that saw fewer than 100 rows
— is the one that advances the date cursor, so a crash mid-chain never
skips a half-consumed day. ``max_titles`` caps deep-fetch spawns per day
but not enumeration: the discovery chain still runs to its end, so the
cursor still reflects a fully swept day.
"""

from __future__ import annotations

from typing import Any

from adapters.aus.sources.frl import CURSOR_KEY, PAGE_SIZE, odata_url
from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView

__all__ = ["FrlDayHandler"]


def _day_filter(day: str) -> str:
    return (
        f"registeredAt ge {day}T00:00:00 and registeredAt le {day}T23:59:59"
    )


class FrlDayHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        day = str(task.params["date"])
        skip = int(task.params.get("skip", 0))
        return RequestSpec(url=odata_url("/Versions", _day_filter(day), skip=skip))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        if response.status_code != 200:
            raise ValueError(f"day feed returned HTTP {response.status_code}")
        payload = response.json()
        rows = payload.get("value")
        if not isinstance(rows, list):
            raise TypeError("day feed JSON has no value[] array")

        day = str(task.params["date"])
        skip = int(task.params.get("skip", 0))
        mode: dict[str, Any] = {
            "comp": str(task.params.get("comp", "anchor")),
            "gazette": str(task.params.get("gazette", "0")),
        }

        newest: dict[str, str] = {}
        for row in rows:
            title_id = row.get("titleId")
            registered = row.get("registeredAt") or ""
            if not title_id:
                continue
            stamp = registered[:19]
            if stamp > newest.get(title_id, ""):
                newest[title_id] = stamp

        seeds: list[TaskSeed] = [
            TaskSeed(
                type="frl_title",
                params={**mode, "title_id": title_id},
                signal=stamp or None,
            )
            for title_id, stamp in sorted(newest.items())
        ]
        max_titles = task.params.get("max_titles")
        if max_titles:
            seeds = seeds[: int(max_titles)]

        result = TaskResult(next_tasks=seeds)

        if len(rows) == PAGE_SIZE:
            result.next_tasks.append(
                TaskSeed(
                    type="frl_day",
                    params={**task.params, "skip": skip + PAGE_SIZE},
                )
            )
        else:
            # Last page of the day: the whole registration day has been
            # consumed (enumeration, not downloads) — safe to advance the
            # cursor, weekend zero-event days included.
            result.cursor_updates = {CURSOR_KEY: day}
            if not seeds and not rows:
                result.expected_empty = f"no registration events on {day}"
        return result
