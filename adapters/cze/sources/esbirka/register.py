"""Task type ``cze_list``: one year's chronological register (POST).

Response shape (probed 2026-10-15, byte-true samples in the task folder's
probe archive)::

    {"dokumentySbirkyVMesici": [
        {"mesic": 1, "sbirkyDokumentuSbirky": [
            {"dokumentySbirkyRejstrikInfo": [
                {"staleUrl": "/sb/2026/1", "nazev": "Vyhláška, …",
                 "kodDokumentuSbirky": "1/2026 Sb.",
                 "stavDokumentuSbirky": "AKTUALNE_PLATNY", "datum": "2026-01-08"},
                …]}]}]}

The register mixes ALL collections (sb / sm / ul0 / ul1 …); capture filters
by the staleUrl prefix against the sweep's ``collections`` param. Register
year == publication year on every entry probed (four years, zero spillover)
— a deviation is a shape change, escalated loudly.

The walk is year-chained, not fanned out: the seed holds the window's FIRST
year only, each completed register chains ``rok + 1`` while the window
continues, and only the FINAL year's completed walk advances the cursor
(section 6.5 chain semantics — an earlier year failing alone can never
leave a "consumed" watermark behind). ``max_docs`` caps the spawns across
the chain (the remaining budget rides to the next year) and, when it
bites, stops the walk and withholds the cursor — a trial window, not a
partial crawl. Out-of-collection rows are not validated beyond their
prefix: a malformed field on a skipped entry is a non-event, while any
anomaly on an in-scope entry escalates.
"""

from __future__ import annotations

import re
from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.cze.sources.esbirka import (
    CURSOR_KEY,
    REGISTER_URL,
    guard_block_page,
    guard_waf,
    stale_parts,
    versioned_stale,
)

__all__ = ["CzeListHandler", "info_seed", "iso_day"]

#: Fields every in-scope register row must carry (probed shape); their
#: absence is a register shape change, not a data boundary.
_REQUIRED = ("staleUrl", "nazev", "kodDokumentuSbirky", "datum")


def iso_day(value: str) -> str:
    """'2026-01-08' validated as an ISO date (the register carries bare
    dates; the detail endpoint's timestamps are handled there)."""
    year, sep, rest = value.partition("-")
    if not sep or len(year) != 4 or len(rest) != 5 or not value.replace("-", "").isdigit():
        raise ValueError(f"datum {value!r} is not an ISO date")
    return value


def _squash(text: str) -> str:
    """Collapse whitespace runs — Czech titles arrive with double spaces
    ('Vyhláška,  kterou …', probed on both register and detail)."""
    return re.sub(r"[\s ]+", " ", text).strip()


def info_seed(doc: dict[str, Any]) -> TaskSeed:
    """Validate one in-scope register row and build its spawn.

    The capture address is ALWAYS the versioned alias (stable, idempotent)
    — the register's own act-level pointer is parsed for its coordinates
    and then normalized away. Params carry the register's stable fields so
    the doc task can cross-check the detail response against them.
    """
    for field in _REQUIRED:
        value = doc.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"register row misses {field!r}: {doc!r}")
    stale = doc["staleUrl"].strip()
    coll, year, number, _ver = stale_parts(stale)
    status = doc.get("stavDokumentuSbirky")
    params: dict[str, Any] = {
        "stale": versioned_stale(coll, year, number),
        "rok": int(year),
        "datum": iso_day(doc["datum"].strip()),
        "kod": _squash(doc["kodDokumentuSbirky"]),
        "nazev": _squash(doc["nazev"]),
    }
    if isinstance(status, str) and status.strip():
        params["stav"] = status.strip()
    return TaskSeed(type="cze_info", params=params)


class CzeListHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=REGISTER_URL,
            method="POST",
            json_body={"rok": int(task.params["rok"])},
            headers={"Accept": "application/json"},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = dict(task.params)
        rok = int(params["rok"])
        from_day = str(params["from"])
        to_day = str(params["to"])
        collections = [str(c) for c in params.get("collections", ["sb"])]
        guard_waf(response.status_code, f"register of {rok}")
        if response.status_code != 200:
            raise ValueError(f"register of {rok} returned HTTP {response.status_code}")
        guard_block_page(response.content, f"register of {rok}")
        data = response.json()
        months = data.get("dokumentySbirkyVMesici")
        if not isinstance(months, list):
            # A wrong-typed payload is a register shape change, and shape
            # changes are ValueError by country-pack convention.
            raise ValueError(  # noqa: TRY004
                f"register of {rok} has no dokumentySbirkyVMesici array"
            )

        seeds: list[TaskSeed] = []
        budget = params.get("max_docs")
        capped = budget is not None and int(budget) <= 0
        for month in months:
            if not isinstance(month, dict):
                raise ValueError(f"register of {rok} holds a non-object month")  # noqa: TRY004
            for group in month.get("sbirkyDokumentuSbirky", []):
                if not isinstance(group, dict):
                    raise ValueError(f"register of {rok} holds a non-object group")  # noqa: TRY004
                rows = group.get("dokumentySbirkyRejstrikInfo", [])
                if not isinstance(rows, list):
                    raise ValueError(f"register of {rok} has a non-array rejstrikInfo")  # noqa: TRY004
                for doc in rows:
                    if not isinstance(doc, dict):
                        raise ValueError(f"register of {rok} holds a non-object row")  # noqa: TRY004
                    stale = doc.get("staleUrl")
                    if not isinstance(stale, str) or not stale.strip():
                        raise ValueError(
                            f"register of {rok} holds a row without staleUrl"
                        )
                    if stale.split("/")[1] not in collections:
                        continue  # another collection's numbering — out of scope
                    seed = info_seed(doc)
                    day = str(seed.params["datum"])
                    if day[:4] != str(rok):
                        raise ValueError(
                            f"register of {rok} holds a {day[:4]}-dated entry "
                            f"{seed.params['kod']!r} — year spillover assumption broken"
                        )
                    if not from_day <= day <= to_day:
                        continue  # outside the window (same year, other month)
                    if capped:
                        break
                    seeds.append(seed)
                    if budget is not None:
                        budget = int(budget) - 1
                        if budget <= 0:
                            capped = True

        next_tasks: list[TaskSeed] = list(seeds)
        cursor_updates: dict[str, str] = {}
        expected_empty = None
        next_year = rok + 1
        if next_year <= int(to_day[:4]) and not capped:
            remaining = dict(params)
            remaining["rok"] = next_year
            if budget is not None:
                remaining["max_docs"] = int(budget)
            next_tasks.append(TaskSeed(type="cze_list", params=remaining))
        elif rok == int(to_day[:4]) and not capped:
            # The final year's register is fully consumed: every in-window
            # entry has been seen — the watermark.
            cursor_updates[CURSOR_KEY] = to_day
            if not seeds:
                expected_empty = (
                    f"window {from_day}..{to_day} holds no in-scope publications "
                    f"({'/'.join(collections)})"
                )
        return TaskResult(
            next_tasks=next_tasks,
            cursor_updates=cursor_updates,
            expected_empty=expected_empty,
        )
