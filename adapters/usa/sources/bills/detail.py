"""Task types ``bill_detail`` / ``bill_actions`` / ``bill_summaries``.

Three facets of one bill's metadata. Each parse writes its domain rows and
mirrors the raw response into the bill's per-policy folder (the human-
readable projection of §6.7 — the ledger stays the retrieval entry).
"""

from __future__ import annotations

from adapters.base import (
    FileOut,
    ReplaceRows,
    RequestSpec,
    Response,
    TaskResult,
    TaskView,
)
from adapters.usa.schema import bill_folder, bill_identity, terminal_status_from_actions
from adapters.usa.sources.bills.enumerate import API_BASE


def _identity(task: TaskView) -> tuple[str, str, str, str]:
    bill_id, type_lower, number_str = bill_identity(
        int(task.params["congress"]), str(task.params["type"]), str(task.params["number"])
    )
    folder = bill_folder(int(task.params["congress"]), type_lower, number_str)
    return bill_id, type_lower, number_str, folder


class BillDetailHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        _, type_lower, number_str, _ = _identity(task)
        return RequestSpec(
            url=f"{API_BASE}/bill/{task.params['congress']}/{type_lower}/{number_str}",
            key_env="CONGRESS_API_KEY",
            key_param="api_key",
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        bill = response.json().get("bill") or {}
        bill_id, _, _, folder = _identity(task)
        sponsor = (bill.get("sponsors") or [{}])[0] or {}
        latest = bill.get("latestAction") or {}
        row = {
            "bill_id": bill_id,
            "congress": int(bill.get("congress", task.params["congress"])),
            "bill_type": str(bill.get("type", task.params["type"])).upper(),
            "number": str(bill.get("number", task.params["number"])),
            "title": bill.get("title"),
            "introduced_date": bill.get("introducedDate"),
            "sponsor_bioguide": sponsor.get("bioguideId"),
            "sponsor_name": sponsor.get("fullName"),
            "sponsor_party": sponsor.get("party"),
            "sponsor_state": sponsor.get("state"),
            "policy_area": (bill.get("policyArea") or {}).get("name"),
            "latest_action_date": latest.get("actionDate"),
            "latest_action_text": latest.get("text"),
            "api_update_date": bill.get("updateDate"),
            "folder": folder,
        }
        return TaskResult(
            upsert_rows={"bills": [row]},
            files=[FileOut(path=f"{folder}/detail.json", content=response.content)],
        )


class BillActionsHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        _, type_lower, number_str, _ = _identity(task)
        return RequestSpec(
            url=f"{API_BASE}/bill/{task.params['congress']}/{type_lower}/{number_str}/actions",
            params={"limit": 250},
            key_env="CONGRESS_API_KEY",
            key_param="api_key",
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        payload = response.json()
        bill_id, _, _, folder = _identity(task)
        rows = [
            {
                "bill_id": bill_id,
                "seq": seq,
                "action_date": item.get("actionDate"),
                "action_type": item.get("type"),
                "action_code": item.get("actionCode"),
                "action_text": item.get("text"),
                "committees": [
                    c.get("systemCode")
                    for c in (item.get("committees") or [])
                    if c.get("systemCode")
                ],
            }
            for seq, item in enumerate(payload.get("actions", []))
        ]
        return TaskResult(
            replacements=[
                ReplaceRows(table="bill_actions", match={"bill_id": bill_id}, rows=rows)
            ],
            upsert_rows={
                "bills": [
                    {
                        "bill_id": bill_id,
                        "terminal_status": terminal_status_from_actions(rows),
                    }
                ]
            },
            files=[FileOut(path=f"{folder}/actions.json", content=response.content)],
        )


class BillSummariesHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        _, type_lower, number_str, _ = _identity(task)
        return RequestSpec(
            url=f"{API_BASE}/bill/{task.params['congress']}/{type_lower}/{number_str}/summaries",
            key_env="CONGRESS_API_KEY",
            key_param="api_key",
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        payload = response.json()
        bill_id, _, _, folder = _identity(task)
        summaries = payload.get("summaries") or []
        mirror = FileOut(path=f"{folder}/summaries.json", content=response.content)
        if not summaries:
            return TaskResult(expected_empty="bill has no CRS summary", files=[mirror])
        # API returns most recent first; keep the latest text whole.
        return TaskResult(
            upsert_rows={"bills": [{"bill_id": bill_id, "summary_text": summaries[0].get("text")}]},
            files=[mirror],
        )
