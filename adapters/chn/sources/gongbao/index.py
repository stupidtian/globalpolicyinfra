"""Task type ``gongbao_index``: the issue catalog, filtered to one year.

The catalog (``/gongbao/gbgl.json``, probed 2026-10-02) is one JSON document
covering every gazette issue of 2000–2026 (937 issues)::

    [{"values": {"2026年": {"第27号": {"gname": "https://www.gov.cn/gongbao/2026/issue_13006/",
                                        "issue": "第27号", "channelId": "35201", …}},
                 "2000年": {"第1号": {… "gname": "https://www.gov.cn/gongbao/2000/issue_1/" …}},
                 …}}]

Issue names are uniformly ``第N号`` (no special-issue shapes in the catalog;
the ``iszk`` flag is 0 across the corpus). The catalog's ``gname`` path
below ``/gongbao/`` is the **sole addressing authority** and comes in three
probed shapes (2026-10-02): the modern ``{year}/issue_{id}`` (25 years),
legacy bare-number folders ``2001/2006`` (8 entries across the 2000s), and
**2007's whole year re-homed** under a different first segment
(``201701/issue_1275`` — verified to serve 2007 content live). The path
travels verbatim in the spawned task's params; only the URL's overall shape
is validated, because the catalog — not any naming convention — decides
where an issue lives.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.chn.sources.gongbao import BASE_URL, CATALOG_URL

__all__ = ["GongbaoIndexHandler"]

_ISSUE_KEY_RE = re.compile(r"^第(\d+)号$")
_GBAO_PATH = "/gongbao/"
_EXPECTED_HOST = urlparse(BASE_URL).netloc


def parse_issue_path(gname: str) -> str:
    """The catalog gname → its path below ``/gongbao/`` (two segments).

    Loud on anything that is not a canonical ``{BASE_URL}/gongbao/{a}/{b}``
    URL: the entry cannot be addressed without its path, and inventing a
    fallback would be guessing. The first segment is NOT required to be the
    catalog year — 2007's issues all live under ``201701/`` (probed live,
    2026-10-02).
    """
    parsed = urlparse(str(gname))
    path = parsed.path.rstrip("/")
    if (
        parsed.scheme not in ("http", "https")
        or parsed.netloc != _EXPECTED_HOST
        or not path.startswith(_GBAO_PATH)
    ):
        raise ValueError(
            f"catalog gname {gname!r} is not a {BASE_URL}/gongbao/ URL"
        )
    parts = path[len(_GBAO_PATH):].split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError(
            f"catalog gname {gname!r} does not resolve to /gongbao/<a>/<b>"
        )
    return f"{parts[0]}/{parts[1]}"


class GongbaoIndexHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=CATALOG_URL)

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        year = str(task.params["year"])
        if response.status_code != 200:
            raise ValueError(f"gongbao catalog returned HTTP {response.status_code}")

        data = response.json()
        if (
            not isinstance(data, list)
            or not data
            or not isinstance(data[0].get("values"), dict)
        ):
            raise ValueError("gongbao catalog carries no values object")
        values = data[0]["values"]

        year_key = f"{year}年"
        if year_key not in values:
            raise ValueError(
                f"gongbao catalog holds no {year_key} (catalog is the authority "
                "on existing years — check the years parameter)"
            )

        entries: list[tuple[int, str, str]] = []
        for issue_key, info in values[year_key].items():
            issue_no = _ISSUE_KEY_RE.match(issue_key)
            if issue_no is None:
                # Unseen catalog shapes are production shapes — loud, never
                # silently dropped (section 7 discipline).
                raise ValueError(
                    f"catalog entry key {issue_key!r} does not match the probed 第N号 shape"
                )
            issue_path = parse_issue_path(info.get("gname", ""))
            entries.append((int(issue_no.group(1)), issue_path, issue_key))
        if not entries:
            return TaskResult(
                expected_empty=f"catalog {year_key} holds zero issues (probed "
                "shape always has ≥27 — treat as source-side structural change)"
            )

        # Newest first (a trial window wants the current issues); the cap is
        # per year because the task is per year.
        entries.sort(reverse=True)
        max_issues = task.params.get("max_issues")
        if isinstance(max_issues, int):
            entries = entries[:max_issues]

        seeds = [
            TaskSeed(
                type="gongbao_issue",
                params={
                    "year": year,
                    "issue_path": issue_path,
                    "issue_no": str(issue_no),
                },
                signal=task.signal,  # a refresh re-walk must reach every issue
            )
            for issue_no, issue_path, _key in entries
        ]
        return TaskResult(next_tasks=seeds)
