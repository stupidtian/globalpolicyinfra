"""Task type ``ul_html``: one act's archival HTML page — the primary file.

GET ``uradni-list.si/glasilo-uradni-list-rs/vsebina/{slug}/{title-slug}?h=``
(the per-act page of the archival gazette site, pre-ZOUL acts only) and
store the response verbatim as the act's primary file
``01_raw/uradnilist/html/{year}/{slug}.html``, doc_id-carried — the text
carrier the cleaning layer reads (whitelist ``div#divSection``).

Probed 2026-10-12, coverage 32/32 (2000-2025, state and municipal,
punctuation-heavy titles): the site answers HTTP 200 with a generic
landing page for unknown slugs, so presence is judged by the
``id="divSection"`` body container, never by status alone — a missing
container is a loud failure (archive gap or title-slug drift), never a
silent skip. The verbatim as-published PDF stays available through
``meta.ul_pdf_path`` (stored once per issue by ``ul_pdf``). See
docs/countries/svn/uradnilist-zh.md.
"""

from __future__ import annotations

import re

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.svn.sources.uradnilist import archive_url_for, html_rel_path

__all__ = ["UlHtmlHandler"]

_BODY_CONTAINER = re.compile(r"""id=['"]divSection['"]""")


class UlHtmlHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=archive_url_for(str(task.params["slug"]), str(task.params["title"]))
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        slug = str(task.params["slug"])
        day = str(task.params["date"])
        try:
            page = response.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"ul_html {slug}: archive page is not UTF-8 ({exc}) — the "
                "archival site encoding may have changed"
            ) from exc
        if not _BODY_CONTAINER.search(page):
            raise ValueError(
                f"ul_html {slug}: no div#divSection body container in the "
                "response — the archival site answered its generic landing "
                "page (act missing from the archive, or title-slug drift)"
            )
        return TaskResult(
            files=[
                FileOut(
                    path=html_rel_path(day, slug),
                    content=response.content,
                    doc_id=str(task.params["doc_id"]),
                )
            ],
        )
