"""Task types ``vote_list_page`` / ``vote_detail``: House roll-call headers.

GET /v3/house-vote/{congress}/{session} lists the session's roll calls;
each item already carries the vote's result and the legislation it was
about, so the list parse can write complete vote rows and link them to
bills (``legislationType HR 204`` → ``bills:USA_119_HR_204``).

Per-member votes are deferred (user decision 2026-08-25); when they return
they arrive as a new task type against the same votes table.

Senate roll calls do not exist in API v3 at all — the future browser
transport's first customer (senate.gov XML, ARCHITECTURE.md section 6.6).
"""

from __future__ import annotations

from typing import Any

from adapters.base import (
    FileOut,
    RequestSpec,
    Response,
    TaskResult,
    TaskSeed,
    TaskView,
)
from adapters.usa.schema import bill_identity
from adapters.usa.sources.bills.enumerate import API_BASE, PAGE_SIZE

_BILL_TYPES = {"HR", "S", "HRES", "SRES", "HJRES", "SJRES", "HCONRES", "SCONRES"}


def _bill_ref(congress: int, legislation_type: str, legislation_number: str) -> str | None:
    if legislation_type.strip().upper() not in _BILL_TYPES:
        return None  # amendment / procedural votes carry no bill backlink
    bill_id, _, _ = bill_identity(congress, legislation_type, legislation_number)
    return bill_id


def _vote_row(item: dict[str, Any]) -> dict[str, Any]:
    congress = int(item["congress"])
    session = int(item["sessionNumber"])
    roll = int(item["rollCallNumber"])
    leg_type = str(item.get("legislationType", ""))
    leg_number = str(item.get("legislationNumber", ""))
    return {
        "vote_id": f"USA_HOUSE_{congress}_{session}_{roll}",
        "chamber": "HOUSE",
        "congress": congress,
        "session": session,
        "roll_call_number": roll,
        "vote_date": str(item.get("startDate", ""))[:10] or None,
        "vote_type": item.get("voteType"),
        "result": item.get("result"),
        "bill_id": _bill_ref(congress, leg_type, leg_number),
        "legislation": f"{leg_type} {leg_number}".strip(),
        "source_url": item.get("sourceDataURL"),
    }


class VoteListPageHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=f"{API_BASE}/house-vote/{task.params['congress']}/{task.params['session']}",
            params={"offset": task.params["offset"], "limit": PAGE_SIZE},
            key_env="CONGRESS_API_KEY",
            key_param="api_key",
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        payload = response.json()
        items = payload.get("houseRollCallVotes", [])
        params = task.params

        rows = [_vote_row(item) for item in items]
        next_tasks: list[TaskSeed] = []
        quota_left = params.get("quota_left")

        for item, row in zip(items, rows, strict=False):
            if quota_left is not None and int(quota_left) <= 0:
                break
            next_tasks.append(
                TaskSeed(
                    type="vote_detail",
                    params={
                        "congress": row["congress"],
                        "session": row["session"],
                        "roll": row["roll_call_number"],
                        "bill_folder": None,
                    },
                    signal=str(item.get("updateDate") or "") or None,
                )
            )
            if quota_left is not None:
                quota_left = int(quota_left) - 1

        pagination = payload.get("pagination") or {}
        count = int(pagination.get("count") or 0)
        offset = int(params.get("offset", 0))
        if offset + PAGE_SIZE < count and (quota_left is None or int(quota_left) > 0):
            chain_params = dict(params)
            chain_params["offset"] = offset + PAGE_SIZE
            chain_params["quota_left"] = quota_left
            next_tasks.append(TaskSeed(type="vote_list_page", params=chain_params))

        return TaskResult(upsert_rows={"votes": rows}, next_tasks=next_tasks)


class VoteDetailHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=f"{API_BASE}/house-vote/{task.params['congress']}/{task.params['session']}/"
            f"{task.params['roll']}",
            key_env="CONGRESS_API_KEY",
            key_param="api_key",
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        v = response.json().get("houseRollCallVote") or {}
        congress = int(v.get("congress", task.params["congress"]))
        session = int(v.get("sessionNumber", task.params["session"]))
        roll = int(v.get("rollCallNumber", task.params["roll"]))
        leg_type = str(v.get("legislationType", ""))
        leg_number = str(v.get("legislationNumber", ""))
        totals = {
            str((entry.get("party") or {}).get("type", "?")): (
                f"{entry.get('yeaTotal', 0)}/{entry.get('nayTotal', 0)}/"
                f"{entry.get('notVotingTotal', 0)}/{entry.get('presentTotal', 0)}"
            )
            for entry in v.get("votePartyTotal") or []
        }
        row = {
            "vote_id": f"USA_HOUSE_{congress}_{session}_{roll}",
            "chamber": "HOUSE",
            "congress": congress,
            "session": session,
            "roll_call_number": roll,
            "vote_date": str(v.get("startDate", ""))[:10] or None,
            "vote_question": v.get("voteQuestion"),
            "vote_type": v.get("voteType"),
            "result": v.get("result"),
            "bill_id": _bill_ref(congress, leg_type, leg_number),
            "legislation": f"{leg_type} {leg_number}".strip(),
            "party_totals": totals,
            "source_url": v.get("sourceDataURL"),
        }
        files: list[FileOut] = []
        bill_ref = row["bill_id"]
        if isinstance(bill_ref, str) and bill_ref:
            # mirror into the voted-on bill's folder (human projection)
            parts = bill_ref.split("_", 3)
            folder = f"01_raw/bills/{parts[1]}/{parts[2]}{parts[3]}"
            files.append(FileOut(path=f"{folder}/votes/{row['vote_id']}.json",
                                 content=response.content))
        return TaskResult(upsert_rows={"votes": [row]}, files=files)
