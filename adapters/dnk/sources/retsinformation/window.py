"""Task type ``rt_window``: one walk step over the documentsearch index.

GET ``/api/documentsearch?o=80&page=N&ps=100`` — rows sorted by
publication date descending, ``retsinfoLink`` prefix = publication medium
(probed equivalence with the documents' own "Offentliggjort i" field,
2026-09-15). Probed behaviours that shape this handler:

- the endpoint has **no server-side filters** (seven candidate parameter
  names all ignored, 2026-09-15) — window filtering is client-side;
- ``page`` is hard-capped at 99: page 100+ answers HTTP 200 with
  ``isError: true`` and no rows, even though ``pageCount`` claims 1939 —
  so a walk that reaches the cap before the window start stops without
  advancing the cursor (partially consumed window, explained empty);
- the walk terminal condition is "this page's oldest date < window
  start": everything from the newest index row down to FROM has then
  been seen, so the terminal page advances ``rt_last_date`` to TO;
- rows outside the gazette scope (retsinfo-only circulars, guidance,
  administrative decisions, parliamentary ft documents) never become
  seeds — default scope is Lovtidende A/B per the source contract.

LOV/LBK rows (timeline-capable types) route through ``rt_timeline`` so
the ``laws`` entity_ref is known when ``rt_doc`` registers the document;
everything else goes straight to ``rt_doc``.
"""

from __future__ import annotations

from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.dnk.sources.retsinformation import (
    API_BASE,
    CURSOR_KEY,
    TIMELINE_CODES,
    parse_dk_date,
)

__all__ = ["RtWindowHandler"]

_PAGE_SIZE = 100
_MAX_PAGE = 99


class RtWindowHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=f"{API_BASE}/api/documentsearch",
            params={"o": "80", "page": str(task.params["page"]), "ps": str(_PAGE_SIZE)},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        data: dict[str, Any] = response.json()
        page = int(task.params["page"])
        from_date = str(task.params["from"])
        to_date = str(task.params["to"])
        scope = {m.strip() for m in str(task.params.get("scope", "lta,ltb")).split(",")}
        timeline_on = str(task.params.get("timeline", "1")) == "1"
        max_docs = int(task.params["max_docs"]) if task.params.get("max_docs") else 0

        docs = data.get("documents") or []
        if data.get("isError"):
            # probed: pages beyond the 99-page cap answer isError with no rows
            if page == 0:
                raise ValueError("rt_window page 0: index answers isError (source broken?)")
            return TaskResult(
                expected_empty=(
                    f"rt_window: page {page} answers isError (page cap) before "
                    f"reaching window start {from_date} — window not fully "
                    "consumed, cursor not advanced"
                )
            )
        if not docs:
            if page == 0:
                raise ValueError("rt_window page 0: empty index")
            return TaskResult(
                expected_empty=(
                    f"rt_window: index walk ended at page {page} without reaching "
                    f"window start {from_date} (no rows) — window not fully consumed, "
                    "cursor not advanced"
                )
            )

        seeds: list[TaskSeed] = []
        min_date: str | None = None
        guard_hit = False
        for doc in docs:
            date_iso = parse_dk_date(doc.get("offentliggoerelsesDato"))
            if date_iso is None:
                continue
            if min_date is None or date_iso < min_date:
                min_date = date_iso
            link = (doc.get("retsinfoLink") or "").strip()
            media = link.strip("/").split("/")[1] if link.startswith("/eli/") else ""
            if media not in scope:
                continue
            if not (from_date <= date_iso <= to_date):
                continue
            if max_docs and len(seeds) >= max_docs:
                guard_hit = True
                break
            code = (doc.get("documentTypeEliCode") or "").strip().upper()
            if timeline_on and code in TIMELINE_CODES:
                seeds.append(
                    TaskSeed(
                        type="rt_timeline",
                        params={
                            "doc_num": str(doc.get("id")),
                            "eli": link,
                            "pub": date_iso,
                            "code": code,
                        },
                    )
                )
            else:
                seeds.append(TaskSeed(type="rt_doc", params={"eli": link, "pub": date_iso, "code": code}))

        terminal = min_date is not None and min_date < from_date
        cursor: dict[str, str] = {}
        if terminal:
            cursor = {CURSOR_KEY: to_date}

        next_tasks: list[TaskSeed] = []
        if not terminal and not guard_hit and len(docs) >= _PAGE_SIZE and page < _MAX_PAGE:
            next_tasks.append(
                TaskSeed(
                    type="rt_window",
                    params={**task.params, "page": str(page + 1)},
                )
            )

        result = TaskResult(next_tasks=seeds + next_tasks, cursor_updates=cursor)
        if result.is_empty():
            result.expected_empty = (
                f"rt_window page {page}: no {','.join(sorted(scope))} rows in "
                f"[{from_date},{to_date}]"
                + (" — walk complete, cursor advanced" if cursor else "")
            )
        return result
