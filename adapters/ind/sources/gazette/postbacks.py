"""PostBack handlers: the GazetteDirectory filter cascade, driven
through the ``form_body`` contract (2026-10-15).

The directory is an ASP.NET WebForms page: filtering = POSTing the full
form back with ``__EVENTTARGET`` naming the control that changed, and
the page's current ``__VIEWSTATE``/``__EVENTVALIDATION``. Two posts
finish a query — the category cascade (repopulates Part/Section) and
the search submit (``btnSubmit`` image button, posted as ``x``/``y``).
Probed live 2026-10-15: a post missing any of
``__LASTFOCUS``/``__SCROLLPOSITIONX``/``__SCROLLPOSITIONY``/the select
current-values answers 500 (Runtime Error) — the form must go back
complete, which is what the page-state signal carries.
"""

from __future__ import annotations

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.ind.sources.gazette import (
    DIR_CATEGORIES,
    SITE,
    extract_hidden_state,
    extract_rows,
    is_federal,
    page_state_to_signal,
    parse_dir_spec,
    signal_to_page_state,
)
from adapters.ind.sources.gazette.browse import _require, _seed_file_task
from runtime.errors import PermanentError

__all__ = ["GzDirCatHandler", "GzDirSearchHandler"]


def _directory_url(task: TaskView) -> str:
    sid = _require(task.params.get("sid"), "sid")
    return f"{SITE}/(S({sid}))/GazetteDirectory.aspx"


def _form_body(task: TaskView, overrides: dict[str, str]) -> dict[str, str]:
    state = signal_to_page_state(task.signal)
    body: dict[str, str] = dict(state.get("extra", {}))
    body.update(
        {
            "__VIEWSTATE": str(state["vs"]),
            "__EVENTVALIDATION": str(state["ev"]),
            "__VIEWSTATEGENERATOR": str(state.get("gen", "")),
        }
    )
    body.update(overrides)
    return body


def _post(url: str, referer: str, form_body: dict[str, str]) -> RequestSpec:
    return RequestSpec(
        url=url,
        method="POST",
        headers={"Referer": referer},
        form_body=form_body,
    )


class GzDirCatHandler:
    """``gz_dir_cat``: category cascade — ``__EVENTTARGET=ddlCategory``.
    The response repopulates Part/Section and carries the page state the
    search post needs."""

    def build_request(self, task: TaskView) -> RequestSpec:
        spec = parse_dir_spec(_require(task.params.get("spec"), "spec"))
        url = _directory_url(task)
        body = _form_body(
            task,
            {
                "__EVENTTARGET": "ddlCategory",
                "__EVENTARGUMENT": "",
                "__LASTFOCUS": "",
                "ddlCategory": DIR_CATEGORIES[spec["cat"]],
            },
        )
        return _post(url, url, body)

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        html = response.content.decode("utf-8", errors="replace")
        state = extract_hidden_state(html)
        return TaskResult(
            next_tasks=[
                TaskSeed(
                    type="gz_dir_search",
                    params={
                        "sid": str(task.params["sid"]),
                        "spec": str(task.params["spec"]),
                    },
                    signal=page_state_to_signal(state),
                )
            ]
        )


class GzDirSearchHandler:
    """``gz_dir_search``: the submit post — category + part + year with
    ``btnSubmit`` clicked. Federal result rows seed file tasks; zero
    rows is an explained empty (a part/year with no federal issue)."""

    def build_request(self, task: TaskView) -> RequestSpec:
        spec = parse_dir_spec(_require(task.params.get("spec"), "spec"))
        url = _directory_url(task)
        body = _form_body(
            task,
            {
                "__EVENTTARGET": "",
                "__EVENTARGUMENT": "",
                "__LASTFOCUS": "",
                "ddlCategory": DIR_CATEGORIES[spec["cat"]],
                "ddlPartSection": spec["part"],
                "ddlYear": spec["year"],
                "btnSubmit.x": "0",
                "btnSubmit.y": "0",
            },
        )
        return _post(url, url, body)

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        html = response.content.decode("utf-8", errors="replace")
        if "gvGazetteList" not in html:
            raise PermanentError(
                "gz_dir_search: session bounce or unexpected page (no result grid)"
            )
        rows = extract_rows(html)
        seeds = [_seed_file_task(row) for row in rows if is_federal(row["UGID"])]
        result = TaskResult(next_tasks=seeds)
        if not rows:
            spec = str(task.params.get("spec", ""))
            result.expected_empty = f"directory: no issues for {spec}"
        return result
