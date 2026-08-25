"""Task type ``bill_list_page``: enumerate one page of a congress.

GET /v3/bill/{congress}?offset=N&limit=250 — every bill of the congress,
newest action first. Parse yields one bills row per item, the next-page
task (chain), and — depending on the ``deep`` mode — the deep-crawl seed
quartet for each qualifying bill, each carrying the item's updateDate as
the reopen signal (section 6.5: re-enumeration reopens a bill's tasks only
when Congress actually touched it).
"""

from __future__ import annotations

from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.usa.schema import bill_identity

__all__ = ["API_BASE", "PAGE_SIZE", "BillListPageHandler"]

API_BASE = "https://api.congress.gov/v3"
PAGE_SIZE = 250

#: Bill types the /bill endpoints enumerate (amendments live elsewhere).
_BILL_TYPES = {"HR", "S", "HRES", "SRES", "HJRES", "SJRES", "HCONRES", "SCONRES"}


def deep_seeds_for_item(item: dict[str, Any], params: dict[str, Any]) -> list[TaskSeed]:
    """Which deep tasks this list item should spawn (page-local selection —
    the item itself carries introduced/updated dates, so no ledger access)."""
    bill_id, type_lower, number_str = bill_identity(
        int(item["congress"]), str(item["type"]), item["number"]
    )
    params = dict(params)
    cases = params.get("cases") or []
    mode = params.get("deep", "none")
    if mode == "none" and not cases:
        return []
    if mode == "all" or cases and bill_id in cases:
        qualifies = True
    elif mode == "window" and params.get("window"):
        from_str, _, to_str = str(params["window"]).partition(":")
        introduced = str(item.get("introducedDate") or "")
        updated = str(item.get("updateDate") or "")[:10]
        qualifies = (from_str <= introduced <= to_str) or (from_str <= updated <= to_str)
    else:
        qualifies = False
    if not qualifies:
        return []
    signal = str(item.get("updateDate") or "") or None
    common = {"congress": int(item["congress"]), "type": type_lower, "number": number_str}
    return [
        TaskSeed(type="bill_detail", params=dict(common), signal=signal),
        TaskSeed(type="bill_actions", params=dict(common), signal=signal),
        TaskSeed(type="bill_text", params=dict(common), signal=signal),
        TaskSeed(type="bill_summaries", params=dict(common), signal=signal),
    ]


class BillListPageHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        params: dict[str, Any] = {
            "offset": task.params["offset"],
            "limit": PAGE_SIZE,
        }
        if task.params.get("sync_from"):
            params["fromDateTime"] = f"{task.params['sync_from']}T00:00:00Z"
        return RequestSpec(
            url=f"{API_BASE}/bill/{task.params['congress']}",
            params=params,
            key_env="CONGRESS_API_KEY",
            key_param="api_key",
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        payload = response.json()
        items = payload.get("bills", [])
        params = task.params

        rows = []
        next_tasks: list[TaskSeed] = []
        for item in items:
            bill_id, _, _ = bill_identity(int(item["congress"]), str(item["type"]), item["number"])
            latest = item.get("latestAction") or {}
            rows.append(
                {
                    "bill_id": bill_id,
                    "congress": int(item["congress"]),
                    "bill_type": str(item["type"]).upper(),
                    "number": str(item["number"]),
                    "title": item.get("title"),
                    "introduced_date": item.get("introducedDate"),
                    "latest_action_date": latest.get("actionDate"),
                    "latest_action_text": latest.get("text"),
                    "api_update_date": item.get("updateDate"),
                }
            )
            next_tasks.extend(deep_seeds_for_item(item, params))

        # chain the next page until the API runs out or max_pages says stop
        pagination = payload.get("pagination") or {}
        count = int(pagination.get("count") or 0)
        offset = int(params.get("offset", 0))
        page_index = int(params.get("page", 0))
        max_pages = params.get("max_pages")
        more_pages = offset + PAGE_SIZE < count
        if more_pages and (max_pages is None or page_index + 1 < int(max_pages)):
            chain_params = dict(params)
            chain_params["offset"] = offset + PAGE_SIZE
            chain_params["page"] = page_index + 1
            next_tasks.append(TaskSeed(type="bill_list_page", params=chain_params))

        result = TaskResult(upsert_rows={"bills": rows}, next_tasks=next_tasks)
        # a sync sweep ends at the last page: stamp the cursor for next time
        is_last_page = not more_pages
        if is_last_page and params.get("sync_from"):
            from datetime import UTC, datetime

            result.cursor_updates = {
                "bills_last_sync": datetime.now(UTC).date().isoformat()
            }
        return result
