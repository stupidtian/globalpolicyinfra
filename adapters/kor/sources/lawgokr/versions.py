"""Task type ``kor_versions``: one law's version timeline (the lineage).

``lsHstListR.do`` returns every version of the law identified by lsId —
current and historical, each row a separate version with its own seq::

    lsViewLsHst2('253527', '20230808', '19592', '20230808', 'Y', '0' , '타법개정');
    lsViewLsHst2('86330',  '20080328', '08995', '20080629', 'N', '0' , '제정');
                  seq       공포일      공포번호   시행일

A discovery-only task: no documents of its own — each version row spawns a
``kor_body`` (same endpoint, same response shape; probed on the 2008
original) and a ``kor_reason``. The current version's tasks already exist
from the body that spawned this one; deterministic task ids dedup them.
``lsId`` in the form is what selects the Korean-history branch — without
it the endpoint returns the empty English-history layer (probed).
"""

from __future__ import annotations

import re

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.kor.sources.lawgokr import (
    BASE_URL,
    body_params,
    canonical_body_url,
    xhr_headers,
)

__all__ = ["KorVersionsHandler"]

_ROW_RE = re.compile(
    r"lsViewLsHst2\('(\d+)',\s*'(\d+)',\s*'(\d+)',\s*'(\d+)'(?:\s*,\s*'(\w+)'\s*,\s*'(\d+)'\s*,\s*'([^']*)')?"
)


class KorVersionsHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        seq = str(task.params["seq"])
        ef_yd = str(task.params["ef_yd"])
        params = {**body_params(seq, ef_yd), "lsId": str(task.params["ls_id"])}
        return RequestSpec(
            url=f"{BASE_URL}/lsHstListR.do",
            params=params,
            headers=xhr_headers(canonical_body_url(seq, ef_yd)),
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        if response.status_code != 200:
            raise ValueError(f"version timeline returned HTTP {response.status_code}")
        text = response.content.decode("utf-8", errors="replace")

        rows = _ROW_RE.findall(text)
        if not rows:
            raise ValueError(
                f"version timeline of {task.params['seq']}/{task.params['ef_yd']} "
                "carries no lsViewLsHst2 rows"
            )

        # The timeline is one chain per law: fetch it once. Rows whose seq
        # equals this task's own seq (the spawning version plus any scheduled
        # siblings — current-effect and future-effect versions share the seq)
        # were already discovered by the list, so they are skipped here; only
        # genuinely historical versions (fresh seqs) are spawned, flagged so
        # their bodies do not re-fetch the same timeline.
        own_seq = str(task.params["seq"])
        next_tasks: list[TaskSeed] = []
        for seq, ef_yd in sorted({(s, e) for s, _a, _n, e, *_ in rows}):
            if seq == own_seq:
                continue
            next_tasks.append(
                TaskSeed(
                    type="kor_body",
                    params={"seq": seq, "ef_yd": ef_yd, "from_versions": True},
                )
            )
            next_tasks.append(TaskSeed(type="kor_reason", params={"seq": seq, "ef_yd": ef_yd}))
        return TaskResult(next_tasks=next_tasks)
