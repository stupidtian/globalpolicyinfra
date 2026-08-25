"""The bills source: task-type registry and seed generation.

Task types (each = one module with ``build_request`` + ``parse``):

===============  =====================================================
type             what one task does
===============  =====================================================
bill_list_page   enumerate one page of a congress; spawns the next page
                 and (per ``deep`` mode) the bill's deep-crawl tasks
bill_detail      one bill's full metadata row + folder mirror file
bill_actions     one bill's lifecycle history (whole-list rewrite)
bill_summaries   one bill's latest CRS summary
bill_text        register the bill's text versions as documents;
                 spawn one download task per version
bill_text_dl     download one text version into the bill's folder
vote_list_page   one page of a session's roll calls; spawns the next page
                 and the session's vote-detail tasks
vote_detail      one roll call's question/result/party totals
===============  =====================================================

Params (key=value on the CLI)::

    congress=119            required
    deep=none|window|all    whether enumeration spawns deep crawls (default none)
    window=FROM:TO          with deep=window: bills introduced or updated in range
    cases=ID[,ID...]        always deep-crawl these bill_ids
    max_pages=N             stop the enumeration chain after N pages
    sessions=1,2            roll-call vote chains to crawl
    max_votes=N             cap vote-detail tasks per session chain
    sync=1                  incremental: enumerate only bills updated since
                            the kv cursor (bills_last_sync)

Deep selection is page-local by design: the list page carries each bill's
introduced and updated dates, so the country code never needs the database
(section 6.3 — packs are pure functions).
"""

from __future__ import annotations

from typing import Any

from adapters.base import SourceDefinition, TaskSeed
from adapters.usa.schema import DOMAIN_KEYS, DOMAIN_SCHEMA, DOMAIN_TABLES

__all__ = ["build_source"]


def _require(params: dict[str, Any], key: str) -> Any:
    value = params.get(key)
    if value in (None, ""):
        raise SystemExit(
            f"error: the bills source needs {key}=… "
            f"(e.g. python cli.py collect --country usa --source bills congress=119)"
        )
    return value


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    congress = int(_require(params, "congress"))
    seeds: list[TaskSeed] = []

    deep = str(params.get("deep", "none"))
    list_params: dict[str, Any] = {
        "congress": congress,
        "offset": 0,
        "page": 0,
        "deep": deep,
    }
    if params.get("window"):
        list_params["window"] = str(params["window"])
    if params.get("cases"):
        list_params["cases"] = [c.strip() for c in str(params["cases"]).split(",") if c.strip()]
    if params.get("max_pages"):
        list_params["max_pages"] = int(params["max_pages"])
    if str(params.get("sync", "")).strip() in ("1", "true", "yes"):
        kv = params.get("_kv", {})
        marker = kv.get("bills_last_sync")
        if marker:
            list_params["sync_from"] = marker
    seeds.append(TaskSeed(type="bill_list_page", params=list_params))

    sessions = str(params.get("sessions", "") or "").strip()
    if sessions:
        for raw in sessions.split(","):
            if raw.strip():
                seeds.append(
                    TaskSeed(
                        type="vote_list_page",
                        params={
                            "congress": congress,
                            "session": int(raw.strip()),
                            "offset": 0,
                            "quota_left": int(params["max_votes"])
                            if params.get("max_votes")
                            else None,
                        },
                    )
                )
    return seeds


def build_source() -> SourceDefinition:
    from adapters.usa.sources.bills.detail import (
        BillActionsHandler,
        BillDetailHandler,
        BillSummariesHandler,
    )
    from adapters.usa.sources.bills.enumerate import BillListPageHandler
    from adapters.usa.sources.bills.text import BillTextDownloadHandler, BillTextHandler
    from adapters.usa.sources.bills.votes import VoteDetailHandler, VoteListPageHandler

    return SourceDefinition(
        name="bills",
        start_tasks=start_tasks,
        task_types={
            "bill_list_page": BillListPageHandler(),
            "bill_detail": BillDetailHandler(),
            "bill_actions": BillActionsHandler(),
            "bill_summaries": BillSummariesHandler(),
            "bill_text": BillTextHandler(),
            "bill_text_dl": BillTextDownloadHandler(),
            "vote_list_page": VoteListPageHandler(),
            "vote_detail": VoteDetailHandler(),
        },
        domain_schema=DOMAIN_SCHEMA,
        domain_tables=DOMAIN_TABLES,
        domain_keys=DOMAIN_KEYS,
    )
