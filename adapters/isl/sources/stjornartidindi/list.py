"""Task type ``stjornartidindi_list``: one slice of the lean listing.

``GET /api/v1/adverts-lean`` — the key-free gazette listing without
inline bodies (the full ``adverts`` endpoint embeds every document's
HTML, reaching 2.4 MB per page; lean is 6 KB for the same rows, probed
2026-09-17, samples in the task folder). Two enumeration axes, both
living in the task params (so re-scoping re-enumerates under new task
identities):

- ``axis=pubdate`` (incremental / recent backfill): ``dateFrom=dateTo=
  {day}``, sorted by publicationDate. Modern-era items enter the system
  in near real time, and late-crossing items (published under a *prior*
  volume year, e.g. 1759/2024 on 2025-01-09; 168 of 2,064 in 2024) land
  on their actual publication date, so the date axis captures them.
- ``axis=year`` (historical backfill): one (``year``, ``deild``) pair of
  the gazette volume axis (``publicationNumber.year``), sorted by
  publicationNumber, paged at the server's 100-row cap — the parse
  emits the next-page seed until ``paging.totalPages`` is exhausted.
  The volume axis never touches the day cursor.

Both axes answer "nothing there" with HTTP 200 and an empty
``adverts`` array (query-style API; no 404 semantics — probed on a
no-issue weekend). An empty pubdate day is a fully consumed slice: the
cursor advances (USA empty-window precedent). scope=state filters
municipal issuers at row level (the issuer rides in every lean row).
Rows are trusted to be self-describing: a row missing a required field
is a shape change and dies loud.
"""

from __future__ import annotations

from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.isl.sources.stjornartidindi import (
    API_BASE,
    CURSOR_KEY,
    is_municipal_issuer,
)

__all__ = ["ListHandler"]

_LIST_URL = f"{API_BASE}/api/v1/adverts-lean"


def _advert_seed(row: dict[str, Any], scope: str) -> TaskSeed:
    pub_number = row.get("publicationNumber") or {}
    involved = row.get("involvedParty") or {}
    deild = (row.get("department") or {}).get("slug") or ""
    native_type = (row.get("type") or {}).get("title") or ""
    return TaskSeed(
        type="stjornartidindi_advert",
        params={
            "id": str(row["id"]),
            "pub_num": str(pub_number.get("full") or ""),
            "year": str(pub_number.get("year") or ""),
            "title": str(row.get("title") or ""),
            "native_type": native_type,
            "deild": deild,
            "involved_party": str(involved.get("title") or ""),
            "pub_date": str(row.get("publicationDate") or ""),
            "scope_slice": scope,
        },
    )


class ListHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        params: dict[str, Any] = {"pageSize": 100}
        if str(task.params["axis"]) == "pubdate":
            day = str(task.params["date"])
            params.update(
                dateFrom=day,
                dateTo=day,
                sortBy="publicationDate",
                direction="ASC",
            )
        else:
            params.update(
                year=str(task.params["year"]),
                department=str(task.params["deild"]),
                sortBy="publicationNumber",
                direction="ASC",
            )
        page = str(task.params.get("page", "1"))
        if page != "1":
            params["page"] = page
        return RequestSpec(url=_LIST_URL, params=params)

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        axis = str(task.params["axis"])
        scope = str(task.params.get("scope", "state"))
        label = f"{axis}:{task.params.get('date') or task.params.get('year')}/{task.params.get('deild', '')}"
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(
                f"stjornartidindi_list {label}: body is not JSON: {exc}"
            ) from exc
        if "adverts" not in payload or "paging" not in payload:
            raise ValueError(
                f"stjornartidindi_list {label}: unexpected response shape "
                f"(keys={sorted(payload)!r}) — listing may have moved"
            )
        paging = payload["paging"] or {}
        try:
            page = int(paging.get("page") or task.params.get("page", "1"))
            total_pages = int(paging.get("totalPages") or 1)
        except (TypeError, ValueError):
            raise ValueError(
                f"stjornartidindi_list {label}: unusable paging block {paging!r}"
            ) from None
        rows = payload["adverts"] or []

        seeds: list[TaskSeed] = []
        kept = 0
        municipal = 0
        for row in rows:
            if not row.get("id") or not (row.get("publicationNumber") or {}).get("full"):
                raise ValueError(
                    f"stjornartidindi_list {label}: row without id/publicationNumber "
                    f"({ {k: row.get(k) for k in ('id', 'publicationNumber', 'title')} }) — "
                    "listing row shape may have changed"
                )
            involved = (row.get("involvedParty") or {}).get("title") or ""
            if scope == "state" and involved and is_municipal_issuer(involved):
                municipal += 1
                continue
            kept += 1
            seeds.append(_advert_seed(row, scope))

        results = TaskResult()
        if kept:
            results.next_tasks.extend(seeds)
        elif rows:
            results.expected_empty = (
                f"stjornartidindi_list {label}: all {len(rows)} listed adverts fall "
                f"outside scope={scope} (municipal issuers: {municipal})"
            )
        else:
            results.expected_empty = (
                f"stjornartidindi_list {label}: no adverts in this slice (clean "
                "empty answer of the query-style API)"
            )

        # The volume axis is fully stateless; the day cursor only moves
        # when the day's *last* page completed (a >100-item day continues
        # via the next page and advances nothing).
        if axis == "pubdate" and page >= total_pages:
            results.cursor_updates = {CURSOR_KEY: str(task.params["date"])}
        if page < total_pages:
            next_params = dict(task.params)
            next_params["page"] = str(page + 1)
            results.next_tasks.append(
                TaskSeed(type="stjornartidindi_list", params=next_params)
            )
        return results
