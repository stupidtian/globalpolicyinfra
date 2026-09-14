"""Task type ``che_sr_walk``: paged enumeration of every SR entry.

``?e a jolux:ConsolidationAbstract`` ORDER BY ?e LIMIT 500 OFFSET n —
17,299 entries ≈ 35 pages (probed 2026-09-09; the endpoint accepted a
LIMIT 50000 request without truncation, but paging keeps responses small
and gives the chain natural resume points). A full page chains to the
next offset; the *last* page — the only one that saw fewer than 500
rows — is the one that sets the SR modified watermark to the sweep's
``mark_ts`` (start time minus a 1-hour clock-skew margin), so a walk
crashed mid-chain never advances the watermark its own pages have not
earned. Any version changed after the sweep started carries a newer
``modified`` and is caught by the next feed run; the margin absorbs
server/client clock disagreement.

``max_entries`` caps entry spawns (a test guard), never the enumeration:
the chain still walks to its end so the watermark still reflects a fully
swept register.
"""

from __future__ import annotations

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.che.sources.fedlex import (
    ACCEPT_SPARQL_JSON,
    SPARQL_ENDPOINT,
    SR_CURSOR_KEY,
    WALK_PAGE,
)

__all__ = ["CheSrWalkHandler", "walk_query"]


def walk_query(offset: int, limit: int) -> str:
    return f"""PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT ?entry ?sr ?titleDe WHERE {{
  ?entry a jolux:ConsolidationAbstract .
  OPTIONAL {{ ?entry jolux:classifiedByTaxonomyEntry ?taxRes . ?taxRes skos:notation ?sr }}
  OPTIONAL {{ ?entry jolux:isRealizedBy ?eDe .
    ?eDe jolux:language <http://publications.europa.eu/resource/authority/language/DEU> ;
         jolux:title ?titleDe }}
}} ORDER BY ?entry LIMIT {limit} OFFSET {offset}"""


class CheSrWalkHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        offset = int(task.params["offset"])
        return RequestSpec(
            url=SPARQL_ENDPOINT,
            params={"query": walk_query(offset, WALK_PAGE)},
            headers=dict(ACCEPT_SPARQL_JSON),
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        if response.status_code != 200:
            raise ValueError(f"SR walk query returned HTTP {response.status_code}")
        payload = response.json()
        bindings = payload.get("results", {}).get("bindings")
        if not isinstance(bindings, list):
            raise TypeError("SR walk response has no results.bindings array")

        entries: list[str] = []
        for binding in bindings:
            cell = binding.get("entry")
            value = cell.get("value", "") if cell else ""
            if not value.startswith("https://fedlex.data.admin.ch/eli/cc/"):
                raise ValueError(f"unexpected entry URI {value!r} in walk page")
            if value not in entries:
                entries.append(value)

        mode = {
            "fmts": str(task.params.get("fmts", "html")),
            "langs": str(task.params.get("langs", "")),
            "sr": str(task.params.get("sr", "anchor")),
        }
        spawns = [
            TaskSeed(type="che_sr_entry", params={**mode, "entry_uri": entry})
            for entry in entries
        ]
        max_entries = task.params.get("max_entries")
        if max_entries:
            spawns = spawns[: int(max_entries)]

        result = TaskResult(next_tasks=spawns)
        if not bindings:
            if int(task.params["offset"]) == 0:
                # the register holds 17,299 entries (counted 2026-09-09) —
                # a zero first page is the endpoint's empty-answer flap,
                # not an empty register; retry rather than "finish"
                from runtime.errors import TransientError

                raise TransientError(
                    "SR walk first page returned zero rows — endpoint flap "
                    "(empty-but-valid answers observed under load)"
                )
            result.expected_empty = "SR walk page beyond the register's end"
        if len(bindings) == WALK_PAGE:
            result.next_tasks.append(
                TaskSeed(
                    type="che_sr_walk",
                    params={**task.params, "offset": int(task.params["offset"]) + WALK_PAGE},
                )
            )
        else:
            # Last page: the whole register has been enumerated — the
            # feed watermark may advance to this sweep's start stamp.
            result.cursor_updates = {SR_CURSOR_KEY: str(task.params["mark_ts"])}
        return result
