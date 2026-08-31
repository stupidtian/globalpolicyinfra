"""Task type ``frl_title``: one title with its full version lineage.

``Titles('{id}')?$expand=versions`` is one request carrying both the
ledger row (name, collection, status, making date, series coordinates,
status history with the repeal chain) and the whole version lineage
(single-level $expand — the nested documents expand is a server-side 400,
probed 2026-08-31, so file inventories are a separate task).

Outputs:

- ``titles`` upsert — one row, including the two lineage pointers the
  daily feed refreshes (current-effect version start; latest *documented*
  version start — they differ while an amendment is in force but
  uncompiled) and ``raw_path`` pointing at the archived raw response;
- ``title_versions`` replacement — the lineage is one whole-of-title
  fact, rewritten per fetch rather than patched row by row;
- one ``frl_docs`` spawn per version selected by the capture policy:
  the as-made version always; the latest documented compilation in
  anchor mode; every compilation in ``comp=all`` mode. Each spawn
  carries what the download side cannot know from the file listing
  alone: the version's role (as-made/compiled), the publication date
  for that document, and the collection (Gazette exclusion, doc_type).

The raw response is archived as ``title.json`` under the title folder
(the register's own snapshot of title + lineage at fetch time).
"""

from __future__ import annotations

import json

from adapters.aus.sources.frl import odata_url
from adapters.base import (
    FileOut,
    ReplaceRows,
    RequestSpec,
    Response,
    TaskResult,
    TaskSeed,
    TaskView,
)

__all__ = ["FrlTitleHandler"]

_AS_MADE = "0"


def _bool_int(value: object) -> int:
    return 1 if value else 0


class FrlTitleHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        title_id = str(task.params["title_id"])
        # top=None: a $top on the expanded singleton read is a server 400
        return RequestSpec(url=odata_url(f"/Titles('{title_id}')", expand="versions", top=None))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        if response.status_code != 200:
            raise ValueError(f"title fetch returned HTTP {response.status_code}")
        title = response.json()
        if title.get("id") != task.params["title_id"]:
            raise ValueError(
                f"title response id {title.get('id')!r} does not match "
                f"requested {task.params['title_id']!r}"
            )

        versions = title.get("versions") or []
        if not versions:
            raise ValueError(f"title {title['id']} carries no versions")

        current_start = next(
            (v["start"][:10] for v in versions if v.get("isCurrent")), None
        )
        documented_start = next(
            (v["start"][:10] for v in versions if v.get("isLatest")), None
        )

        title_row = {
            "title_id": title["id"],
            "name": title.get("name") or title["id"],
            "collection": title.get("collection"),
            "sub_collection": title.get("subCollection"),
            "status": title.get("status"),
            "making_date": (title.get("makingDate") or "")[:10] or None,
            "is_principal": _bool_int(title.get("isPrincipal")),
            "is_in_force": _bool_int(title.get("isInForce")),
            "year": title.get("year"),
            "number": title.get("number"),
            "series_type": title.get("seriesType"),
            "latest_version_start": current_start,
            "latest_documented_start": documented_start,
            "status_history": json.dumps(
                title.get("statusHistory") or [], ensure_ascii=False
            ),
        }

        version_rows = []
        for version in sorted(versions, key=lambda v: v.get("start") or ""):
            version_rows.append(
                {
                    "title_id": title["id"],
                    "start": (version.get("start") or "")[:10],
                    "end": (version.get("end") or "")[:10] or None,
                    "compilation_number": version.get("compilationNumber"),
                    "registered_at": (version.get("registeredAt") or "")[:19] or None,
                    "is_current": _bool_int(version.get("isCurrent")),
                    "is_latest": _bool_int(version.get("isLatest")),
                    "reasons": json.dumps(
                        version.get("reasons") or [], ensure_ascii=False
                    ),
                }
            )

        mode_comp = str(task.params.get("comp", "anchor"))
        gazette = str(task.params.get("gazette", "0")) == "1"
        collection = title.get("collection") or ""

        spawns = []
        for version in version_rows:
            comp = version["compilation_number"]
            if comp == _AS_MADE:
                role, as_made = "asmade", True
            elif comp is not None:
                if mode_comp != "all" and version["start"] != documented_start:
                    continue
                role, as_made = "comp", False
            else:
                # Amendment marker: no document exists anywhere in the
                # source for this window — lineage row only.
                continue
            spawns.append(
                TaskSeed(
                    type="frl_docs",
                    params={
                        "title_id": title["id"],
                        "start": version["start"],
                        "role": role,
                        "comp": comp,
                        "name": title_row["name"],
                        "collection": collection,
                        "publication_date": (
                            title_row["making_date"]
                            if as_made
                            else version["start"]
                        ),
                        # ES (explanatory statement) belongs to instruments'
                        # as-made versions only; compilations of Acts have
                        # no statement and as-made Acts never do either.
                        "es": "1" if as_made and collection not in ("Act", "") else "0",
                        "gazette": "1" if gazette else "0",
                    },
                )
            )
        if not gazette and collection == "Gazette":
            spawns = []

        title_id = str(title["id"])
        folder = f"01_raw/frl/{title_id[:2]}/{title_id}"
        title_row["raw_path"] = f"{folder}/title.json"
        return TaskResult(
            upsert_rows={"titles": [title_row]},
            replacements=[
                ReplaceRows(
                    table="title_versions",
                    match={"title_id": title_id},
                    rows=version_rows,
                )
            ],
            files=[FileOut(path=f"{folder}/title.json", content=response.content)],
            next_tasks=spawns,
            expected_empty=(
                "Gazette title: ledger row only (gazette=0)" if not spawns else None
            ),
        )
