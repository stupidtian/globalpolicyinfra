"""Task type ``jorf_index``: read the directory listing, spawn day tasks.

The listing at BASE_URL is a plain Apache index (ISO-8859-1 HTML) naming
every archive since 2025-07-13. Three rules turn it into day tasks:

- keep only ``JORF_{YYYYMMDD}-{HHMMSS}.tar.gz`` (the Freemium global stock
  and the presentation PDFs are ignored);
- only archives generated before 12:00 are issue candidates — the daily
  issue lands between 00:15 and 07:00 (342/404 days, probed 2026-08-28),
  maintenance diffs after 20:30, and the 61 evening-only days are the
  edition-less Mondays plus a few early artifacts (the gazette publishes
  Tuesday–Sunday);
- a date may hold several pre-noon archives (rare re-pushes); the lexically
  smallest filename is the day's earliest, i.e. the issue as first published.

Days with no candidate archive simply produce no task; a window that
matches nothing is an explained empty result.
"""

from __future__ import annotations

import re

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.fra.sources.jorf import BASE_URL, USER_AGENT

__all__ = ["JorfIndexHandler"]

_FILE_RE = re.compile(r'href="JORF_(\d{8})-(\d{6})\.tar\.gz"')

#: Issue archives land 00:15–07:00, maintenance diffs after 20:30; noon is
#: the safety margin between the two clusters (404/404 days classified, 2026-08-28).
_NOON = "120000"


def _to_iso(ymd: str) -> str:
    return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"


class JorfIndexHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=f"{BASE_URL}/", headers={"User-Agent": USER_AGENT})

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        listing = response.content.decode("iso-8859-1")

        earliest: dict[str, str] = {}
        for ymd, hms in _FILE_RE.findall(listing):
            if hms >= _NOON:
                continue
            name = f"JORF_{ymd}-{hms}.tar.gz"
            current = earliest.get(ymd)
            if current is None or name < current:
                earliest[ymd] = name

        lo = str(task.params["from"]).replace("-", "")
        hi = str(task.params["to"]).replace("-", "")
        selected = sorted(
            (ymd, name) for ymd, name in earliest.items() if lo <= ymd <= hi
        )
        if not selected:
            return TaskResult(
                expected_empty=(
                    f"no daily archive in the directory for {task.params['from']}.."
                    f"{task.params['to']} (no edition published, or before 2025-07-13 "
                    "— history lives in the global stock archive)"
                )
            )
        return TaskResult(
            next_tasks=[
                TaskSeed(type="jorf_issue", params={"date": _to_iso(ymd), "filename": name})
                for ymd, name in selected
            ]
        )
