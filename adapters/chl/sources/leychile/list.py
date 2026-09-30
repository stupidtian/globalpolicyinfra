"""Task type ``chl_list``: one page of one year's register.

Row shape (probed 2026-09-20, stable from 1900 to 2024)::

    {"IDNORMA": "1209817", "ID_VERSION": "14477307", "TIPOVERSION": "3",
     "NORMA": "Decreto 297 EXENTO", "TITULO_NORMA": "DETERMINA PRECIOS …",
     "ABREVIACION": "DTO", "DESCRIPCION": "Decreto", "NUMERO": "297 EXENTO",
     "ORGANISMO": "MINISTERIO DE ENERGÍA",
     "FECHA_PUBLICACION": "31-DIC-2024",        <- Spanish months
     "FECHA_PROMULGACION": "2024-12-30",        <- already ISO
     "FECHA_VIGENCIA": "2024-12-31",            <- = latest version's
                                                    vigenteDesde (probed on
                                                    Ley 18290)
     "FECHA_DEROGACION": "", …}

One register row per norma — the current-version view of the law. Every
row lands in ``normas`` (the register and its time series are complete
after the list layer alone, ~8.3K pages for the whole corpus of 415,344);
``max_normas`` caps only the deep-fetch spawns, never the registration.

Pagination: any page is one request away (``npagina``); orden=2 walks the
year publication-date-descending with clean page boundaries (probed:
refetch-stable, zero duplicate IDNORMA across pages). A page beyond the
last returns HTTP 200 with an empty row list — ``expected_empty``; with
``walk=1`` the chain self-terminates.

``signal`` (the CLI's ``refresh=<timestamp>``) rides the walk children so
a refresh run re-reads every page of the year.
"""

from __future__ import annotations

from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.chl.sources.leychile import (
    API_BASE,
    PAGE_SIZE,
    list_params,
    map_doc_type,
    spanish_date_to_iso,
)

__all__ = ["ChlListHandler"]


def _norma_row(item: dict[str, Any]) -> dict[str, str]:
    """One register row for the ``normas`` table (ISO dates; empty stays
    empty — upsert merges partial rows)."""
    id_norma = str(item.get("IDNORMA", "")).strip()
    if not id_norma:
        raise ValueError("register row carries no IDNORMA")
    return {
        "id_norma": id_norma,
        "norma_name": item.get("NORMA") or item.get("COMPUESTO") or f"Norma {id_norma}",
        "title": item.get("TITULO_NORMA") or "",
        "doc_type": map_doc_type(item.get("ABREVIACION", "")),
        "type_abbr": item.get("ABREVIACION") or "",
        "organismo": item.get("ORGANISMO") or "",
        "numero": item.get("NUMERO") or "",
        "fecha_promulgacion": item.get("FECHA_PROMULGACION") or "",
        "fecha_publicacion": spanish_date_to_iso(item.get("FECHA_PUBLICACION", "")) or "",
        "fecha_derogacion": spanish_date_to_iso(item.get("FECHA_DEROGACION", "")) or "",
        "current_vigencia": item.get("FECHA_VIGENCIA") or "",
        "tipo_version": str(item.get("TIPOVERSION", "")).strip(),
    }


class ChlListHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=f"{API_BASE}/buscarjson",
            params=list_params(int(task.params["year"]), int(task.params["pg"])),
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = dict(task.params)
        year = int(params["year"])
        pg = int(params["pg"])
        if response.status_code != 200:
            raise ValueError(f"register page {year}/{pg} returned HTTP {response.status_code}")

        data: Any = response.json()
        if not isinstance(data, list) or len(data) < 2 or not isinstance(data[0], list):
            raise ValueError(f"register page {year}/{pg} is not the probed [rows, echo] shape")
        rows: list[Any] = data[0]

        if not rows:
            return TaskResult(
                expected_empty=f"register page {year}/{pg} holds no normas "
                "(beyond the year's last page)"
            )

        # Every row registers (time-series floor); anchors spawn per row.
        # FECHA_VIGENCIA (latest version's vigenteDesde) identifies the
        # anchor version in the canonical date form; probed non-empty from
        # 1900 rows to 2024 — fall back to the numeric ID_VERSION only if
        # a future row drops it, the body endpoint accepts both.
        upserts: list[dict[str, str]] = []
        anchors: list[TaskSeed] = []
        for item in rows:
            row = _norma_row(item)
            upserts.append(row)
            id_version = item.get("FECHA_VIGENCIA") or item.get("ID_VERSION") or ""
            if not str(id_version).strip():
                raise ValueError(f"norma {row['id_norma']} carries neither FECHA_VIGENCIA nor ID_VERSION")
            anchors.append(
                TaskSeed(
                    type="chl_body",
                    params={
                        "id_norma": row["id_norma"],
                        "id_version": str(id_version).strip(),
                        "tipo_version": row["tipo_version"],
                    },
                )
            )

        max_normas = params.get("max_normas")
        cap = max_normas if isinstance(max_normas, int) else None
        capped = cap is not None and len(anchors) > cap
        if capped and cap is not None:
            anchors = anchors[:cap]

        next_tasks = list(anchors)
        full_page = len(rows) >= PAGE_SIZE
        if full_page and not capped and params.get("walk"):
            next_tasks.append(
                TaskSeed(
                    type="chl_list",
                    params={**params, "pg": pg + 1},
                    signal=task.signal,  # a refresh re-walk must reach every page
                )
            )
        return TaskResult(
            upsert_rows={"normas": upserts},
            next_tasks=next_tasks,
        )
