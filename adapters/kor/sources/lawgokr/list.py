"""Task type ``kor_list``: one page of the current-law list — laws, not rows.

Row shape (probed 2026-08-29, stable across the corpus)::

    <li id="liBgcolor0"> <a href="#"
      onclick="lsViewWideAll('253527','20230808','liBgcolor0',$(this),'3','0','Y','81'); …"
      title="10ㆍ27법난 피해자의 명예회복 등에 관한 법률 [시행 2023. 8. 8.] [법률 제19592호, …]">

One law, one anchor (user ruling 2026-08-31): the list occasionally shows
the *same* seq on two rows — one amendment with staggered article-level
effective dates (probed 2026-08-31: both rows carry the identical
promulgation number, e.g. 대통령령 제36561호 with 시행 2026-08-04 and
2028-01-01). Those are effective-date views of one version, not two
discoveries: rows are deduplicated by seq (earliest effective date anchors
the law), and the version timeline (kor_versions) recovers every dated view
including future ones. A future-dated view is part of the law's lifecycle,
exactly like a historical version — it must not stand as a separate row.

Pagination: any page is one request away. A page beyond the last returns
HTTP 200 with zero rows (``expected_empty``); with ``walk=1`` the chain
self-terminates. ``max_laws`` caps kor_body spawns per page and, when it
bites, also stops walking (a trial window, not a partial crawl).

Repeatable discovery (user ruling 2026-08-31): a re-crawl must find new
laws without re-fetching stored ones. List tasks therefore accept a
``signal`` (the CLI's ``refresh=<timestamp>``) — the ledger's reopen rule
(section 6.5) re-executes the walk while done body tasks stay skipped, so
a refresh run costs the page reads plus whatever is genuinely new.
"""

from __future__ import annotations

import re

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.kor.sources.lawgokr import BASE_URL, PAGE_SIZE, list_params, xhr_headers

__all__ = ["KorListHandler"]

_ROW_RE = re.compile(
    r'<a\s+href="#"\s+onclick="lsViewWideAll\(\'(\d+)\',\'(\d+)\'[^"]*"\s+title="([^"]*)"',
    re.DOTALL,
)


class KorListHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=f"{BASE_URL}/lsScListR.do",
            params=list_params(int(task.params["pg"])),
            headers=xhr_headers(f"{BASE_URL}/lsSc.do?menuId=1&subMenuId=15&tabMenuId=81&query="),
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = dict(task.params)
        pg = int(params["pg"])
        if response.status_code != 200:
            raise ValueError(f"list page {pg} returned HTTP {response.status_code}")

        text = response.content.decode("utf-8", errors="replace")
        rows = _ROW_RE.findall(text)

        # One law one anchor: earliest effective date per seq (the in-force
        # view of the latest amendment; later-dated views are the same
        # amendment's staggered effective dates, recovered via the timeline).
        by_seq: dict[str, tuple[str, str]] = {}
        for seq, ef_yd, _title in rows:
            current = by_seq.get(seq)
            if current is None or ef_yd < current[0]:
                by_seq[seq] = (ef_yd, _title)
        seeds = [
            TaskSeed(type="kor_body", params={"seq": seq, "ef_yd": ef_yd})
            for seq, (ef_yd, _title) in sorted(by_seq.items())
        ]

        if not seeds:
            return TaskResult(
                expected_empty=f"list page {pg} holds no laws (beyond the last page — "
                "corpus end reached)"
            )

        max_laws = params.get("max_laws")
        cap = max_laws if isinstance(max_laws, int) else None
        capped = cap is not None and len(seeds) > cap
        if capped and cap is not None:
            seeds = seeds[:cap]

        next_tasks = list(seeds)
        full_page = len(rows) >= PAGE_SIZE
        if full_page and not capped and params.get("walk"):
            next_tasks.append(
                TaskSeed(
                    type="kor_list",
                    params={**params, "pg": pg + 1},
                    signal=task.signal,  # a refresh re-walk must reach every page
                )
            )
        return TaskResult(next_tasks=next_tasks)
