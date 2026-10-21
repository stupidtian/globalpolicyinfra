"""Task type ``uqn_sitemap_month``: one calendar month of the gazette.

GET the monthly sitemap and turn every in-scope item URL into a
``uqn_item`` seed. Two probed behaviours shape this handler (2026-10-10,
samples in the task folder):

- Item URLs come in two shapes — plain
  (``/decisions-and-regulations/{id}``) and category-prefixed
  (``/decisions-and-regulations/rules-and-regulations/{id}``) — and the
  same id can in principle appear in both. Both normalize to the plain
  canonical form here; the in-month seen-set collapses duplicates.
- Months before the last sitemap regeneration hold a frozen all-archive
  block (the same ids repeated in every stale month) rather than that
  month's items. The union-over-months design absorbs the duplication
  through task identity: same (id, kind) -> same task -> done-skip.

A month's cursor only advances once the month has *ended* — the current
month's sitemap keeps growing, so it is re-walked on every sync (watermark
= "confirmed consumed", not "visited").
"""

from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.sau.sources.uqn import CURSOR_KEY, SITE

__all__ = ["UqnSitemapMonthHandler"]

_DECISION_URL = re.compile(rf"^{SITE}/decisions-and-regulations/(?:[a-z-]+/)?(\d+)/?$")
_ADVERTISEMENT_URL = re.compile(rf"^{SITE}/advertisements/(\d+)/?$")


class UqnSitemapMonthHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        y, m = str(task.params["month"]).split("-")
        return RequestSpec(url=f"{SITE}/sitemaps/{int(y)}/{int(m)}/sitemap_0.xml")

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        month = str(task.params["month"])
        sections = set(str(task.params.get("sections", "decisions")).split(","))

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise ValueError(f"sitemap {month}: body is not XML: {exc}") from exc
        if not isinstance(root.tag, str) or not (
            root.tag.endswith("}urlset") or root.tag == "urlset"
        ):
            raise ValueError(
                f"sitemap {month}: unexpected root element {root.tag!r} "
                "(not a <urlset> — wrong month index?)"
            )

        y, m = (int(part) for part in month.split("-"))
        next_month = dt.date(y + 1, 1, 1) if m == 12 else dt.date(y, m + 1, 1)
        month_ended = next_month <= dt.datetime.now(dt.UTC).date()
        cursor: dict[str, str] = {CURSOR_KEY: month} if month_ended else {}

        seeds: list[TaskSeed] = []
        seen: set[tuple[str, str]] = set()
        for element in root.iter():
            tag = element.tag
            if not (isinstance(tag, str) and (tag.endswith("}loc") or tag == "loc")):
                continue
            loc = (element.text or "").strip()
            decision = _DECISION_URL.match(loc)
            if decision is not None:
                if "decisions" not in sections:
                    continue
                kind = "decisions"
                uqn_id = decision.group(1)
            else:
                advertisement = _ADVERTISEMENT_URL.match(loc)
                if advertisement is None:
                    continue  # news, old-era /details?p=, authors, …
                if "advertisements" not in sections:
                    continue
                kind = "advertisements"
                uqn_id = advertisement.group(1)
            if (uqn_id, kind) in seen:
                continue
            seen.add((uqn_id, kind))
            seeds.append(TaskSeed(type="uqn_item", params={"id": uqn_id, "kind": kind}))

        if not seeds:
            return TaskResult(
                expected_empty=(
                    f"sitemap {month}: no in-scope item URLs (sections="
                    f"{','.join(sorted(sections))})"
                ),
                cursor_updates=cursor,
            )
        return TaskResult(next_tasks=seeds, cursor_updates=cursor)
