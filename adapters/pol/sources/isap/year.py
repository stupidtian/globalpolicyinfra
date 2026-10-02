"""Task type ``isap_year``: one year of the Dziennik Ustaw, one request.

``GET /eli/acts/DU/{year}`` — the year's full listing answers in a single
response (no paging; probed 2026-09-20: 2024 → count=1984=len(items),
1995 → 801; the boundary check DU/2024/1984=200 vs DU/2024/1985=404
confirms count == the year's maximum position). Rows carry title, native
type, status, promulgation/announcement dates, volume, pos, changeDate,
the textHTML/textPDF flags and the ELI inline.

The promulgation-date window (``from``/``to``) filters at row level; the
window and the ``max_acts`` guard travel in the sweep task's params, so
widening a scope later means new sweep identities and an automatic
backfill, while the per-act tasks below stay identity-stable. A window
with zero hits is a legal empty (explained); the year axis carries no
cursor — increments ride the change feed. Rows without a promulgation
date exist in the source (one-off acts repealed before promulgation,
probed: DU/2024/1723 of 1,984 rows in 2024) — they pass without a
window and fall outside any windowed sweep by design.
"""

from __future__ import annotations

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.pol.sources.isap import ELI_BASE

__all__ = ["IsapYearHandler"]

_YEAR_ITEM_REQUIRED = ("pos", "changeDate", "title")


class IsapYearHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=f"{ELI_BASE}/acts/{task.params['publisher']}/{task.params['year']}"
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        publisher = str(task.params["publisher"])
        year = str(task.params["year"])
        from_str = str(task.params.get("from", ""))
        to_str = str(task.params.get("to", ""))
        max_acts = int(task.params["max_acts"]) if task.params.get("max_acts") else None

        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(f"isap_year {publisher}/{year}: body is not JSON: {exc}") from exc
        items = payload.get("items")
        if not isinstance(items, list) or "count" not in payload:
            raise ValueError(
                f"isap_year {publisher}/{year}: unexpected response shape "
                f"(keys={sorted(payload)!r}) — the year listing may have moved"
            )

        seeds: list[TaskSeed] = []
        skipped_window = 0
        for item in items:
            for field in _YEAR_ITEM_REQUIRED:
                if not item.get(field):
                    raise ValueError(
                        f"isap_year {publisher}/{year}: listing row without {field!r} "
                        f"({item.get('displayAddress')!r}) — row shape may have changed"
                    )
            if str(item.get("publisher") or "") != publisher:
                raise ValueError(
                    f"isap_year {publisher}/{year}: row {item.get('displayAddress')!r} "
                    f"answers publisher {item.get('publisher')!r}"
                )
            promulgation = str(item.get("promulgation") or "")[:10]
            if from_str and (not promulgation or promulgation < from_str):
                skipped_window += 1
                continue
            if to_str and (not promulgation or promulgation > to_str):
                skipped_window += 1
                continue
            if max_acts is not None and len(seeds) >= max_acts:
                break
            seeds.append(
                TaskSeed(
                    type="isap_act",
                    params={
                        "publisher": publisher,
                        "year": year,
                        "pos": str(int(item["pos"])),
                    },
                    signal=str(item["changeDate"]),
                )
            )

        result = TaskResult(next_tasks=seeds)
        if not seeds:
            result.expected_empty = (
                f"isap_year {publisher}/{year}: no entries in the requested window "
                f"({len(items)} listed, {skipped_window} outside from/to)"
                if items
                else f"isap_year {publisher}/{year}: the year holds no entries"
            )
        return result
