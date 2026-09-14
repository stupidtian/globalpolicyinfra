"""Task type ``che_sr_feed``: the SR change feed.

Every mutation the SR layer ever sees — a new point-in-time version, a
revised consolidation, an entry whose windows shifted — bumps the
``dct:modified`` stamp of the affected ``Consolidation`` (probed
2026-09-09: four versions touched within 24h). The feed asks for
versions modified strictly after the watermark, ascending, and reopens
one ``che_sr_entry`` per touched entry carrying the entry's newest stamp
as its signal: the store's done-skip then reopens an entry only when its
signal is genuinely newer (section 6.5).

The cursor advances only on the chain's last page (fewer rows than the
page size) and only to the newest stamp *that page saw* — server-ordered,
so no client-side timezone arithmetic. Entries have no modified stamp of
their own (probed), which is exactly why entries are always reached
through their versions.
"""

from __future__ import annotations

from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.che.sources.fedlex import (
    ACCEPT_SPARQL_JSON,
    FEED_PAGE,
    SPARQL_ENDPOINT,
    SR_CURSOR_KEY,
)

__all__ = ["CheSrFeedHandler", "feed_query"]


def feed_query(since: str, offset: int, limit: int) -> str:
    return f"""PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#>
PREFIX dct: <http://purl.org/dc/terms/>
SELECT ?v ?entry ?mod WHERE {{
  ?v a jolux:Consolidation ; jolux:isMemberOf ?entry ; dct:modified ?mod .
  FILTER (?mod > "{since}"^^<http://www.w3.org/2001/XMLSchema#dateTime>)
}} ORDER BY ASC(?mod) LIMIT {limit} OFFSET {offset}"""


def _cell(binding: dict[str, Any], name: str) -> str:
    cell = binding.get(name)
    return cell.get("value", "") if cell else ""


class CheSrFeedHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=SPARQL_ENDPOINT,
            params={
                "query": feed_query(
                    str(task.params["since"]), int(task.params["offset"]), FEED_PAGE
                )
            },
            headers=dict(ACCEPT_SPARQL_JSON),
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        if response.status_code != 200:
            raise ValueError(f"SR feed query returned HTTP {response.status_code}")
        payload = response.json()
        bindings = payload.get("results", {}).get("bindings")
        if not isinstance(bindings, list):
            raise TypeError("SR feed response has no results.bindings array")

        mode = {
            "fmts": str(task.params.get("fmts", "html")),
            "langs": str(task.params.get("langs", "")),
            "sr": str(task.params.get("sr", "anchor")),
        }
        newest: dict[str, str] = {}
        for binding in bindings:
            entry = _cell(binding, "entry")
            mod = _cell(binding, "mod")
            if not entry.startswith("https://fedlex.data.admin.ch/eli/cc/") or not mod:
                raise ValueError(f"unexpected feed row: entry={entry!r} mod={mod!r}")
            # server order is ascending; later rows win the max per entry
            newest[entry] = mod

        spawns = [
            TaskSeed(type="che_sr_entry", params={**mode, "entry_uri": entry}, signal=mod)
            for entry, mod in sorted(newest.items())
        ]

        result = TaskResult(next_tasks=spawns)
        if not bindings:
            result.expected_empty = (
                f"no SR consolidation changes since {task.params['since']}"
            )
            return result
        if len(bindings) == FEED_PAGE:
            result.next_tasks.append(
                TaskSeed(
                    type="che_sr_feed",
                    params={**task.params, "offset": int(task.params["offset"]) + FEED_PAGE},
                )
            )
        else:
            # Last page of the chain: everything to this stamp is consumed.
            # The cursor moves to the newest stamp seen (server-ordered
            # last row), so the next feed starts strictly after it.
            result.cursor_updates = {SR_CURSOR_KEY: max(newest.values())}
        return result
