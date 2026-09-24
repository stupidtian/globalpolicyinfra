"""Task type ``tad_list``: one day of one scope slice, one page.

GET the legacy search (``dokpaieska.rezult_l`` on www.lrs.lt, an Oracle
mod_plsql endpoint) and turn every result row into a ``tad_doc`` seed.
Probed behaviours shaping this handler (2026-09-15, samples in the task
folder):

- The response is windows-1257 HTML; the row count lives in
  ``Iš viso - <b>N</b>``. A zero total is a clean answer (HTTP 200) and
  a fully consumed slice: expected_empty, and the day cursor still
  advances (empty windows are confirmed-consumed, USA precedent).
- Pages hold 30 rows and pagination is *stateless*: ``p_no=N`` works
  without the ``p_sess`` key the page's own links carry. When the total
  exceeds this page's reach, the next page is seeded with the same
  window/slice params — the deterministic task identity makes re-runs
  idempotent.
- **Deep-pagination wall**: the endpoint serves at most 510 rows per
  query window (page 17 is the last with content; page 18+ answers
  200 with the correct total but zero rows — probed 2026-09-21 on
  Dec 2020, 841 orders). When a page comes back empty while its offset
  is still inside the total, the window is split into two halves and
  re-enumerated (the split children carry the same deterministic task
  identity, so rows already collected are done-skipped); a single-day
  window cannot split and fails loud.
- Rows carry the TAR registration, entry-into-force date and a
  ``PAKEISTAS`` marker inline, but the ``tad_doc`` detail is the
  authority: seeds travel light (``p_id`` only).
"""

from __future__ import annotations

import re
from datetime import date as date_cls
from datetime import timedelta

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.ltu.sources.tad import API_BASE, CURSOR_KEY, PAGE_CAP, PAGE_SIZE, decode_response

__all__ = ["TadListHandler"]

_TOTAL_RE = re.compile(r"Iš viso\s*-\s*<b>(\d+)</b>")
_ROW_RE = re.compile(r'class="dpav"[^>]*>\s*<a[^>]+href="[^"]*p_id=(\d+)')


class TadListHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        date_from = str(task.params["date"])
        date_to = str(task.params.get("to", date_from))
        page = int(str(task.params.get("page", "1")))
        return RequestSpec(
            url=f"{API_BASE}/dokpaieska.rezult_l",
            params={
                "p_nuo": date_from,
                "p_iki": date_to,
                "p_org": str(task.params.get("org", "")),
                "p_drus": str(task.params["drus"]),
                "p_no": str(page),
                "p_tr1": "2",
                "p_tr2": "2",
                "p_rus": "1",
            },
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        date = str(task.params["date"])
        window_end = str(task.params.get("to", date))
        page = int(str(task.params.get("page", "1")))
        scope = str(task.params.get("scope", ""))
        html = decode_response(response.content)

        total_match = _TOTAL_RE.search(html)
        if total_match is None:
            raise ValueError(
                f"tad_list {date}..{window_end} scope={scope} page={page}: no 'Iš viso' "
                "total in the response — legacy search shape may have changed"
            )
        total = int(total_match.group(1))

        pids = _ROW_RE.findall(html)
        if not pids:
            if total == 0:
                return TaskResult(
                    expected_empty=(
                        f"{scope} slice of {date}..{window_end}: the register answers "
                        f"zero acts (Iš viso - {total})"
                    ),
                    cursor_updates={CURSOR_KEY: window_end},
                )
            if (page - 1) * PAGE_SIZE >= total:
                raise ValueError(
                    f"tad_list {date}..{window_end} scope={scope} page={page}: total is "
                    f"{total} but no result rows parsed — row markup may have changed"
                )
            if total <= PAGE_CAP:
                raise ValueError(
                    f"tad_list {date}..{window_end} scope={scope} page={page}: total "
                    f"{total} fits under the {PAGE_CAP}-row window yet the page is "
                    "empty — row markup may have changed"
                )
            # Deep-pagination wall: this page's offset is inside the total
            # but the endpoint no longer serves rows. Split the window in
            # half and re-enumerate; already-collected rows are done-skipped
            # by task identity. A one-day window cannot split — fail loud.
            window_from = date_cls.fromisoformat(date)
            window_to = date_cls.fromisoformat(window_end)
            if window_from >= window_to:
                raise ValueError(
                    f"tad_list {date} scope={scope}: {total} acts exceed the "
                    f"{PAGE_CAP}-row legacy window even for a single day"
                )
            mid = window_from + timedelta(days=(window_to - window_from).days // 2)
            seeds = [
                TaskSeed(
                    type="tad_list",
                    params=_window_params(task, window_from, mid),
                ),
                TaskSeed(
                    type="tad_list",
                    params=_window_params(task, mid + timedelta(days=1), window_to),
                ),
            ]
            return TaskResult(next_tasks=seeds)
        if len(pids) > PAGE_SIZE:
            raise ValueError(
                f"tad_list {date}..{window_end} scope={scope} page={page}: parsed "
                f"{len(pids)} rows, more than the {PAGE_SIZE}-row page — row markup "
                "may have changed"
            )

        seeds = [
            TaskSeed(type="tad_doc", params={"pid": pid, "scope": scope}) for pid in pids
        ]
        if total > page * PAGE_SIZE:
            next_params: dict[str, str] = {
                "date": date,
                "org": str(task.params.get("org", "")),
                "drus": str(task.params["drus"]),
                "page": str(page + 1),
                "scope": scope,
            }
            if window_end != date:
                next_params["to"] = window_end
            seeds.append(TaskSeed(type="tad_list", params=next_params))
        return TaskResult(next_tasks=seeds, cursor_updates={CURSOR_KEY: window_end})


def _window_params(task: TaskView, window_from: date_cls, window_to: date_cls) -> dict[str, str]:
    """Params for a re-enumeration child window (split fallback)."""
    params = {
        "date": window_from.isoformat(),
        "org": str(task.params.get("org", "")),
        "drus": str(task.params["drus"]),
        "page": "1",
        "scope": str(task.params.get("scope", "")),
    }
    if window_to != window_from:
        params["to"] = window_to.isoformat()
    return params
