"""Task type ``gazette_slice``: one (day × collection-name) slice.

The repair channel for busy days (``result_count > 100``): the DigitalNZ
offset pagination is unreliable inside an *unfiltered* day query
(rotating views — probed 2026-10-12: 4 pages of a 350-notice day carried
77 duplicate rows; 2-page days audited 3-of-6 short), but the
``and[collection]`` filter carves the day into type-name subsets whose
pagination is stable — probed on the largest slice seen so far (121
notices: page 1 = 100 + page 2 = 21, union 121, zero duplicates,
2026-10-12). A single-page slice is complete by construction; a longer
slice may therefore chain pages like any well-behaved source, closing
on the first short page. Slicing reproduced the probe day exactly:
24 slices, sum 350 = union 350 = total.

The day task hands each slice its facet count as ``expected``; the
slice's own ``result_count`` must agree with it (two independent
measurements of the same subset) or the shape dies loudly.

A zero-notice slice is normal noise (the day task spawns only non-empty
facet buckets, but ``repair_days`` seeds the whole vocabulary
speculatively): explained empty, done.
"""

from __future__ import annotations

from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.nzl.sources.gazette import API_BASE, COLLECTION, PAGE_SIZE
from adapters.nzl.sources.gazette.notice import records_to_documents

__all__ = ["SLICE_TYPE", "GazetteSliceHandler"]

SLICE_TYPE = "gazette_slice"


class GazetteSliceHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        day = str(task.params["date"])
        name = str(task.params["collection"])
        page = int(task.params.get("page", 1))
        return RequestSpec(
            url=f"{API_BASE}/records.json",
            params={
                "and[primary_collection]": COLLECTION,
                "and[date]": f"{day} TO {day}",
                "and[collection]": name,
                "per_page": PAGE_SIZE,
                "page": page,
            },
            headers={"Accept": "application/json"},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        day = str(task.params["date"])
        name = str(task.params["collection"])
        page = int(task.params.get("page", 1))

        payload = response.json()
        search = payload.get("search") if isinstance(payload, dict) else None
        if not isinstance(search, dict) or not isinstance(search.get("results"), list):
            raise ValueError(  # noqa: TRY004 — an unexplained shape, not a caller bug
                f"gazette slice {day} / {name!r}: unexpected response shape — no "
                f"search.results object (top-level keys: "
                f"{sorted(payload) if isinstance(payload, dict) else type(payload).__name__})"
            )
        results: list[Any] = search["results"]
        raw_count = search.get("result_count")
        if not isinstance(raw_count, int):
            raise ValueError(  # noqa: TRY004 — an unexplained shape, not a caller bug
                f"gazette slice {day} / {name!r}: result_count missing or not an "
                f"integer ({raw_count!r})"
            )
        expected = task.params.get("expected")
        if expected is not None and str(raw_count) != str(expected):
            raise ValueError(
                f"gazette slice {day} / {name!r}: query total {raw_count} disagrees with "
                f"the day facet count {expected} — exact-partition identity broken"
            )
        remaining = raw_count - PAGE_SIZE * (page - 1)
        if len(results) != min(max(remaining, 0), PAGE_SIZE):
            raise ValueError(
                f"gazette slice {day} / {name!r}: page {page} carries {len(results)} "
                f"records (query total {raw_count}) — unexpected page shape"
            )

        documents, files = records_to_documents(results, day)
        if len(results) == PAGE_SIZE:
            # Full page: slice pagination is stable (probed) — chain to
            # the next page; the final short page closes the slice.
            return TaskResult(
                documents=documents,
                files=files,
                next_tasks=[
                    TaskSeed(type=SLICE_TYPE, params={**task.params, "page": page + 1})
                ],
            )
        result = TaskResult(documents=documents, files=files)
        if not documents:
            result.expected_empty = (
                f"collection {name!r} has no notices on {day} (speculative slice)"
            )
        return result
