"""Task types ``bgbl_session`` and ``bgbl_csrf``: the session bootstrap.

media.xav (PDF delivery) requires the transport session's cookie *and* the
CSRF token bound to that session (P0 matrix experiment, 2026-08-27: either
one missing or a foreign token yields 403). The cookie lives in the
transport's cookie jar (section 6.3) — the pack never sees it; the CSRF
token arrives in a JSON *body* and travels to the download tasks via task
params (section 6.6 allows cross-page state through params).

Two tasks, one request each (2026-08-27 plan ruling): E3 opens the session,
E4 reads the token. Both carry the per-run nonce so every collect run
rebuilds a fresh session.
"""

from __future__ import annotations

from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.deu.sources.bgbl import BASE_URL, BOOK, USER_AGENT

__all__ = ["BgblCsrfHandler", "BgblSessionHandler"]


def _headers() -> dict[str, str]:
    return {"User-Agent": USER_AGENT}


class BgblSessionHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=f"{BASE_URL}/start.xav", headers=_headers())

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        if response.status_code != 200:
            raise ValueError(f"session bootstrap returned HTTP {response.status_code}")
        # The Set-Cookie exchange happened transport-side; nothing to read here.
        params: dict[str, Any] = dict(task.params)
        return TaskResult(next_tasks=[TaskSeed(type="bgbl_csrf", params=params)])


class BgblCsrfHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=f"{BASE_URL}/start.xav",
            params={"nocomm": "final", "SID": "", "startbk": BOOK, "bk": BOOK, "start": ""},
            headers={**_headers(), "X-Requested-With": "XMLHttpRequest"},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        payload = response.json()
        token = payload.get("csrftoken")
        if not token:
            raise ValueError("session response carries no csrftoken")
        params: dict[str, Any] = {**task.params, "csrf": str(token)}
        return TaskResult(
            next_tasks=[TaskSeed(type="bgbl_toc", params={**params, "level": "root", "node_id": 0})]
        )
