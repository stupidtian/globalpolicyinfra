"""Task type ``gongbao_issue``: one issue's table of contents.

The TOC page (probed 2026-10-02 on the 2026 and 2000 generations; samples
archived) is static HTML whose article list is a flat run of::

    <div class="box"><ul>
      <li><a href="./202609/content_7082254.html" target="_blank">
          共担时代责任 勇做先锋力量<br/>　——在…的讲话 ……… 中华人民共和国主席 习近平</a></li>
      …
    </ul></div>

Two link generations (both urljoin-resolved against the issue URL, never
hand-concatenated):

* 2026-era: ``./202609/content_7082252.html``
  → ``…/gongbao/2026/issue_13006/202609/content_7082252.html``
* 2000-era: ``../../content/2000/content_60538.htm``
  → ``…/gongbao/content/2000/content_60538.htm``

Only *article* links are entries — the page carries other relative links
(css, the search page, the 1954–1999 scan archive) and absolute ones
(sibling issues, the English edition). Across both generations the probed
article shape is a relative href whose basename is ``content_<id>.htm(l)``
(2026-10-02: both issue pages carry exactly that pattern; everything else
is navigation). The whole TOC line (title + dot leader + signing
authority) rides in the spawned doc task's params as ``toc``: it is
deterministic discovery data, and it is the only place the authority
suffix (``………… 机关``) exists for entries whose article page omits a
signature block.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.chn.sources.gongbao import (
    BASE_URL,
    issue_folder,
    issue_url,
    normalize_space,
)

__all__ = ["GongbaoIssueHandler", "parse_toc_line", "relative_article_path"]

_TOC_ROW_RE = re.compile(
    r'<a\s+href="(\.{1,2}/[^"]*content_\d+\.[hm]tm?l?)"[^>]*>(.*?)</a>', re.DOTALL
)
_CANONICAL_PREFIX = f"{BASE_URL}/gongbao/"
# TOC lines join title and signing authority with CJK dot leaders; three-dot
# runs are the probed form (2026-10-02), two-or-more is tolerated.
_LEADER_RE = re.compile(r"[·•‧\u2026]{2,}")


def relative_article_path(issue_page_url: str, href: str) -> str:
    """Resolve one TOC href into the canonical path below ``/gongbao/``."""
    absolute = urljoin(issue_page_url, href)
    if not absolute.startswith(_CANONICAL_PREFIX):
        raise ValueError(
            f"TOC href {href!r} resolves outside /gongbao/ (got {absolute!r})"
        )
    return absolute[len(_CANONICAL_PREFIX):]


def parse_toc_line(raw_html: str) -> str:
    """TOC cell HTML → normalized single-line text (whitespace collapsed)."""
    return normalize_space(re.sub(r"<[^>]+>", "", raw_html))


class GongbaoIssueHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=issue_url(str(task.params["issue_path"])))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        year = str(task.params["year"])
        issue_path = str(task.params["issue_path"])
        page_url = issue_url(issue_path)
        if response.status_code != 200:
            raise ValueError(f"issue TOC {issue_path} returned HTTP {response.status_code}")

        html = response.content.decode("utf-8", errors="replace")
        rows = _TOC_ROW_RE.findall(html)
        seeds: list[TaskSeed] = []
        for href, cell in rows:
            path = relative_article_path(page_url, href)
            seeds.append(
                TaskSeed(
                    type="gongbao_doc",
                    params={
                        "path": path,
                        "toc": parse_toc_line(cell),
                        "year": year,
                        "issue_path": issue_path,
                        "issue_no": str(task.params.get("issue_no", "")),
                    },
                )
            )
        if not seeds:
            # Probed shape always lists ≥8 entries (2026-10-02, six years
            # sampled: 8–20); a linkless page contradicts the catalog, which
            # says this issue exists — shape change, escalate.
            raise ValueError(
                f"issue TOC {issue_path} carries no article links "
                "(the catalog lists this issue — shape change, escalate)"
            )

        return TaskResult(
            next_tasks=seeds,
            files=[
                FileOut(
                    path=f"{issue_folder(issue_path)}/issue_toc.html",
                    content=response.content,
                )
            ],
        )
