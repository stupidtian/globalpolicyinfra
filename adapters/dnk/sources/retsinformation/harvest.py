"""Task type ``rt_harvest``: one day of the official harvest change feed.

GET ``https://api.retsinformation.dk/v1/Documents?date=YYYY-MM-DD`` —
Civilstyrelsen's official harvest service (swagger in the task archive):
documents changed in ``(date-1, date 03:00]``, each with
``reasonForChange`` (NewDocument / DocumentContentChanged /
DocumentMetadataChanged / DocumentMetadataChangedAndDocumentContentChanged
/ RemovedDocument), ``changeDate`` and the accession number. Hard
constraints (probed 2026-09-15): only 03:00-23:45, **one call per 10
seconds** (429 otherwise — run with ``--delay 10:12``), ``date`` within
the last 10 days. Offical daily-cadence channel; default-off refresh
sweep in this source.

The feed identifies documents by accession number only — resolution to
the canonical path (and therefore to the window-mode doc_id) happens in
``rt_text`` (resolve mode) via the POST response metadata, so refreshed
documents keep their identity instead of duplicating rows. Removed
documents are explained empties (no deletion machinery in v1).
"""

from __future__ import annotations

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.dnk.sources.retsinformation import HARVEST_BASE, ID_TO_CODE

__all__ = ["RtHarvestHandler"]


class RtHarvestHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=f"{HARVEST_BASE}/v1/Documents",
            params={"date": str(task.params["date"])},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        date = str(task.params["date"])
        items = response.json()
        if not isinstance(items, list):
            raise TypeError(f"rt_harvest {date}: unexpected payload shape")

        seeds: list[TaskSeed] = []
        removed = 0
        for item in items:
            reason = str(item.get("reasonForChange") or "")
            accn = str(item.get("accessionsnummer") or "").strip()
            if not accn:
                continue
            if reason == "RemovedDocument":
                removed += 1
                continue
            doc_type = item.get("documentType") or {}
            code = ID_TO_CODE.get(int(doc_type.get("id", 0)), "") if isinstance(doc_type, dict) else ""
            seeds.append(
                TaskSeed(
                    type="rt_text",
                    params={
                        "eli": f"/eli/accn/{accn}",
                        "code": code,
                        "resolve": "1",
                        # the change feed covers the whole site; the media
                        # (known only after resolution) is filtered against
                        # the run's scope so out-of-scope changes explain away
                        "scope": str(task.params.get("scope", "lta,ltb")),
                    },
                    signal=str(item.get("changeDate") or date),
                )
            )
        if not seeds:
            return TaskResult(
                expected_empty=(
                    f"rt_harvest {date}: {len(items)} changes, all removed-document "
                    f"entries ({removed}) or accession-less — nothing to refresh"
                )
                if items
                else f"rt_harvest {date}: empty change feed"
            )
        return TaskResult(next_tasks=seeds)
