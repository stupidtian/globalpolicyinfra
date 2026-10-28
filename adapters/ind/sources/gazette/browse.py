"""GET-side handlers: the session seed and the two entry pages.

The session recipe (probed live 2026-10-04..15): the portal root 302s
into a cookieless ASP.NET session whose id lives in the URL path; every
deep request carries the *same* id in its path plus a Referer pointing
at that session's default.aspx — missing either bounces to error.aspx
(the web-archive crawler fate, not anti-bot). The adapter can never see
the final redirect URL (Response has no headers), so the session id is
parsed out of the rendered homepage as the modal ``(S(id))``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.ind.sources.gazette import (
    RECENT_CATEGORY,
    SITE,
    extract_hidden_state,
    extract_rows,
    extract_session_sid,
    is_federal,
    page_state_to_signal,
)
from runtime.errors import PermanentError

__all__ = ["GzDirOpenHandler", "GzHomeHandler", "GzRecentHandler"]

_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _iso_date(raw: str) -> str:
    """Grid dates are DD-Mon-YYYY (e.g. ``13-Oct-2026``); the ledger's
    publication_date and doc_id want ISO. An unparseable date stays
    verbatim (the framework records 00000000 doc_ids for missing dates —
    never invent one)."""
    parts = raw.strip().split("-")
    if len(parts) == 3:
        day, mon, year = parts
        try:
            return date(int(year), _MONTHS[mon.title()], int(day)).isoformat()
        except (KeyError, ValueError):
            pass
    return raw


def _seed_file_task(row: dict[str, str]) -> TaskSeed:
    params = {
        "ugid": row.get("UGID", ""),
        "pub": _iso_date(row.get("PublishDate", "")),
        "issue": _iso_date(row.get("IssueDate", "")),
        "category": row.get("Category", ""),
        "ministry": row.get("Ministry", ""),
        "department": row.get("Department", ""),
        "office": row.get("Office", ""),
        "subject": row.get("Subject", ""),
        "part": row.get("PartSection", ""),
        "file_size": row.get("FileSize", ""),
    }
    return TaskSeed(type="gz_file", params=params)


def _federal_file_seeds(html: str) -> tuple[list[TaskSeed], int]:
    rows = extract_rows(html)
    seeds = [_seed_file_task(row) for row in rows if is_federal(row["UGID"])]
    skipped = len(rows) - len(seeds)
    return seeds, skipped


class GzHomeHandler:
    """``gz_home``: GET the portal root; parse the modal session id and
    seed the entry chains requested on the command line. The per-run
    ``nonce`` in params (DEU session-seed precedent) gives the session
    task a fresh identity each run; downstream file tasks keep stable
    identities and stay done-skipped."""

    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=f"{SITE}/")

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        html = response.content.decode("utf-8", errors="replace")
        sid = extract_session_sid(html)
        seeds: list[TaskSeed] = []
        if str(task.params.get("recent", "")) == "1":
            seeds.append(TaskSeed(type="gz_recent", params={"sid": sid}))
        for spec in task.params.get("dir", []):
            seeds.append(TaskSeed(type="gz_dir_open", params={"sid": sid, "spec": str(spec)}))
        return TaskResult(next_tasks=seeds)


class GzRecentHandler:
    """``gz_recent``: one GET of the freshness window
    (RecentUploads Category=1, page 1 = newest 20 of ~100). Every
    federal (CG-DL) row seeds one file task; state-gazette rows are
    counted and skipped (out of scope by the country boundary)."""

    def build_request(self, task: TaskView) -> RequestSpec:
        sid = str(task.params["sid"])
        return RequestSpec(
            url=f"{SITE}/(S({sid}))/RecentUploads.aspx?Category={RECENT_CATEGORY}",
            headers={"Referer": f"{SITE}/(S({sid}))/default.aspx"},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        html = response.content.decode("utf-8", errors="replace")
        if "gvGazetteList_lbl_UGID_" not in html and "gvGazetteList" not in html:
            raise PermanentError(
                "gz_recent: session bounce or unexpected page (no result grid)"
            )
        seeds, skipped = _federal_file_seeds(html)
        result = TaskResult(next_tasks=seeds)
        if not seeds and skipped == 0 and "gvGazetteList" not in html:
            result.expected_empty = "recent window: grid present but no rows parsed"
        return result


class GzDirOpenHandler:
    """``gz_dir_open``: GET the GazetteDirectory filter page; capture
    its PostBack state into the chain's first page-state signal."""

    def build_request(self, task: TaskView) -> RequestSpec:
        sid = str(task.params["sid"])
        return RequestSpec(
            url=f"{SITE}/(S({sid}))/GazetteDirectory.aspx",
            headers={"Referer": f"{SITE}/(S({sid}))/default.aspx"},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        html = response.content.decode("utf-8", errors="replace")
        state = extract_hidden_state(html)
        return TaskResult(
            next_tasks=[
                TaskSeed(
                    type="gz_dir_cat",
                    params={"sid": str(task.params["sid"]), "spec": str(task.params["spec"])},
                    signal=page_state_to_signal(state),
                )
            ]
        )


def _require(value: Any, label: str) -> str:
    text = str(value)
    if not text:
        raise PermanentError(f"gazette chain task missing {label} in params")
    return text
