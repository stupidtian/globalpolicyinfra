"""Task type ``diario_issue``: one gazette issue's viewer page.

POST the row's "Ver Diario" submit button (the row index rides in
params) with the session's view state. The application answers with the
PDF viewer page; two probed shapes decide everything (2026-10-19,
samples in the task folder):

- **Viewer shape**: an ``<object type="application/pdf" data=
  "/diario/javax.faces.resource/dynamiccontent.properties.xhtml?…">``
  whose URL carries the session-bound download token (``pfdrid`` etc.),
  plus echoed issue metadata (Número de Diario / Tipo Edición / Fecha de
  Publicación) that must match the requested issue — the echo is the
  per-issue shape guard, and the trial run proved it load-bearing (a
  stale shared table model makes the click land on another issue's
  viewer, which only the echo catches). The download URL's relative
  form travels to ``diario_pdf`` in params (public page state, never a
  secret).
- **Request-form shape**: no object and a "Número de Recibo" form — the
  searcher's row exists but no PDF is archived (the pre-2001-era
  signature, also hit for scattered modern gaps). An explained empty;
  never retried, never OCR'd.

Chain position: this task seeds its ``diario_pdf`` fetch; the day's
**last** issue additionally seeds the next day's search, listed after
the PDF fetch (same-batch FIFO keeps the download ahead of the table-
mutating search). Anything else (viewer without object and without the
form, mismatched echoes) fails loud.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.col.sources.diario import SEARCHER_URL

__all__ = ["DiarioIssueHandler"]

_OBJECT_DATA_RE = re.compile(
    r'<object[^>]*type="application/pdf"[^>]*data="([^"]+)"'
)
_LABEL_ECHO_RE = {
    "numero": re.compile(
        r'Número de Diario:</label>\s*</td>\s*<td><label[^>]*>([^<]*)</label>'
    ),
    "tipo_edicion": re.compile(
        r'Tipo Edición:</label>\s*</td>\s*<td><label[^>]*>([^<]*)</label>'
    ),
    "fecha": re.compile(
        r'Fecha de Publicación:</label>\s*</td>\s*<td><label[^>]*>([^<]*)</label>'
    ),
}
_REQUEST_FORM_SIGNATURE = "Número de Recibo"


def _next_day_seed(task: TaskView, viewstate: str) -> TaskSeed | None:
    day = str(task.params["date"])
    window_to = str(task.params["window_to"])
    following = date.fromisoformat(day) + timedelta(days=1)
    if following.isoformat() > window_to:
        return None
    return TaskSeed(
        type="diario_day",
        params={
            "date": following.isoformat(),
            "window_to": window_to,
            "viewstate": viewstate,
        },
    )


class DiarioIssueHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        row = str(task.params["row"])
        viewstate = str(task.params["viewstate"])
        return RequestSpec(
            url=f"{SEARCHER_URL}index.xhtml",
            method="POST",
            form_body={
                "frmConDiario": "frmConDiario",
                f"dtbDiariosOficiales:{row}:j_idt34": "",
                "javax.faces.ViewState": viewstate,
            },
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        day = str(task.params["date"])
        numero = str(task.params["numero"])
        if response.status_code != 200:
            raise ValueError(
                f"diario issue {numero} ({day}): viewer answered HTTP {response.status_code}"
            )
        html = response.content.decode("utf-8", errors="replace")

        is_last = str(task.params.get("is_last", "")) == "1"
        next_day = None
        if is_last:
            state_match = re.search(
                r'id="j_id1:javax.faces.ViewState:0"[^>]*value="([^"]*)"', html
            )
            if state_match:
                next_day = _next_day_seed(task, state_match.group(1))

        object_match = _OBJECT_DATA_RE.search(html)
        if not object_match:
            if _REQUEST_FORM_SIGNATURE in html:
                return TaskResult(
                    next_tasks=[next_day] if next_day else [],
                    expected_empty=(
                        f"issue {numero} of {day}: no PDF in the digital "
                        "archive (the viewer serves the publication-request "
                        "form — the pre-2001 era signature)"
                    ),
                )
            raise ValueError(
                f"diario issue {numero} ({day}): neither a PDF viewer object "
                "nor the known request-form shape"
            )

        echoes: dict[str, str] = {}
        for key, pattern in _LABEL_ECHO_RE.items():
            found = pattern.search(html)
            if not found:
                raise ValueError(
                    f"diario issue {numero} ({day}): viewer page carries no "
                    f"{key} echo (unknown shape)"
                )
            echoes[key] = found.group(1).strip()

        if echoes["numero"] != numero:
            raise ValueError(
                f"diario issue {numero} ({day}): viewer echoes issue "
                f"{echoes['numero']!r} instead — the shared view-state table "
                "model was mutated out of chain order"
            )
        expected_fecha = f"{day[8:]}/{day[5:7]}/{day[:4]}"
        if echoes["fecha"] != expected_fecha:
            raise ValueError(
                f"diario issue {numero} ({day}): viewer echoes date "
                f"{echoes['fecha']!r} instead of {expected_fecha!r}"
            )

        data_attr = object_match.group(1).replace("&amp;", "&")
        if not data_attr.startswith("/"):
            raise ValueError(
                f"diario issue {numero} ({day}): unexpected object data URL {data_attr[:80]!r}"
            )
        pdf_seed = TaskSeed(
            type="diario_pdf",
            params={
                "date": day,
                "numero": numero,
                "tipo_edicion": str(task.params.get("tipo_edicion", "")),
                "dyn_url": data_attr,
            },
        )
        # Same-batch FIFO: the PDF download (token is session-bound) runs
        # before the next day's search re-renders the shared table.
        next_tasks = [pdf_seed]
        if next_day is not None:
            next_tasks.append(next_day)
        return TaskResult(next_tasks=next_tasks)
