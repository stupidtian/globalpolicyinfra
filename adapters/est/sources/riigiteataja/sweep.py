"""Task type ``rt_sweep``: one page of the version inventory.

``GET /api/oigusakt_otsing/1/otsi`` — the key-free inventory listing
(probed 2026-10-27, samples in the task folder). One request answers with
``{staatus, paring, metaandmed{kokku, leht, limiit}, aktid[]}``; rows are
version-granular (globaalID unique per document version, terviktekstID
grouping the versions of one act) and carry issuer, native type, validity,
status, the text-layer word (``terviktekst`` or ``algtekst-terviktekst``),
the canonical ``/akt/{id}.xml`` address and the ``muudetud`` update stamp
inline. The default order is stable across calls (identical first pages on
repeat probes, 2026-10-27), so offset paging walks the inventory without
duplicates inside one run.

Paging is a chain: the parse of page N emits the page N+1 seed until the
declared ``pages_end`` or an empty page (the inventory tail — a clean
expected empty, and with a ``dokument`` filter legitimately empty from
page 1). The server rejects ``limiit`` above 500 with a loud 400.

scope=state filters municipal issuers at row level (the issuer rides in
every row; the compound-word rule lives in the source package). Filtered
rows are counted and explained, never silent.
"""

from __future__ import annotations

from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.est.sources.riigiteataja import (
    API_BASE,
    DEFAULT_PAGE_SIZE,
    REQUEST_HEADERS,
    is_municipal_issuer,
)

__all__ = ["SweepHandler"]

_LIST_URL = f"{API_BASE}/api/oigusakt_otsing/1/otsi"


def _act_seed(row: dict[str, Any], scope: str) -> TaskSeed:
    return TaskSeed(
        type="rt_act",
        params={
            "id": str(row["globaalID"]),
            "group": str(row.get("terviktekstID") or ""),
            "liik": str(row.get("liik") or ""),
            "valjaandja": str(row.get("valjaandja") or ""),
            "title": str(row.get("pealkiri") or ""),
            "scope_slice": scope,
        },
        signal=str(row.get("muudetud") or ""),
    )


class SweepHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        params: dict[str, Any] = {
            "leht": str(task.params["page"]),
            "limiit": str(DEFAULT_PAGE_SIZE),
        }
        dokument = str(task.params.get("dokument", "")).strip()
        if dokument:
            params["dokument"] = dokument
        return RequestSpec(url=_LIST_URL, params=params, headers=REQUEST_HEADERS)

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        page = str(task.params["page"])
        scope = str(task.params.get("scope", "state"))
        label = f"page {page}" + (
            f" dokument={task.params['dokument']}" if task.params.get("dokument") else ""
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(
                f"rt_sweep {label}: body is not JSON: {exc}"
            ) from exc
        if "aktid" not in payload or "metaandmed" not in payload:
            raise ValueError(
                f"rt_sweep {label}: unexpected response shape "
                f"(keys={sorted(payload)!r}) — inventory may have moved"
            )
        rows = payload["aktid"] or []

        seeds: list[TaskSeed] = []
        kept = 0
        municipal = 0
        for row in rows:
            if not row.get("globaalID") or not (row.get("muudetud")):
                raise ValueError(
                    f"rt_sweep {label}: row without globaalID/muudetud "
                    f"({ {k: row.get(k) for k in ('globaalID', 'muudetud', 'pealkiri')} }) — "
                    "inventory row shape may have changed"
                )
            issuer = str(row.get("valjaandja") or "")
            if scope == "state" and is_municipal_issuer(issuer):
                municipal += 1
                continue
            kept += 1
            seeds.append(_act_seed(row, scope))

        results = TaskResult()
        if kept:
            results.next_tasks.extend(seeds)
        elif rows:
            results.expected_empty = (
                f"rt_sweep {label}: all {len(rows)} listed versions fall outside "
                f"scope={scope} (municipal issuers: {municipal})"
            )
        else:
            results.expected_empty = (
                f"rt_sweep {label}: empty page — inventory tail (or a dokument "
                "filter with no matches) fully consumed"
            )

        pages_end = task.params.get("pages_end")
        has_next_page = pages_end is None or int(page) < int(str(pages_end))
        if rows and has_next_page:
            next_params = dict(task.params)
            next_params["page"] = str(int(page) + 1)
            results.next_tasks.append(TaskSeed(type="rt_sweep", params=next_params))
        return results
