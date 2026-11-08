"""Task types ``suin_window`` / ``suin_page``: one sanction-date day.

POST the public Elasticsearch ``_search`` endpoint for one ``fecha``
calendar day (Bogotá-aligned via the range query's ``time_zone``),
filtered to the normative tipo whitelist and sorted by id ascending.
Cross-page walking is the task queue's first-layer pattern: page 0 runs
in ``suin_window``, a full page chains a ``suin_page`` continuation
carrying the ``search_after`` cursor in its params; the first short page
closes the day and moves the watermark. One task = one request.

Probed behaviours shaping these handlers (2026-10-19, samples in the
task folder):

- The index answers with exact totals (``relation: eq``) and stable
  ``id`` sort values, so ``search_after`` pagination covers the whole
  index (10k ``from+size`` window bypassed, verified over 103,340 docs).
- An empty day is a clean 200 with zero hits — still a *fully consumed*
  day: the watermark advances.
- ``tipo`` is dirty at the edges (form leftovers like "-- Seleccione --"
  and numeric junk); the whitelist filter keeps them out by design.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.col.sources.suin import (
    CURSOR_KEY,
    DEFAULT_TIPOS,
    ES_SEARCH_URL,
    PAGE_SIZE,
    parse_tipos,
)

__all__ = ["SuinPageHandler", "SuinWindowHandler"]


def _scope(task: TaskView) -> list[str]:
    raw = task.params.get("tipos")
    return parse_tipos(str(raw) if raw else None)


def _search_body(scope: list[str], search_after: list[int] | None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "from": 0,
        "size": PAGE_SIZE,
        "track_total_hits": True,
        "sort": [{"id": "asc"}],
        "query": {
            "bool": {
                "filter": [
                    {"terms": {"tipo.keyword": scope}},
                ]
            }
        },
    }
    if search_after is None:
        return body
    page_task: dict[str, Any] = {"search_after": search_after}
    return {**body, **page_task}


def _fecha_range(body: dict[str, Any], day: str) -> None:
    filters = body["query"]["bool"]["filter"]
    filters.insert(
        0,
        {
            "range": {
                "fecha": {
                    "gte": day,
                    "lt": (date.fromisoformat(day) + timedelta(days=1)).isoformat(),
                    "time_zone": "America/Bogota",
                }
            }
        },
    )


def _doc_seed(hit: dict[str, Any], found_on: str, scope: list[str]) -> TaskSeed:
    source = hit.get("_source") or {}
    norm_id = source.get("id")
    if norm_id is None:
        raise ValueError(f"suin {found_on}: a hit carries no _source.id")
    params: dict[str, str] = {"id": str(norm_id), "found_on": found_on}
    carried = {
        "fecha": source.get("fecha"),
        "titulo": source.get("titulo"),
        "tipo": source.get("tipo"),
        "subtipo": source.get("subtipo"),
        "numero": source.get("numero"),
        "anio": source.get("anio"),
        "entidad": source.get("entidad"),
        "estado": source.get("estado"),
        "numero_diario": source.get("numerodiariooficial"),
        "pagina_diario": source.get("paginadiariooficial"),
        "documentofuente": source.get("documentofuente"),
        "materia": source.get("materia"),
        "sector": source.get("sector"),
        "noart": source.get("noart"),
    }
    for key, value in carried.items():
        if value is not None and str(value).strip():
            params[key] = str(value)
    if scope != list(DEFAULT_TIPOS):
        params["tipos"] = ",".join(scope)
    return TaskSeed(type="suin_doc", params=params)


def _parse_page(response: Response, task: TaskView, search_after: list[int] | None) -> TaskResult:
    day = str(task.params["date"])
    scope = _scope(task)
    if response.status_code != 200:
        raise ValueError(f"suin {day}: ES search answered HTTP {response.status_code}")
    payload = response.json()
    hits = (payload.get("hits") or {}).get("hits")
    if not isinstance(hits, list):
        raise TypeError(f"suin {day}: ES response carries no hits list")

    seeds = [_doc_seed(hit, day, scope) for hit in hits]

    if len(hits) == PAGE_SIZE:
        last_sort = hits[-1].get("sort")
        if not isinstance(last_sort, list) or not last_sort:
            raise ValueError(f"suin {day}: full page's last hit carries no sort value")
        next_params: dict[str, str] = {
            "date": day,
            "search_after": json.dumps([int(v) for v in last_sort]),
        }
        if task.params.get("tipos"):
            next_params["tipos"] = str(task.params["tipos"])
        return TaskResult(
            next_tasks=[*seeds, TaskSeed(type="suin_page", params=next_params)],
        )

    # Short page (or empty): the day is exhausted — emit the seeds and close it.
    explained = (
        f"no norms with fecha {day} in the tipo whitelist"
        if not seeds and search_after is None
        else f"fecha {day} page closed with {len(seeds)} further norms"
    )
    return TaskResult(
        next_tasks=seeds,
        expected_empty=explained if not seeds else None,
        cursor_updates={CURSOR_KEY: day},
    )


class SuinWindowHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        day = str(task.params["date"])
        body = _search_body(_scope(task), None)
        _fecha_range(body, day)
        return RequestSpec(url=ES_SEARCH_URL, method="POST", json_body=body)

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        return _parse_page(response, task, None)


class SuinPageHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        day = str(task.params["date"])
        search_after = json.loads(str(task.params["search_after"]))
        if not isinstance(search_after, list):
            raise TypeError(f"suin {day}: malformed search_after param")
        body = _search_body(_scope(task), [int(v) for v in search_after])
        _fecha_range(body, day)
        return RequestSpec(url=ES_SEARCH_URL, method="POST", json_body=body)

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        search_after = json.loads(str(task.params["search_after"]))
        return _parse_page(response, task, [int(v) for v in search_after])
