"""Task type ``frl_docs``: one version's file inventory and format choice.

``/Documents?$filter=titleId eq 'X' and start eq {start}`` returns only
that version's files — a handful of rows (6 on the probe instrument: 3
formats × primary/ES), so no pagination is needed at version scope
(probed 2026-08-31; the same title queried unscoped had 309 rows / 4
pages, which is why selection happens per version, not per title).

Format policy: EPUB volume 0 is the whole work in the register's primary
machine-readable format and is always preferred; PDF volume 0 is the
fallback when a version has no EPUB; a multi-volume PDF with no volume 0
(rare, large acts) falls back to the first volume, flagged in meta.
Word files are skipped (derivative, no unique content).

``es=1`` spawns the Explanatory Statement alongside the primary file —
instruments' only official policy-rationale document (Acts carry their
explanatory memoranda on the parliamentary site, not here).
"""

from __future__ import annotations

from typing import Any

from adapters.aus.sources.frl import odata_url
from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView

__all__ = ["FrlDocsHandler"]

_PRIMARY = "Primary"
_ES = "ES"


def _pick_format(files: list[dict[str, Any]]) -> tuple[str, int] | None:
    """(format, volume) of the best file among one kind's listings."""
    epub0 = next((f for f in files if f.get("format") == "Epub" and f.get("volumeNumber") == 0), None)
    if epub0:
        return "Epub", 0
    pdf0 = next((f for f in files if f.get("format") == "Pdf" and f.get("volumeNumber") == 0), None)
    if pdf0:
        return "Pdf", 0
    pdfs = sorted(
        (f for f in files if f.get("format") == "Pdf"),
        key=lambda f: f.get("volumeNumber") or 0,
    )
    if pdfs:
        return "Pdf", int(pdfs[0].get("volumeNumber") or 0)
    return None


class FrlDocsHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        title_id = str(task.params["title_id"])
        start = str(task.params["start"])
        filter_expr = f"titleId eq '{title_id}' and start eq {start}T00:00:00"
        return RequestSpec(url=odata_url("/Documents", filter_expr))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        if response.status_code != 200:
            raise ValueError(f"document listing returned HTTP {response.status_code}")
        rows = response.json().get("value")
        if not isinstance(rows, list):
            raise TypeError("document listing JSON has no value[] array")

        title_id = str(task.params["title_id"])
        by_kind: dict[str, list[dict[str, Any]]] = {_PRIMARY: [], _ES: []}
        for row in rows:
            kind = row.get("type")
            if kind in by_kind:
                by_kind[kind].append(row)

        seeds: list[TaskSeed] = []
        kinds = [_PRIMARY]
        if str(task.params.get("es", "0")) == "1":
            kinds.append(_ES)
        for kind in kinds:
            choice = _pick_format(by_kind[kind])
            if choice is None:
                continue
            fmt, volume = choice
            seeds.append(
                TaskSeed(
                    type="frl_doc",
                    params={
                        "title_id": title_id,
                        "start": str(task.params["start"]),
                        "kind": kind,
                        "fmt": fmt,
                        "vol": volume,
                        "comp": task.params.get("comp"),
                        # raw-stream downloads carry no envelope, so the
                        # document title can only come from the chain
                        "name": task.params.get("name"),
                        "collection": task.params.get("collection", ""),
                        "publication_date": task.params.get("publication_date"),
                    },
                )
            )

        if not seeds:
            return TaskResult(
                expected_empty=(
                    f"no downloadable file for {title_id} at {task.params['start']} "
                    f"(kinds={kinds})"
                )
            )
        return TaskResult(next_tasks=seeds)
