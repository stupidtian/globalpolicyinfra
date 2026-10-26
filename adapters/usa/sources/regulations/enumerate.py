"""Task type ``fr_list_page``: one page of a Federal Register date window.

GET /api/v1/documents.json with publication_date bounds, 1,000 per page —
every FR document published in the window. Parse yields one partial
``fr_documents`` row per item (the listing already carries most fields),
the next-page task while pages remain, and — when ``deep`` says so — an
``fr_detail`` seed per document.

FR documents are immutable once published (mistakes become separate
Correction documents), so unlike bills there is no reopen signal: an
already-fetched detail is simply never re-enqueued.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.usa.schema import fr_folder, president_name

__all__ = ["API_BASE", "LISTING_FIELDS", "PAGE_SIZE", "TYPE_CODES", "FrListPageHandler"]

API_BASE = "https://www.federalregister.gov/api/v1"
PAGE_SIZE = 1000

#: The API silently caps any query at 10,000 results: total_pages tops out
#: at PAGE_SIZE-strided 10 no matter how many documents actually match.
_API_CAP_PAGES = 10000 // PAGE_SIZE

#: Bisection floor: a window shorter than this cannot plausibly hit the cap
#: (~1% of a cap even for the heaviest rule years), so stop splitting there.
_BISECT_FLOOR_DAYS = 31

#: A fully swept window advances the sync cursor only when its end is at
#: the present edge (within this many days of today). Capped-window
#: bisection finishes sub-windows out of order; an old-ending window
#: stamping would move the watermark backwards on a coin flip.
_CURSOR_GRACE_DAYS = 7

#: Friendly type tokens -> the API's internal uppercase codes. The filter
#: takes the codes (``conditions[type][]=RULE``); the pretty names the JSON
#: returns ("Rule", "Proposed Rule") are NOT accepted by the filter.
TYPE_CODES: dict[str, str] = {
    "rule": "RULE",
    "proposed": "PRORULE",
    "notice": "NOTICE",
    "presidential": "PRESDOCU",
}

#: Ask for the rich field set so listing rows are near-complete on their own
#: (the detail endpoint adds subtype/dates/corrections/topics and friends).
LISTING_FIELDS: tuple[str, ...] = (
    "document_number",
    "title",
    "type",
    "publication_date",
    "abstract",
    "action",
    "citation",
    "volume",
    "start_page",
    "end_page",
    "html_url",
    "raw_text_url",
    "pdf_url",
    "agencies",
    "president",
    "executive_order_number",
    "proclamation_number",
    "docket_ids",
    "regulation_id_numbers",
    "cfr_references",
)


def _first_rin(rids: list[Any]) -> str | None:
    for rid in rids:
        if rid:
            return str(rid)
    return None


class FrListPageHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        params: dict[str, Any] = {
            "conditions[publication_date][gte]": task.params["from"],
            "conditions[publication_date][lte]": task.params["to"],
            "per_page": PAGE_SIZE,
            "page": int(task.params.get("page", 1)),
            "fields[]": list(LISTING_FIELDS),
        }
        # optional type filter, e.g. types=rule,proposed -> RULE+PRORULE only
        # (the lifecycle backfill skips NOTICE/PRESDOCU: ~83% of modern years)
        type_tokens = task.params.get("types") or []
        if type_tokens:
            params["conditions[type][]"] = [
                TYPE_CODES.get(str(t).strip().lower(), str(t).strip().upper())
                for t in type_tokens
            ]
        return RequestSpec(url=f"{API_BASE}/documents.json", params=params)

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        payload = response.json()
        items = payload.get("results", [])
        params = task.params

        rows = []
        next_tasks: list[TaskSeed] = []
        deep = params.get("deep", "none")
        cases = params.get("cases") or []
        for item in items:
            document_number = str(item.get("document_number") or "")
            if not document_number:
                continue
            publication_date = item.get("publication_date")
            rids = [str(r) for r in (item.get("regulation_id_numbers") or []) if r]
            rows.append(
                {
                    "document_number": document_number,
                    "publication_date": publication_date,
                    "title": item.get("title") or document_number,
                    "type": item.get("type"),
                    "abstract": item.get("abstract"),
                    "action": item.get("action"),
                    "citation": item.get("citation"),
                    "volume": item.get("volume"),
                    "start_page": item.get("start_page"),
                    "end_page": item.get("end_page"),
                    "agencies": item.get("agencies") or [],
                    "president": president_name(item.get("president")),
                    "executive_order_number": item.get("executive_order_number"),
                    "proclamation_number": item.get("proclamation_number"),
                    "docket_ids": item.get("docket_ids") or [],
                    "rins": rids,
                    "rin": _first_rin(rids),
                    "cfr_references": item.get("cfr_references") or [],
                    "html_url": item.get("html_url"),
                    "raw_text_url": item.get("raw_text_url"),
                    "pdf_url": item.get("pdf_url"),
                    "folder": fr_folder(str(publication_date), document_number),
                }
            )
            if deep == "all" or document_number in cases:
                next_tasks.append(
                    TaskSeed(
                        type="fr_detail",
                        params={
                            "document_number": document_number,
                            "formats": params.get("formats", "txt,xml"),
                        },
                    )
                )

        # chain the next page until the API runs out or max_pages says stop
        page = int(params.get("page", 1))
        total_pages = int(payload.get("total_pages") or 0)
        max_pages = params.get("max_pages")

        # A capped "fully swept" window is a lie — it both loses rows and
        # would forge the cursor. Split the window in half and sweep the
        # halves (page-1 rows still count); recursion bottoms out at
        # windows that genuinely fit under the cap.
        window_from = str(params["from"])[:10]
        window_to = str(params["to"])[:10]
        span = (date.fromisoformat(window_to) - date.fromisoformat(window_from)).days
        if page == 1 and total_pages >= _API_CAP_PAGES and span > _BISECT_FLOOR_DAYS:
            mid = date.fromisoformat(window_from) + timedelta(days=span // 2)
            halves = [
                {**params, "from": window_from, "to": mid.isoformat(), "page": 1},
                {
                    **params,
                    "from": (mid + timedelta(days=1)).isoformat(),
                    "to": window_to,
                    "page": 1,
                },
            ]
            return TaskResult(
                upsert_rows={"fr_documents": rows},
                next_tasks=[TaskSeed(type="fr_list_page", params=half) for half in halves],
            )

        more_pages = page < total_pages
        if more_pages and (max_pages is None or page < int(max_pages)):
            chain_params = dict(params)
            chain_params["page"] = page + 1
            next_tasks.append(TaskSeed(type="fr_list_page", params=chain_params))

        result = TaskResult(upsert_rows={"fr_documents": rows}, next_tasks=next_tasks)
        # FR is date-partitioned, so a complete sweep of a window at the
        # present edge advances the sync cursor to its end. Windows that
        # end in history (bisected backfill segments) never stamp — with
        # many sub-windows finishing out of order, an old end would move
        # the watermark backwards at random.
        if not more_pages:
            today = datetime.now(UTC).date()
            if (today - date.fromisoformat(window_to)).days <= _CURSOR_GRACE_DAYS:
                result.cursor_updates = {"fr_last_pub_date": window_to}
        return result
