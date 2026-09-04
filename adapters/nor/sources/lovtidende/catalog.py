"""Task type ``lt_list``: the package catalogue, i.e. the freshness probe.

GET ``https://api.lovdata.no/v1/publicData/list`` — the live authority on
what bulk packages exist (the download URL registered on data.norge.no is
already stale, probed 2026-09-03; filenames are discovered, never
hardcoded). The JSON array answers one entry per package with
``filename`` / ``description`` / ``sizeBytes`` / ``lastModified``.

Two filename shapes are lovtidende avdeling I (probed 2026-09-03; both
extensions tolerated because the catalogue once shipped .zip):

- ``lovtidend-avd1-{from}-{to}.tar.bz2`` — the frozen multi-year archive
- ``lovtidend-avd1-{year}.tar.bz2`` — the current-year package, rebuilt
  every morning (~01:30 UTC)

Each in-scope package yields one ``lt_pack`` task whose params carry the
package's identity stamp ``{sizeBytes}@{lastModified}``. The stamp is the
reopen mechanism (section 6.5 refresh pattern with the stamp sourced
from the server's own catalogue): unchanged stamp → identical task_id →
already done → skipped; rebuilt package → new stamp → new identity →
re-sweep. The ``gjeldende-*`` consolidated-law packages are a future
version-sequence source and never spawned.
"""

from __future__ import annotations

import json
import re
from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView

__all__ = ["LIST_URL", "LtListHandler"]

LIST_URL = "https://api.lovdata.no/v1/publicData/list"

_ARCHIVE_RE = re.compile(r"^lovtidend-avd1-(\d{4})-(\d{4})\.(?:tar\.bz2|zip)$")
_YEAR_RE = re.compile(r"^lovtidend-avd1-(\d{4})\.(?:tar\.bz2|zip)$")


def _stamp(entry: dict[str, Any]) -> str:
    size = str(entry.get("sizeBytes", "")).strip()
    modified = str(entry.get("lastModified", "")).strip()
    if not size or not modified:
        raise ValueError(
            f"catalogue entry {entry.get('filename', '?')!r} lacks sizeBytes/lastModified "
            "— unknown shape, refusing to build a stamp from it"
        )
    return f"{size}@{modified}"


class LtListHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=LIST_URL, headers={"Accept": "application/json"})

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        scope = str(task.params.get("packages", "all"))
        try:
            payload: Any = json.loads(response.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"catalogue: body is not JSON: {exc}") from exc
        if not isinstance(payload, list):
            raise TypeError(f"catalogue: expected a JSON array, got {type(payload).__name__}")

        entries = [e for e in payload if isinstance(e, dict)]
        gazette = [e for e in entries if "filename" in e and (
            _ARCHIVE_RE.match(str(e["filename"])) or _YEAR_RE.match(str(e["filename"]))
        )]
        if not gazette:
            raise ValueError(
                "catalogue carries no lovtidend-avd1-* package at all — the API shape "
                "changed; nothing will be spawned"
            )

        wanted = []
        for entry in gazette:
            filename = str(entry["filename"])
            is_archive = _ARCHIVE_RE.match(filename) is not None
            if scope == "archive" and not is_archive:
                continue
            if scope == "year" and is_archive:
                continue
            wanted.append(entry)

        archives = [e for e in wanted if _ARCHIVE_RE.match(str(e["filename"]))]
        years = [e for e in wanted if _YEAR_RE.match(str(e["filename"]))]
        if len(archives) > 1 or len(years) > 1:
            raise ValueError(
                "catalogue carries more than one archive or current-year package "
                f"({[e.get('filename') for e in wanted]}) — unknown shape"
            )

        if not wanted:
            return TaskResult(
                expected_empty=(
                    f"catalogue has no package in scope {scope!r} "
                    f"(available: {[str(e.get('filename')) for e in gazette]})"
                )
            )
        return TaskResult(
            next_tasks=[
                TaskSeed(
                    type="lt_pack",
                    params={"file": str(e["filename"]), "stamp": _stamp(e)},
                )
                for e in wanted
            ]
        )
