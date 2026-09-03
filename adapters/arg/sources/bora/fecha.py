"""Task type ``bora_fecha``: point the server-side session at one day.

GET ``/edicion/actualizar/{DD-MM-YYYY}`` with XHR headers — the site's own
way of selecting the edition day; the chosen day lives in the server-side
session (cookie jar), which the transport maintains for the whole collect
run (section 6.3 session semantics). The response body is a bare JSON
object (``{}``); the task's only job is to have issued the request and to
chain the day's listing task.

Chain discipline (why this type exists as its own task): ``bora_seccion``
and its pagination read the session date, so within a run exactly one day
may be "active" in the session. ``bora_fecha(D)`` is enqueued only by (a)
the run's seed — a single day, the first not-yet-consumed one — or (b) the
last listing page of day D-1. The engine's FIFO then guarantees no other
fecha task can interleave; ``bora_seccion`` still verifies the session date
against the page's own ``fechaSeleccionadaYMD`` as defence in depth. The
seed carries a per-run ``run`` stamp so a crashed-and-rerun window
re-executes the date-setting request (its side effect does not survive a
process restart; done-skip must not swallow it) — the listing tasks carry
no stamp and done-skip normally.
"""

from __future__ import annotations

from adapters.arg.sources.bora import BASE_URL
from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView

__all__ = ["BoraFechaHandler"]


class BoraFechaHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        yyyy, mm, dd = str(task.params["date"]).split("-")
        return RequestSpec(
            url=f"{BASE_URL}/edicion/actualizar/{dd}-{mm}-{yyyy}",
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json",
                "Referer": f"{BASE_URL}/",
            },
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        date = str(task.params["date"])
        to = str(task.params["to"])
        if response.status_code != 200:
            raise ValueError(
                f"fecha {date}: edition selector answered HTTP {response.status_code}"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise ValueError(f"fecha {date}: selector body is not JSON: {exc}") from exc
        if not isinstance(body, dict):
            raise TypeError(f"fecha {date}: selector body is {type(body).__name__}")
        params: dict[str, str] = {"date": date, "to": to, "run": str(task.params["run"])}
        return TaskResult(next_tasks=[TaskSeed(type="bora_seccion", params=params)])
