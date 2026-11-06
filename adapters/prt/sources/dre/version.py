"""Task type ``dre_version``: per-run token bootstrap (one module each).

GET one portal frontend module script (stable URL) and regex-extract the
apiVersion tokens of its data actions. ``moduleVersion`` is not validated
by the portal (probed 2026-09-17: an arbitrary string answers data; the
envelope only *reports* ``hasModuleVersionChanged``), so only these
per-action tokens matter. They rotate with every portal release, hence
the fresh extraction on every run and the trip through task params —
downstream task ids change when the portal redeploys and already-done
windows re-execute; idempotent upserts keep the ledger correct
(ARCHITECTURE section 6.3, session-token trade-off).

The chain: ``module_order[0]`` is seeded by ``start_tasks``; each parse
merges its tokens into ``tok`` and seeds the next module; the last
module's parse emits the working seeds — one ``dre_day`` per
(serie, date) in the requested ranges plus one ``dre_doc`` per targeted
``doc=`` entry.
"""

from __future__ import annotations

from datetime import date, timedelta

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.prt.sources.dre import (
    MODULE_ORDER,
    MODULE_SCRIPTS,
    tokens_for,
)

__all__ = ["DreVersionHandler"]


class DreVersionHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        module = str(task.params["module"])
        return RequestSpec(url=MODULE_SCRIPTS[module])

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        module = str(task.params["module"])
        tok = dict(task.params.get("tok") or {})
        spec = dict(task.params.get("spec") or {})

        js = response.content.decode("utf-8", errors="replace")
        tok.update(tokens_for(module, js))

        index = MODULE_ORDER.index(module)
        if index + 1 < len(MODULE_ORDER):
            nxt = MODULE_ORDER[index + 1]
            return TaskResult(
                next_tasks=[
                    TaskSeed(type="dre_version", params={"module": nxt, "tok": tok, "spec": spec})
                ]
            )

        seeds: list[TaskSeed] = []
        for serie, (from_iso, to_iso) in sorted(spec.get("ranges", {}).items()):
            day = date.fromisoformat(from_iso)
            end = date.fromisoformat(to_iso)
            while day <= end:
                seeds.append(
                    TaskSeed(
                        type="dre_day",
                        params={"date": day.isoformat(), "serie": serie, "tok": dict(tok)},
                    )
                )
                day += timedelta(days=1)
        for entry in spec.get("docs", []):
            seeds.append(
                TaskSeed(
                    type="dre_doc",
                    params={
                        "tipo": str(entry["tipo"]),
                        "key": str(entry["key"]),
                        "tok": dict(tok),
                    },
                )
            )
        if not seeds:
            return TaskResult(
                expected_empty=(
                    "nothing to fetch: sync ranges are already up to date and no "
                    "doc= entries were given"
                )
            )
        return TaskResult(next_tasks=seeds)
