"""Task type ``gazette_day``: one calendar day of the New Zealand Gazette.

One request: the DigitalNZ day query with ``per_page=100``,
``facets=collection`` and ``facets_per_page=50``. Probed behaviours that
shape this handler (2026-10-11/12, verbatim samples in the task folder):

- The envelope is ``{"api_terms_of_use": …, "search": {"facets", "page",
  "per_page", "request_url", "result_count", "results"}}``; any other
  shape dies loudly.
- **The collection facet partitions the day exactly**: the primary
  bucket ("The New Zealand Gazette") mirrors ``result_count``, and the
  type buckets sum to ``result_count`` (probed on a 25-notice and a
  350-notice day). A day violating either identity is an unexplained
  shape and dies loudly.
- **Busy days are never paginated.** The API's offset pagination is
  unreliable inside one day (rotating views: 4 pages of a 350-notice
  day carried 77 duplicate rows; 2-page days audited 3-of-6 short —
  probed 2026-10-12); ``sort`` is ignored (``sort=id`` answers HTTP
  500) and ``per_page`` is hard-capped at 100. A day with
  ``result_count <= 100`` is complete in its single response. A busier
  day is *sliced*: one ``gazette_slice`` per non-empty type bucket,
  carrying the facet count as the slice's expected total (each slice
  re-reconciles against it). Single-page slices are complete by
  construction; slicing reproduced the probe day exactly (24 slices,
  sum 350 = union 350 = total).

A no-notice day (weekends, holidays, pre-2000 dates) is a fully
consumed day: explained empty and the ``gazette_last_date`` cursor
advances. On busy days the cursor advances once the slices are seeded —
slice health is visible in task accounting and the per-year count
audit, not in the cursor (the ESP daily-summary precedent).
"""

from __future__ import annotations

from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.nzl.sources.gazette import (
    API_BASE,
    COLLECTION,
    CURSOR_KEY,
    PAGE_SIZE,
    PRIMARY_COLLECTION_FACET,
)
from adapters.nzl.sources.gazette.notice import records_to_documents

__all__ = ["GazetteDayHandler"]

_FACET_PAGE = 50  # > the largest probed type vocabulary (~22 names/day)


class GazetteDayHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        day = str(task.params["date"])
        return RequestSpec(
            url=f"{API_BASE}/records.json",
            params={
                "and[primary_collection]": COLLECTION,
                "and[date]": f"{day} TO {day}",
                "per_page": PAGE_SIZE,
                "facets": "collection",
                "facets_per_page": _FACET_PAGE,
            },
            headers={"Accept": "application/json"},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        day = str(task.params["date"])

        payload = response.json()
        search = payload.get("search") if isinstance(payload, dict) else None
        if not isinstance(search, dict) or not isinstance(search.get("results"), list):
            raise ValueError(  # noqa: TRY004 — an unexplained shape, not a caller bug
                f"gazette {day}: unexpected response shape — no search.results "
                f"object (top-level keys: {sorted(payload) if isinstance(payload, dict) else type(payload).__name__})"
            )
        results: list[Any] = search["results"]
        raw_count = search.get("result_count")
        if not isinstance(raw_count, int):
            raise ValueError(  # noqa: TRY004 — an unexplained shape, not a caller bug
                f"gazette {day}: result_count missing or not an integer ({raw_count!r})"
            )
        if raw_count == 0:
            # Empty day: nothing to partition, nothing to audit. The API
            # answers two probed facet shapes here — a bare ``{}``
            # (2026-10-10 probe) and ``{"collection": {}}`` (2000s
            # weekends) — both covered by short-circuiting before the
            # facet audit.
            return TaskResult(
                expected_empty=(
                    f"no gazette notices for {day} (weekend, holiday, or pre-2000 date)"
                ),
                cursor_updates={CURSOR_KEY: day},
            )
        raw_facets = search.get("facets")
        facets: dict[str, Any] = raw_facets if isinstance(raw_facets, dict) else {}
        collection_facet = facets.get("collection")
        if not isinstance(collection_facet, dict):
            raise ValueError(  # noqa: TRY004 — an unexplained shape, not a caller bug
                f"gazette {day}: the collection facet block is missing — the day "
                "cannot be audited or sliced"
            )

        # The exact-partition identity (probed invariant): the primary
        # bucket mirrors the total and the type buckets sum to it.
        type_buckets = {
            str(name): int(count)
            for name, count in collection_facet.items()
            if name != PRIMARY_COLLECTION_FACET
        }
        if not type_buckets or sum(type_buckets.values()) != raw_count:
            # Void-classification day (2019 transition era, probed
            # 2026-10-12: records carry empty collection membership, the
            # facet block is empty even on 12-40-notice days). No slice
            # axis exists — but a single response is still the whole day
            # when it fits one page. Beyond a page the day is unfixable
            # by slicing and dies loudly for targeted repair.
            if raw_count <= PAGE_SIZE:
                if len(results) != raw_count:
                    raise ValueError(
                        f"gazette {day}: result_count {raw_count} but response "
                        f"carries {len(results)} records"
                    )
                documents, files = records_to_documents(results, day)
                result = TaskResult(
                    documents=documents,
                    files=files,
                    cursor_updates={CURSOR_KEY: day},
                )
                if not documents:
                    result.expected_empty = (
                        f"no gazette notices for {day} (weekend, holiday, or pre-2000 date)"
                    )
                return result
            raise ValueError(
                f"gazette {day}: {raw_count} notices but no collection classification "
                "— cannot slice beyond a single page, needs targeted repair"
            )
        if collection_facet.get(PRIMARY_COLLECTION_FACET) != raw_count:
            raise ValueError(
                f"gazette {day}: primary facet "
                f"{collection_facet.get(PRIMARY_COLLECTION_FACET)!r} != result_count "
                f"{raw_count} — exact-partition identity broken"
            )

        if raw_count <= PAGE_SIZE:
            # Small day: the single response is the whole day.
            if len(results) != raw_count:
                raise ValueError(
                    f"gazette {day}: result_count {raw_count} but response carries "
                    f"{len(results)} records"
                )
            documents, files = records_to_documents(results, day)
            result = TaskResult(
                documents=documents,
                files=files,
                cursor_updates={CURSOR_KEY: day},
            )
            if not documents:
                result.expected_empty = (
                    f"no gazette notices for {day} (weekend, holiday, or pre-2000 date)"
                )
            return result

        # Busy day: slice every non-empty type bucket, each slice carrying
        # its facet count as the expected total (re-reconciled on arrival).
        seeds = [
            TaskSeed(
                type="gazette_slice",
                params={"date": day, "collection": name, "expected": str(count)},
            )
            for name, count in sorted(type_buckets.items())
            if count > 0
        ]
        return TaskResult(next_tasks=seeds, cursor_updates={CURSOR_KEY: day})
