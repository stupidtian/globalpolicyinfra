"""Task type ``pravo_day``: one calendar day of the official publication.

GET the portal's date-addressed day search (``/search``) and turn every
kept entry into a ``pravo_text`` seed. Probed behaviours this handler
encodes (2026-10-12, raw samples in the task folder):

- The result list is server-rendered HTML. A day with no documents at all
  answers HTTP 200 with the literal line «Документы не найдены» — an
  explained empty; the archive's early years (late 2011 through early
  2012) contain many such days. That is data reality: the cursor still
  advances.
- The count line «Показаны на странице: с X по Y из N» carries the day's
  total. ``index * pageSize < N`` means more pages: the page derives
  ``{date, index+1}`` — a chain, so page k+1 exists only after page k is
  committed (out-of-order workers can never skip ahead). The *tail* page
  of the chain is the task that fully consumed the day and moves the
  ``pravo_last_date`` cursor.
- Entries carry everything downstream needs: publication number, listing
  date, the full title (type word + number + proper title) and the PDF
  page count. Two filters run here and travel in task params so widening
  later re-fetches automatically: ``scope`` (federal = publication number
  starts ``0001``; regional acts carry ``XY00``) and ``include_court``
  (Constitutional Court acts are case law — excluded by default).
"""

from __future__ import annotations

import re

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.rus.sources.pravo import (
    CURSOR_KEY,
    FEDERAL_PREFIX,
    PAGE_SIZE,
    PORTAL_BASE,
    clean_listing_title,
    is_court_title,
    map_doc_type,
    parse_title,
)

__all__ = ["PravoDayHandler"]

_EMPTY_MARK = "Документы не найдены"

_COUNT_RE = re.compile(r"Показаны на странице:.{0,120}?из\s*(\d+)", re.DOTALL)
_ROW_SPLIT_RE = re.compile(r'<div class="documents-table-row">')
_ITEM_RE = re.compile(
    r'<a href="/document/(\d+)" class="documents-item-name">\s*(.*?)\s*</a>', re.DOTALL
)
_DATE_RE = re.compile(r"Дата опубликования:\s*</span>\s*<span class=\"info-data\">(\d{2}\.\d{2}\.\d{4})</span>")
_PAGES_RE = re.compile(r"\((\d+) стр\.\)")


def _dmy(iso: str) -> str:
    year, month, day = iso.split("-")
    return f"{day}.{month}.{year}"


class PravoDayHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        day = str(task.params["date"])
        index = int(task.params.get("index", 1))
        return RequestSpec(
            url=f"{PORTAL_BASE}/search",
            params={
                "PublishDateFrom": _dmy(day),
                "PublishDateTo": _dmy(day),
                "pageSize": str(PAGE_SIZE),
                "index": str(index),
            },
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        day = str(task.params["date"])
        index = int(task.params.get("index", 1))
        scope = str(task.params.get("scope", "federal"))
        include_court = str(task.params.get("include_court", "no"))
        types_raw = str(task.params.get("types", ""))
        keep_types = {t.strip() for t in types_raw.split(",") if t.strip()}
        # Which leg carries the body: bank HTML (default) or the portal's
        # scanned PDF — the only carrier for ministry acts (probed:
        # the bank holds no ведомственные акты at all, 2026-10-12).
        content = str(task.params.get("content", "html"))
        body_task = "pravo_pdf" if content == "pdf" else "pravo_text"
        # The designated cursor writer: only the window-end day's tail page
        # moves the watermark (see start_tasks — interleaved page chains
        # make per-day writes order-dependent).
        cursor_through = str(task.params.get("cursor_through", day))

        if response.status_code != 200:
            raise ValueError(
                f"pravo_day {day}/{index}: unexpected HTTP {response.status_code}"
            )
        html = response.content.decode("utf-8", errors="strict")

        def tail_result(expected_empty: str | None) -> TaskResult:
            cursor = {CURSOR_KEY: day} if day == cursor_through else {}
            return TaskResult(expected_empty=expected_empty, cursor_updates=cursor)

        if _EMPTY_MARK in html:
            return tail_result(
                f"no documents published on {day} ({_EMPTY_MARK})"
            )

        count_match = _COUNT_RE.search(html)
        if count_match is None:
            raise ValueError(
                f"pravo_day {day}/{index}: neither the empty-day marker nor "
                "the result-count line found — listing shape mutated"
            )
        total = int(count_match.group(1))
        has_next = index * PAGE_SIZE < total

        kept: list[TaskSeed] = []
        skipped_federal = skipped_court = skipped_type = 0
        for row in _ROW_SPLIT_RE.split(html)[1:]:
            item = _ITEM_RE.search(row)
            if item is None:
                continue
            number = item.group(1)
            raw_title = item.group(2)
            date_match = _DATE_RE.search(row)
            if date_match is None:
                raise ValueError(
                    f"pravo_day {day}/{index}: entry {number} carries no "
                    "listing date — row shape mutated"
                )
            listing_date = date_match.group(1)

            if scope == "federal" and not number.startswith(FEDERAL_PREFIX):
                skipped_federal += 1
                continue
            title = clean_listing_title(raw_title)
            if include_court == "no" and is_court_title(title):
                skipped_court += 1
                continue
            doc_type = map_doc_type(title)
            if keep_types and doc_type not in keep_types:
                skipped_type += 1
                continue

            pages_match = _PAGES_RE.search(row)
            fields = parse_title(title)
            entry: dict[str, str] = {
                "номер": number,
                "pub_date": f"{listing_date[6:]}-{listing_date[3:5]}-{listing_date[:2]}",
                "title": title,
                "doc_type": doc_type,
                "scope": scope,
                "include_court": include_court,
            }
            for key in ("doc_number", "doc_date", "issuing_authority"):
                if key in fields:
                    entry[key] = fields[key]
            if pages_match is not None:
                entry["pdf_pages"] = pages_match.group(1)
            kept.append(TaskSeed(type=body_task, params=entry))

        if has_next:
            kept.append(
                TaskSeed(
                    type="pravo_day",
                    params={
                        "date": day,
                        "index": str(index + 1),
                        "scope": scope,
                        "include_court": include_court,
                        "types": types_raw,
                        "content": content,
                        "cursor_through": cursor_through,
                    },
                )
            )
            return TaskResult(next_tasks=kept)

        if not kept:
            return tail_result(
                f"page {index} of {day} fully consumed: no entries inside "
                f"the default scope (regional skipped: {skipped_federal}, "
                f"court skipped: {skipped_court}, type skipped: {skipped_type})"
            )
        if day == cursor_through:
            return TaskResult(next_tasks=kept, cursor_updates={CURSOR_KEY: day})
        return TaskResult(next_tasks=kept)
