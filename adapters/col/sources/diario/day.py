"""Task type ``diario_day``: one calendar day's issue list.

POST the searcher form (``fechaInicial`` = ``fechaFinal`` = the day, plus
the session's view state). The result table carries one row per issue of
that day — issue number, edition type, publication-date echo. Probed
shapes (2026-10-19, samples in the task folder):

- rows: ``dtbDiariosOficiales:{row}:fechaDiario`` / ``:numeroDiario`` /
  ``:tipoEdicion`` labels; the row's own "Ver Diario" submit button is
  ``dtbDiariosOficiales:{row}:j_idt34`` (row index travels in params);
- empty day: a clean result table with the paginator reading
  ``Registro 0 a 0 de 0`` — an explained empty;
- a finished search is a *fully consumed* day partition: the watermark
  ``diario_last_date`` advances here (USA empty-window precedent), the
  per-issue PDF outcomes below cannot un-consume the enumeration.

Chain position (trial-run lesson 2026-10-19): the server-side view
state holds one shared table model, so this search must be immediately
followed by its own row clicks. The task emits its issue tasks with
``is_last`` markers; when the window continues, the **last issue's**
handler (or this handler on an empty day) seeds the next day's search —
never this task, whose table would be stale by the time the issues
finish. A row echoing a different date, or a table with neither rows nor
the empty signature, fails loud.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.col.sources.diario import CURSOR_KEY, SEARCHER_URL

__all__ = ["DiarioDayHandler"]

_ROW_FECHA_RE = re.compile(
    r'id="dtbDiariosOficiales:(\d+):fechaDiario"[^>]*>([^<]*)<'
)
_ROW_NUMERO_RE = re.compile(
    r'id="dtbDiariosOficiales:(\d+):numeroDiario"[^>]*>([^<]*)<'
)
_ROW_TIPO_RE = re.compile(
    r'id="dtbDiariosOficiales:(\d+):tipoEdicion"[^>]*>([^<]*)<'
)
_EMPTY_SIGNATURE = "Registro 0 a 0 de 0"
#: The fresh view state rides on every search response; downstream POSTs
#: use the latest value seen (equal to the session value in practice).
_VIEWSTATE_RE = re.compile(
    r'id="j_id1:javax.faces.ViewState:0"[^>]*value="([^"]*)"'
)


def _ddmmyyyy(iso: str) -> str:
    year, month, day = iso.split("-")
    return f"{day}/{month}/{year}"


def _next_day_params(task: TaskView, viewstate: str) -> dict[str, str] | None:
    """The window walks one day at a time: day+1 while below ``window_to``."""
    day = str(task.params["date"])
    window_to = str(task.params["window_to"])
    following = date.fromisoformat(day) + timedelta(days=1)
    if following.isoformat() > window_to:
        return None
    return {
        "date": following.isoformat(),
        "window_to": window_to,
        "viewstate": viewstate,
    }


class DiarioDayHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        day = str(task.params["date"])
        viewstate = str(task.params["viewstate"])
        return RequestSpec(
            url=f"{SEARCHER_URL}index.xhtml",
            method="POST",
            form_body={
                "frmConDiario": "frmConDiario",
                "fechaInicial_input": _ddmmyyyy(day),
                "fechaFinal_input": _ddmmyyyy(day),
                "btnBuscar": "Buscar",
                "javax.faces.ViewState": viewstate,
            },
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        day = str(task.params["date"])
        if response.status_code != 200:
            raise ValueError(f"diario day {day}: search answered HTTP {response.status_code}")
        html = response.content.decode("utf-8", errors="replace")
        viewstate_match = _VIEWSTATE_RE.search(html)

        fechas = {row: value.strip() for row, value in _ROW_FECHA_RE.findall(html)}
        numeros = {row: value.strip() for row, value in _ROW_NUMERO_RE.findall(html)}
        tipos = {row: value.strip() for row, value in _ROW_TIPO_RE.findall(html)}

        if not fechas:
            if _EMPTY_SIGNATURE not in html:
                raise ValueError(
                    f"diario day {day}: no rows and no empty-table signature "
                    "(unknown shape — refusing to invent an empty day)"
                )
            next_params = (
                _next_day_params(task, viewstate_match.group(1))
                if viewstate_match
                else None
            )
            next_tasks = (
                [TaskSeed(type="diario_day", params=next_params)] if next_params else []
            )
            return TaskResult(
                next_tasks=next_tasks,
                expected_empty=f"no Diario Oficial issue indexed for {day}",
                cursor_updates={CURSOR_KEY: day},
            )

        if not viewstate_match:
            raise ValueError(f"diario day {day}: response carries no view state")
        viewstate = viewstate_match.group(1)

        rows = sorted(fechas, key=int)
        seeds: list[TaskSeed] = []
        for position, row in enumerate(rows):
            row_fecha = fechas[row]
            if row_fecha != f"{day[8:]}/{day[5:7]}/{day[:4]}":
                raise ValueError(
                    f"diario day {day}: row {row} echoes date {row_fecha!r} "
                    "instead of the searched day"
                )
            numero = numeros.get(row, "")
            if not numero:
                raise ValueError(f"diario day {day}: row {row} carries no issue number")
            seeds.append(
                TaskSeed(
                    type="diario_issue",
                    params={
                        "date": day,
                        "numero": numero,
                        "tipo_edicion": tipos.get(row, ""),
                        "row": row,
                        "is_last": "1" if position == len(rows) - 1 else "",
                        "window_to": str(task.params["window_to"]),
                        "viewstate": viewstate,
                    },
                )
            )
        return TaskResult(next_tasks=seeds, cursor_updates={CURSOR_KEY: day})
