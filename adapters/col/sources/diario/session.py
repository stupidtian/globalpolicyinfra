"""Task type ``diario_session``: establish the JSF session for one run.

GET the searcher home page. Two things come back that the rest of the
chain needs (probed 2026-10-19, samples in the task folder):

- a cookie session (kept by the transport's cookie jar — invisible here);
- the JSF view state (``j_id1:javax.faces.ViewState:0`` input value),
  which this application keeps **stable for the whole session** (three
  consecutive searches reusing one value succeeded) — every downstream
  task carries it in its params.

The handler chains **only the first date** of the window: the searcher's
server-side view state holds one shared table model, so a day search and
its row clicks must run strictly adjacent (trial-run lesson 2026-10-19:
three day searches enqueued together poisoned every row click — each
click landed on the last-*rendered* table's row). The chain therefore
walks day by day: search → row clicks → PDF → next day's search. A
response without a view state (WAF page, HTML change) fails loud.
"""

from __future__ import annotations

import re

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.col.sources.diario import SEARCHER_URL

__all__ = ["DiarioSessionHandler"]

_VIEWSTATE_RE = re.compile(
    r'id="j_id1:javax.faces.ViewState:0"[^>]*value="([^"]*)"'
)


class DiarioSessionHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=SEARCHER_URL)

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        if response.status_code != 200:
            raise ValueError(
                f"diario session: searcher home answered HTTP {response.status_code}"
            )
        html = response.content.decode("utf-8", errors="replace")
        match = _VIEWSTATE_RE.search(html)
        if not match:
            raise ValueError(
                "diario session: no JSF view state on the searcher home "
                "(shape changed or an interstitial page answered)"
            )

        return TaskResult(
            next_tasks=[
                TaskSeed(
                    type="diario_day",
                    params={
                        "date": str(task.params["from"]),
                        "window_to": str(task.params["to"]),
                        "viewstate": match.group(1),
                    },
                )
            ]
        )
