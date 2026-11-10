"""Task type ``frl_dept``: one title's administering department (metadata only).

The backfill channel for the register's ``administeringDepartments``
navigation (probed 2026-10-31: every title carries at least its current
administering department — e.g. F2026L01121 → Department of
Infrastructure, Transport…; C2026A00080 → Foreign Affairs and Trade).

``made=… depts=1`` sweeps spawn one frl_dept per enumerated title. The
department is a **title-level fact** (one per title, shared by all its
documents), so it lands in the ``title_departments`` table — engine-native
upsert, idempotent re-runs, and the durable home the propagation pass
reads when filling ``documents.issuing_authority`` for the historical
corpus (documents rows are INSERT OR IGNORE, so the fetch cannot update
them directly; titles-side storage + one local propagation is the
sanctioned shape, cf. the 2026-09-01 doc_type repair deviation).

Files and cleaned texts are untouched by this task — one small JSON GET
per title, no version lineage, no downloads.
"""

from __future__ import annotations

from adapters.aus.sources.frl import odata_url
from adapters.base import RequestSpec, Response, TaskResult, TaskView

__all__ = ["FrlDeptHandler"]

_DEPT_SEP = "; "


class FrlDeptHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        title_id = str(task.params["title_id"])
        # no $top (the singleton+$top quirk), no $select (the nav must ride
        # along with the entity read; the response is a few KB either way)
        return RequestSpec(
            url=odata_url(f"/Titles('{title_id}')", expand="administeringDepartments",
                          top=None)
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        if response.status_code != 200:
            raise ValueError(f"department fetch returned HTTP {response.status_code}")
        title = response.json()
        title_id = str(task.params["title_id"])
        if title.get("id") != title_id:
            raise ValueError(
                f"department response id {title.get('id')!r} does not match "
                f"requested {title_id!r}"
            )
        names = [
            str(d.get("name") or "").strip()
            for d in (title.get("administeringDepartments") or [])
            if d.get("name")
        ]
        if not names:
            return TaskResult(
                expected_empty=f"title {title_id} carries no administering department"
            )
        department = _DEPT_SEP.join(names)
        return TaskResult(
            upsert_rows={"title_departments": [
                {"title_id": title_id, "department": department}
            ]}
        )
