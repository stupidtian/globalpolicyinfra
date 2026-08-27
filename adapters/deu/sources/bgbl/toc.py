"""Task type ``bgbl_toc``: walk the toclevel tree to the selected issues.

One handler, three levels selected by ``params["level"]``:

- ``root``: the n=0 response; find the Teil I node by its stable label and
  spawn the part-level task (discovery instead of hardcoding node ids —
  self-healing if the site reindexes).
- ``part``: Teil I's children are years; match the requested year label.
- ``year``: the year's children are issues ("Nr. 7 vom 19.02.2020"); one
  bgbl_issue seed per issue that passes the window filter.

toclevel responses are session-free, so only the *download* chain depends
on the csrf passed through here.
"""

from __future__ import annotations

import re
from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.deu.sources.bgbl import BASE_URL, TEIL_LABELS, USER_AGENT

__all__ = ["BgblTocHandler"]

#: Issue-tree labels look like "Nr. 67 vom 30.12.2020".
_ISSUE_LABEL_RE = re.compile(r"^Nr\.\s*(\d+)\s+vom\s+(\d{2}\.\d{2}\.\d{4})$")


def _walk(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """All nodes of a toclevel response: every item plus its materialized
    children (grandchildren stay lazy as ``c: true`` and never materialize
    in this response shape)."""
    nodes: list[dict[str, Any]] = []
    for item in payload.get("items", []):
        nodes.append(item)
        children = item.get("c")
        if isinstance(children, list):
            nodes.extend(children)
    return nodes


class BgblTocHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        node_id = task.params.get("node_id", 0)
        return RequestSpec(
            url=f"{BASE_URL}/ajax.xav",
            params={"q": "toclevel", "n": str(node_id)},
            headers={"User-Agent": USER_AGENT},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        payload = response.json()
        params = dict(task.params)
        level = str(params["level"])

        if level == "root":
            return self._parse_root(payload, params)
        if level == "part":
            return self._parse_part(payload, params)
        if level == "year":
            return self._parse_year(payload, params)
        raise ValueError(f"unknown toc level {level!r}")

    def _parse_root(self, payload: dict[str, Any], params: dict[str, Any]) -> TaskResult:
        label = TEIL_LABELS[str(params["part"])]
        for node in _walk(payload):
            if node.get("l") == label:
                if "id" not in node:
                    raise ValueError(f"toc node {label!r} carries no id")
                return TaskResult(
                    next_tasks=[
                        TaskSeed(type="bgbl_toc", params={**params, "level": "part", "node_id": node["id"]})
                    ]
                )
        raise ValueError(f"part label {label!r} not found in toclevel root")

    def _parse_part(self, payload: dict[str, Any], params: dict[str, Any]) -> TaskResult:
        year = str(params["year"])
        for node in _walk(payload):
            if node.get("l") == year:
                if "id" not in node:
                    raise ValueError(f"year node {year!r} carries no id")
                return TaskResult(
                    next_tasks=[
                        TaskSeed(type="bgbl_toc", params={**params, "level": "year", "node_id": node["id"]})
                    ]
                )
        raise ValueError(
            f"year {year} not found in the {TEIL_LABELS[str(params['part'])]} tree "
            f"(archive covers 1949-2022)"
        )

    def _parse_year(self, payload: dict[str, Any], params: dict[str, Any]) -> TaskResult:
        wanted = params["issues"]
        seeds: list[TaskSeed] = []
        for node in _walk(payload):
            match = _ISSUE_LABEL_RE.match(str(node.get("l", "")))
            if not match:
                continue
            issue_nr = int(match.group(1))
            if wanted != "all" and issue_nr not in wanted:
                continue
            if "did" not in node:
                raise ValueError(f"issue node {node.get('l')!r} carries no did")
            seeds.append(
                TaskSeed(
                    type="bgbl_issue",
                    params={
                        "nonce": params["nonce"],
                        "csrf": params["csrf"],
                        "part": params["part"],
                        "year": params["year"],
                        "issue_nr": issue_nr,
                        "issue_label": str(node["l"]),
                        "did": str(node["did"]),
                    },
                )
            )
        if not seeds:
            return TaskResult(
                expected_empty=f"no issue of {params['year']} matches the window filter"
            )
        return TaskResult(next_tasks=seeds)
