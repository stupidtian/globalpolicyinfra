"""Task type ``isap_text``: the act's HTML text — the primary document file.

``GET /eli/acts/DU/{y}/{p}/text.html`` — a bare document body (h1 with
head-type/head-date spans, h2 part headings, article structure; 2026-09-20
probe: DU/2024/1 at 125,753 bytes, charset=utf-8; even the 1995 scan era
serves OCR-backed HTML). The file lands as ``text.html`` beside the
archived ``act.json`` and carries the doc_id (one file per doc_id carries
it, section 6.9). A response that is not the act document (empty body,
JSON error envelope) is a loud shape change, never a silent write.
"""

from __future__ import annotations

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.pol.sources.isap import ELI_BASE, act_folder

__all__ = ["IsapTextHandler"]

_MIN_HTML_BYTES = 100


class IsapTextHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        publisher = str(task.params["publisher"])
        return RequestSpec(
            url=(
                f"{ELI_BASE}/acts/{publisher}/{task.params['year']}/"
                f"{task.params['pos']}/text.html"
            )
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        publisher = str(task.params["publisher"])
        label = f"{publisher}/{task.params['year']}/{task.params['pos']}"
        content = response.content
        stripped = content.lstrip()[:200].lower()
        if len(content) < _MIN_HTML_BYTES or not stripped.startswith(b"<"):
            raise ValueError(
                f"isap_text {label}: response is not the HTML document "
                f"({len(content)} bytes, starts {content[:60]!r})"
            )
        return TaskResult(
            files=[
                FileOut(
                    path=f"{act_folder(publisher, task.params['year'], task.params['pos'])}/text.html",
                    content=content,
                    doc_id=str(task.params["doc_id"]),
                )
            ]
        )
