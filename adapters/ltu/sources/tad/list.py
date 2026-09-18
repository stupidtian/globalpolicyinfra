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
- Rows carry the TAR registration, entry-into-force date and a
  ``PAKEISTAS`` marker inline, but the ``tad_doc`` detail is the
  authority: seeds travel light (``p_id`` only).
"""

from __future__ import annotations

import re

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.ltu.sources.tad import API_BASE, CURSOR_KEY, PAGE_SIZE, decode_response

__all__ = ["TadListHandler"]

_TOTAL_RE = re.compile(r"Iš viso\s*-\s*<b>(\d+)</b>")
_ROW_RE = re.compile(r'class="dpav"[^>]*>\s*<a[^>]+href="[^"]*p_id=(\d+)')


class TadListHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        date = str(task.params["date"])
        page = int(str(task.params.get("page", "1")))
        return RequestSpec(
            url=f"{API_BASE}/dokpaieska.rezult_l",
            params={
                "p_nuo": date,
                "p_iki": date,
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
        page = int(str(task.params.get("page", "1")))
        scope = str(task.params.get("scope", ""))
        html = decode_response(response.content)

        total_match = _TOTAL_RE.search(html)
        if total_match is None:
            raise ValueError(
                f"tad_list {date} scope={scope} page={page}: no 'Iš viso' total in the "
                "response — legacy search shape may have changed"
            )
        total = int(total_match.group(1))

        pids = _ROW_RE.findall(html)
        if not pids:
            if total == 0:
                return TaskResult(
                    expected_empty=(
                        f"{scope} slice of {date}: the register answers zero acts "
                        f"(Iš viso - {total})"
                    ),
                    cursor_updates={CURSOR_KEY: date},
                )
            raise ValueError(
                f"tad_list {date} scope={scope} page={page}: total is {total} but no "
                "result rows parsed — row markup may have changed"
            )
        if len(pids) > PAGE_SIZE:
            raise ValueError(
                f"tad_list {date} scope={scope} page={page}: parsed {len(pids)} rows, "
                f"more than the {PAGE_SIZE}-row page — row markup may have changed"
            )

        seeds = [TaskSeed(type="tad_doc", params={"pid": pid}) for pid in pids]
        if total > page * PAGE_SIZE:
            seeds.append(
                TaskSeed(
                    type="tad_list",
                    params={
                        "date": date,
                        "org": str(task.params.get("org", "")),
                        "drus": str(task.params["drus"]),
                        "page": str(page + 1),
                        "scope": scope,
                    },
                )
            )
        return TaskResult(next_tasks=seeds, cursor_updates={CURSOR_KEY: date})
