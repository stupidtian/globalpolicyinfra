"""The list-endpoint enumerators: ``sd_day``, ``sd_year_page``, ``sd_fix``.

Three entry points into one endpoint —
``GET /akn/fi/act/statute/list`` — differing only in their server-side
filter (``dateIssued`` / ``startYear=endYear`` / ``publishedSince``), so
they share this module (section 6.4 ruling D4: one file tells one family).
Probed shapes, 2026-09-13, samples in the task folder:

- rows are JSON ``{"akn_uri": …/akn/fi/act/statute/{year}/{number}/{lang}@,
  "status": "NEW"|"MODIFIED"}``; the URI is the manifestation the fetch
  task will download — parsed, never string-rebuilt;
- the page size is capped at 10 server-side (limit > 10 → HTTP 400); the
  first page is 1 and a page with fewer rows than the limit ends the chain
  — *every* enumeration chains, a single gazette day can fill two pages
  (2025-02-13: 12 rows over 2 pages);
- an empty array is a legitimate answer for a no-issue day (verified
  against 2025-02-14/15, a Friday and a Saturday) — data, not a failure;
- ``status`` rides to the fetch task as its ``signal``: a later sweep that
  sees MODIFIED where NEW was recorded reopens the done fetch task
  (section 6.5 reopen rule).

``max_items`` caps *spawns, not enumeration* (CHE max_works semantics):
the chain always walks to the last page so the day is fully consumed and
the cursor advances, but fetch seeds stop at the cap. The running total
travels through the chain in the ``spawned`` param — task identity stays
deterministic because the counter is a pure function of the pages before.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.fin.sources.finlex import (
    API_BASE,
    CURSOR_KEY,
    DAY_PAGE_LIMIT,
    FIX_CURSOR_KEY,
)

__all__ = ["SdDayHandler", "SdFixHandler", "SdYearPageHandler"]

_LIST_URL = f"{API_BASE}/akn/fi/act/statute/list"


def _rows(response: Response, label: str) -> list[dict[str, Any]]:
    if response.status_code != 200:
        raise ValueError(
            f"{label}: unexpected HTTP {response.status_code} "
            "(empty days answer 200 with [], not 404)"
        )
    try:
        payload: Any = json.loads(response.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}: body is not JSON: {exc}") from exc
    if not isinstance(payload, list) or not all(isinstance(r, dict) for r in payload):
        raise ValueError(f"{label}: expected a JSON array of row objects")
    rows: list[dict[str, Any]] = list(payload)
    return rows


def _manifestation(akn_uri: str) -> tuple[str, str, str] | None:
    """``…/statute/{year}/{number}/{lang}@`` → (year, number, lang).

    Rows we cannot read are skipped rather than fatal — the enumeration
    must keep its contract with the cursor — but they stay visible through
    the kept/total accounting in expected_empty messages.
    """
    segments = akn_uri.rstrip("/").split("/")
    if len(segments) < 4 or segments[-4] != "statute" or not segments[-1].endswith("@"):
        return None
    return segments[-3], segments[-2], segments[-1][:-1]


class _ListEnumerator:
    """Shared chain mechanics; subclasses provide the request filter and
    the last-page bookkeeping."""

    def _filter_params(self, task: TaskView) -> dict[str, Any]:
        raise NotImplementedError

    def _chain_type(self) -> str:
        raise NotImplementedError

    def _label(self, task: TaskView) -> str:
        raise NotImplementedError

    def _finish(
        self, task: TaskView, seeds: list[TaskSeed], kept: int, total: int, last_page: bool
    ) -> TaskResult:
        raise NotImplementedError

    def build_request(self, task: TaskView) -> RequestSpec:
        query: dict[str, Any] = {
            "format": "json",
            "limit": DAY_PAGE_LIMIT,
            "page": int(task.params.get("page", 1)),
        }
        query.update(self._filter_params(task))
        types = str(task.params.get("types", ""))
        if types:
            query["typeStatute"] = types
        langs = self._lang_scope(task)
        if len(langs) == 1:
            # Server-side language filter (probed 2026-09-14:
            # langAndVersion=fin@ answers fin@ rows only) — halves the
            # enumeration pages for the single-language default sweep.
            query["langAndVersion"] = f"{next(iter(langs))}@"
        return RequestSpec(url=_LIST_URL, params=query)

    @staticmethod
    def _lang_scope(task: TaskView) -> set[str]:
        """The language scope a sweep applies. An absent/empty ``langs``
        (the pre-2026-09-14 sweeps ran with the then-default "collect all")
        now resolves to the current default ``fin`` — legacy bilingual chain
        pages still pending in a ledger therefore finish under the new
        single-language scope instead of resurrecting the Swedish half."""
        raw = str(task.params.get("langs", "")).strip()
        if not raw:
            return {"fin"}
        return {p for p in raw.split(",") if p}

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        label = f"{type(self).__name__} {self._label(task)} p{task.params.get('page', 1)}"
        rows = _rows(response, label)
        last_page = len(rows) < DAY_PAGE_LIMIT

        langs = self._lang_scope(task)
        max_items = int(task.params["max_items"]) if task.params.get("max_items") else None
        spawned = int(task.params.get("spawned", 0))

        seeds: list[TaskSeed] = []
        kept = 0
        for row in rows:
            manifestation = _manifestation(str(row.get("akn_uri", "")))
            if manifestation is None:
                continue
            year, number, lang = manifestation
            if langs and lang not in langs:
                continue
            kept += 1
            if max_items is not None and spawned + len(seeds) >= max_items:
                continue  # enumeration continues, deep fetch capped
            seeds.append(
                TaskSeed(
                    type="sd_fetch",
                    params={"year": year, "number": number, "lang": lang},
                    signal=str(row.get("status", "")) or None,
                )
            )
        new_spawned = spawned + len(seeds)

        result = self._finish(task, seeds, kept=kept, total=len(rows), last_page=last_page)
        if not last_page:  # full page → chain the next page of the same sweep
            chain: dict[str, Any] = {
                "page": int(task.params.get("page", 1)) + 1,
                "spawned": new_spawned,
            }
            for key in self._chain_keys():
                if key in task.params:
                    chain[key] = task.params[key]
            result.next_tasks.append(TaskSeed(type=self._chain_type(), params=chain))
        return result

    def _chain_keys(self) -> tuple[str, ...]:
        return ("date", "to_date", "year", "since", "mark_ts", "langs", "types", "max_items")


class SdDayHandler(_ListEnumerator):
    """One date-issued day; the chain's last page advances the day cursor
    and discovers the next day of the sweep — days run serially, so the
    cursor stays monotone even when a single day spans several pages."""

    def _filter_params(self, task: TaskView) -> dict[str, Any]:
        return {"dateIssued": str(task.params["date"])}

    def _chain_type(self) -> str:
        return "sd_day"

    def _label(self, task: TaskView) -> str:
        return str(task.params["date"])

    def _finish(
        self, task: TaskView, seeds: list[TaskSeed], kept: int, total: int, last_page: bool
    ) -> TaskResult:
        day = str(task.params["date"])
        result = TaskResult(next_tasks=seeds)
        if total == 0:
            result.expected_empty = (
                f"no statutes issued on {day} (weekend, holiday, or a genuinely "
                "quiet day — the source answers an empty array)"
            )
        elif kept == 0:
            result.expected_empty = f"day {day}: {total} rows returned, none inside langs scope"
        elif not seeds:
            result.expected_empty = (
                f"day {day}: max_items cap reached, {kept} in-scope rows left unfetched"
            )
        if last_page:
            result.cursor_updates = {CURSOR_KEY: day}
            next_day = date.fromisoformat(day) + timedelta(days=1)
            to_date = str(task.params.get("to_date", day))
            if next_day <= date.fromisoformat(to_date):
                nxt: dict[str, Any] = {"date": next_day.isoformat(), "to_date": to_date}
                for key in self._chain_keys():
                    if key in task.params and key not in nxt:
                        nxt[key] = task.params[key]
                result.next_tasks.append(TaskSeed(type="sd_day", params=nxt))
        return result


class SdYearPageHandler(_ListEnumerator):
    """Backfill enumeration of one gazette year; no date cursor."""

    def _filter_params(self, task: TaskView) -> dict[str, Any]:
        year = str(task.params["year"])
        return {"startYear": year, "endYear": year, "sortBy": "number"}

    def _chain_type(self) -> str:
        return "sd_year_page"

    def _label(self, task: TaskView) -> str:
        return str(task.params["year"])

    def _finish(
        self, task: TaskView, seeds: list[TaskSeed], kept: int, total: int, last_page: bool
    ) -> TaskResult:
        year = str(task.params["year"])
        result = TaskResult(next_tasks=seeds)
        if total == 0:
            result.expected_empty = (
                f"gazette year {year} carries no manifestations "
                "(years outside 1734 / 1868–1907 / 1917– have no records)"
            )
        elif kept == 0:
            result.expected_empty = f"year {year}: {total} rows returned, none inside langs scope"
        elif not seeds:
            result.expected_empty = (
                f"year {year}: max_items cap reached, {kept} in-scope rows left unfetched"
            )
        return result


class SdFixHandler(_ListEnumerator):
    """Change feed since a watermark; the chain's last page stamps the sweep."""

    def _filter_params(self, task: TaskView) -> dict[str, Any]:
        return {"publishedSince": str(task.params["since"])}

    def _chain_type(self) -> str:
        return "sd_fix"

    def _label(self, task: TaskView) -> str:
        return str(task.params["since"])

    def _finish(
        self, task: TaskView, seeds: list[TaskSeed], kept: int, total: int, last_page: bool
    ) -> TaskResult:
        since = str(task.params["since"])
        mark_ts = str(task.params["mark_ts"])
        result = TaskResult(next_tasks=seeds)
        if total == 0:
            result.expected_empty = f"no statute rows changed since {since}"
        elif kept == 0:
            result.expected_empty = (
                f"change feed since {since}: {total} rows, none inside langs scope"
            )
        elif not seeds:
            result.expected_empty = (
                f"change feed since {since}: max_items cap reached, "
                f"{kept} in-scope rows left unfetched"
            )
        # The watermark moves to *this sweep's* start stamp (the skew margin
        # was applied when the sweep was seeded) and only on the chain's
        # last page — a crashed sweep never advances it.
        if last_page:
            result.cursor_updates = {FIX_CURSOR_KEY: mark_ts}
        return result
