"""Task type ``ul_month``: one calendar month's slice of the issue calendar.

GET the authoritative issue calendar (``/api/uradni-list/izdaje-datumi`` —
every gazette issue date since 1991-01-18 in one JSON response, probed
2026-10-12) and emit one ``ul_date`` seed per real issue date inside this
task's month and window bounds. The calendar is the enumeration backbone:
days without an issue are never enqueued at all, so the "clean empty day"
shape other gazette sources tolerate never arises here — a bounds-consistent
month whose calendar slice is empty is a legitimate (rare) empty yield, and
a date the calendar asserts must answer a real listing (the ul_date handler
fails loudly otherwise). See docs/countries/svn/uradnilist-zh.md.
"""

from __future__ import annotations

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.svn.sources.uradnilist import API_BASE

__all__ = ["UlMonthHandler"]


class UlMonthHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=f"{API_BASE}/uradni-list/izdaje-datumi")

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        month = str(task.params["month"])
        lo = str(task.params["from"])
        hi = str(task.params["to"])
        scope = str(task.params.get("scope", "state"))
        pdf = str(task.params.get("pdf", "on"))
        payload = response.json()
        data = payload.get("data")
        dates = data.get("izdajeDatumi") if isinstance(data, dict) else None
        if not isinstance(dates, list) or not all(isinstance(day, str) for day in dates):
            raise ValueError(
                f"ul_month {month}: calendar response has no data.izdajeDatumi date "
                "list — the issue calendar endpoint may have moved"
            )
        seeds = [
            TaskSeed(
                type="ul_date",
                params={"date": day, "scope": scope, "pdf": pdf},
            )
            for day in dates
            if day.startswith(month) and lo <= day <= hi
        ]
        if not seeds:
            return TaskResult(
                expected_empty=(
                    f"{month}: no gazette issue dates inside [{lo}..{hi}] "
                    f"(calendar holds {len(dates)} issues)"
                )
            )
        return TaskResult(next_tasks=seeds)
