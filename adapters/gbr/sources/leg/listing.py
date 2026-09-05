"""Task type ``leg_list``: one page of a type-year list feed.

``/{type}/{year}/data.feed`` enumerates every item of legislation of that
type and year (probed 2026-09-03: 100 per page with ``results-count``,
``<link rel="next">`` chaining, ``leg:morePages`` as a page estimate).
Entries carry the work id URI, an (xhtml-wrapped) title, the site's
``atom:updated`` stamp and the item's type/year/number.

Two probed quirks live here: the uksi list **mixes in wsi-canonical
items** (they share the numbering series — the first entry of the 2024
feed is wsi/2024/1395), so scope filtering happens per entry on the id
URI's first path segment; and some entries carry no ``ukm:CreationDate``,
so the enactment date is always taken from the item XML in ``leg_enacted``
(the feed's date, when present, travels in the task params as a fallback.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urlparse

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.gbr.sources.leg import PAGE_SIZE, SITE, USER_AGENT, _xml, item_key

__all__ = ["LegListHandler"]


class LegListHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        item_type = str(task.params["type"])
        year = str(task.params["year"])
        page = int(task.params.get("page", 1))
        return RequestSpec(
            url=f"{SITE}/{item_type}/{year}/data.feed",
            params={"page": str(page), "results-count": str(PAGE_SIZE)},
            headers={"User-Agent": USER_AGENT},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        if response.status_code != 200:
            raise ValueError(f"list feed returned HTTP {response.status_code}")
        root = ET.fromstring(response.content)

        scope = {t for t in str(task.params.get("types", "")).split(",") if t}
        rows: list[dict[str, Any]] = []
        seeds: list[TaskSeed] = []
        for entry in _xml.children(root, "entry"):
            id_el = _xml.first_child(entry, "id")
            uri = (id_el.text or "").strip() if id_el is not None else ""
            if not uri:
                raise ValueError("feed entry without an id element")
            segments = [s for s in urlparse(uri).path.split("/") if s]
            if segments and segments[0] == "id":
                segments = segments[1:]
            if len(segments) < 3:
                raise ValueError(f"unrecognised legislation id URI {uri!r}")
            item_type, year, number = segments[0], segments[1], segments[2]
            if item_type not in scope:
                continue

            title_el = _xml.first_child(entry, "title")
            title = _xml.texts(title_el) or f"{item_type}/{year}/{number}"
            updated_el = _xml.first_child(entry, "updated")
            updated = (updated_el.text or "").strip()[:19] if updated_el is not None else ""
            creation = ""
            creation_el = _xml.find_deep(entry, "CreationDate")
            if creation_el is not None:
                creation = creation_el.get("Date", "")

            rows.append(
                {
                    "item_key": item_key(item_type, year, number),
                    "uri": uri,
                    "title": title,
                    "native_type": item_type,
                    "year": year,
                    "number": number,
                    "updated": updated or None,
                }
            )
            seeds.append(
                TaskSeed(
                    type="leg_enacted",
                    params={
                        "type": item_type,
                        "year": year,
                        "number": number,
                        "title": title,
                        "creation_date": creation,
                    },
                    signal=updated or None,
                )
            )

        result = TaskResult(upsert_rows={"items": rows}, next_tasks=seeds)
        has_next = any(
            link.get("rel") == "next" for link in _xml.children(root, "link")
        )
        if has_next:
            result.next_tasks.append(
                TaskSeed(
                    type="leg_list",
                    params={**task.params, "page": int(task.params.get("page", 1)) + 1},
                )
            )
        elif not rows:
            result.expected_empty = (
                f"no in-scope items on this page of "
                f"{task.params.get('type')}/{task.params.get('year')}"
            )
        return result
