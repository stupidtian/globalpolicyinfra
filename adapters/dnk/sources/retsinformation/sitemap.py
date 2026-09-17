"""Task type ``rt_sitemap``: sitemap backfill enumeration entry.

GET ``https://retsinformation.dk/sitemap.xml`` (index, page 0) then
``…/sitemap.xml?page=N`` (one urlset of 10,000 canonical URLs each,
~21 pages covering 1665-2026, probed 2026-09-15). The URLs carry media
and year but **no dates** — the years filter is applied to the path, and
documents fetched through this entry pass ``pub=""`` (doc_id dates as
00000000; the real date is recovered in meta ``dies_signi`` and, for
stub-era texts, ``doc_texts.publication_date``). This is the only
enumeration channel reaching behind the documentsearch index's 2024-04
window boundary; bulk backfill operations stay out of scope here.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.dnk.sources.retsinformation import SITEMAP_INDEX

__all__ = ["RtSitemapHandler"]

_HOST_PREFIXES = ("https://retsinformation.dk", "https://www.retsinformation.dk")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_years(spec: str) -> tuple[int, int]:
    lo, _, hi = spec.strip().partition(":")
    if not hi:
        hi = lo
    return int(lo), int(hi)


class RtSitemapHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        page = int(task.params["page"])
        url = SITEMAP_INDEX if page == 0 else f"{SITEMAP_INDEX}?page={page}"
        return RequestSpec(url=url)

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        page = int(task.params["page"])
        years_spec = str(task.params["years"])
        scope = {m.strip() for m in str(task.params.get("scope", "lta,ltb")).split(",")}
        max_docs = int(task.params["max_docs"]) if task.params.get("max_docs") else 0

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise ValueError(f"rt_sitemap page {page}: body is not XML: {exc}") from exc

        locs = [
            (node.text or "").strip()
            for node in root.iter()
            if _local(node.tag) == "loc" and node.text
        ]

        if page == 0:
            page_nums = sorted(n for loc in locs if (n := _page_num(loc)) is not None)
            if not page_nums:
                raise ValueError("rt_sitemap index: no ?page= entries found")
            page_seeds = [
                TaskSeed(type="rt_sitemap", params={**task.params, "page": str(n)})
                for n in page_nums
            ]
            return TaskResult(next_tasks=page_seeds)

        lo_year, hi_year = _parse_years(years_spec)
        seeds: list[TaskSeed] = []
        for loc in locs:
            if not loc.startswith("/eli/"):
                for prefix in _HOST_PREFIXES:
                    if loc.startswith(prefix):
                        loc = loc[len(prefix):]
                        break
            if not loc.startswith("/eli/"):
                continue
            parts = loc.strip("/").split("/")
            if len(parts) < 4 or parts[1] not in scope:
                continue
            try:
                year = int(parts[2])
            except ValueError:
                continue
            if not lo_year <= year <= hi_year:
                continue
            if max_docs and len(seeds) >= max_docs:
                break
            seeds.append(TaskSeed(type="rt_doc", params={"eli": loc, "pub": ""}))

        if not seeds:
            return TaskResult(
                expected_empty=(
                    f"rt_sitemap page {page}: no {','.join(sorted(scope))} URLs "
                    f"in years {years_spec}"
                )
            )
        return TaskResult(next_tasks=seeds)


def _page_num(loc: str) -> int | None:
    import re

    match = re.search(r"\?page=(\d+)$", loc)
    return int(match.group(1)) if match else None
