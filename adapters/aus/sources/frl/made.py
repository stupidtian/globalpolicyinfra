"""Task type ``frl_made``: one page of the making-date enumeration.

The backfill entry (``made=FROM:TO`` on the CLI): pages through
``/Titles?$filter=makingDate ge … and le …`` in ``$top=100`` slices,
spawning one ``frl_title`` per title id found. This is the *making-date*
axis — "what was made in this range" — which is how a historical backfill
must be enumerated: registration dates of old titles are 2005–2013 mass
back-import stamps (a 1901 Act registers as 2013-01-22), and the
registration feed mixes compilation events of old titles into every
window, so it cannot answer making-year questions (probed 2026-08-31:
2010 holds 2,995 titles — 150 Acts, 2,843 legislative instruments).

``$select=id`` keeps pages light (full rows carry name/status history
JSON around 3 KB per title; only the id is needed here). Enumeration
never touches the registration cursor: the daily feed and this entry are
independent axes that meet at the identity layer — an frl_title already
done from a daily sweep skips here regardless of which entry found it.
"""

from __future__ import annotations

from typing import Any

from adapters.aus.sources.frl import PAGE_SIZE, odata_url
from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView

__all__ = ["FrlMadeHandler"]


def _made_filter(from_date: str, to_date: str) -> str:
    return f"makingDate ge {from_date}T00:00:00 and makingDate le {to_date}T23:59:59"


class FrlMadeHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=odata_url(
                "/Titles",
                _made_filter(str(task.params["from"]), str(task.params["to"])),
                skip=int(task.params.get("skip", 0)),
                select="id",
            )
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        if response.status_code != 200:
            raise ValueError(f"made enumeration returned HTTP {response.status_code}")
        rows = response.json().get("value")
        if not isinstance(rows, list):
            raise TypeError("made enumeration JSON has no value[] array")

        mode: dict[str, Any] = {
            "comp": str(task.params.get("comp", "anchor")),
            "gazette": str(task.params.get("gazette", "0")),
            "layer": str(task.params.get("layer", "full")),
        }
        title_ids = sorted({row["id"] for row in rows if row.get("id")})
        seeds = [
            TaskSeed(type="frl_title", params={**mode, "title_id": title_id})
            for title_id in title_ids
        ]
        max_titles = task.params.get("max_titles")
        if max_titles:
            seeds = seeds[: int(max_titles)]

        result = TaskResult(next_tasks=seeds)
        if len(rows) == PAGE_SIZE:
            result.next_tasks.append(
                TaskSeed(
                    type="frl_made",
                    params={
                        **task.params,
                        "skip": int(task.params.get("skip", 0)) + PAGE_SIZE,
                    },
                )
            )
        elif not rows:
            result.expected_empty = (
                f"no titles made between {task.params['from']} and {task.params['to']}"
            )
        # no cursor updates: the making axis never advances the
        # registration feed's frl_last_date
        return result
