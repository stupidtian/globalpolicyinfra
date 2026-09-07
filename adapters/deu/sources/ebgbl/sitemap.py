"""Task type ``ebgbl_sitemap``: the whole Verkündung index in one request.

robots.txt points to ``XMLSitemaps/Sitemap_Verkuendungen.xml``; one GET
returns every eBGBl entry URL (2026-09-07: 2,876 URLs — Teil I 1,504,
Teil II 1,372). This is a live source: re-running the same command re-pulls
the sitemap, new URLs become new tasks, already-done entries are skipped
(no session state, so tasks are naturally resumable).
"""

from __future__ import annotations

import re

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.deu.sources.ebgbl import SITEMAP_URL, USER_AGENT

__all__ = ["EbgblSitemapHandler"]

#: Entry URLs look like https://www.recht.bund.de/bgbl/1/2023/12/VO.html
_ENTRY_RE = re.compile(r"/bgbl/([12])/(\d{4})/([^/]+)/VO\.html$")


class EbgblSitemapHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=SITEMAP_URL, headers={"User-Agent": USER_AGENT})

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        if response.status_code != 200:
            raise ValueError(f"sitemap returned HTTP {response.status_code}")
        xml = response.content.decode("utf-8", errors="replace")

        params = dict(task.params)
        part = str(params["part"])
        year = str(params["year"])
        wanted: list[str] | str = params["nrs"]

        seeds: list[TaskSeed] = []
        for loc in re.findall(r"<loc>([^<]+)</loc>", xml):
            match = _ENTRY_RE.search(loc.strip())
            if match is None:
                continue
            loc_part, loc_year, loc_nr = match.group(1), match.group(2), match.group(3)
            if loc_part != part or loc_year != year:
                continue
            if wanted != "all" and loc_nr not in wanted:
                continue
            seeds.append(
                TaskSeed(
                    type="ebgbl_entry",
                    params={"part": part, "year": params["year"], "nr": loc_nr},
                )
            )
        if not seeds:
            return TaskResult(
                expected_empty=f"no Verkündung of {part}/{year} matches the window filter"
            )
        return TaskResult(next_tasks=seeds)
