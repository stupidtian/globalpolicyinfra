"""Task type ``govza_list``: one slice of the date-filtered listing.

``GET /document`` with the server-side publication-date filter
(``field_gcisdoc_document_date[min]=date&[…max]=date``, plus ``page=N``
for continuations) — the same request shape the portal's own search form
submits (probed 2026-10-10, samples in the task folder). 30 rows per
page; the parse emits one detail seed per in-scope row and a same-type
next-page seed while a page comes back full (30 rows).

The empty answer is a clean ``<p>No Results</p>`` where the table would
be (weekends, no-gazette days, and pages past the end answer
identically — probed on page=999) — an explained empty, and, being a
fully consumed day slice, the day cursor still advances.

Row shape (stable across the 2025-06 legacy samples and the 2026-10
live fetch): three ``<td>`` cells keyed by ``views-field-…`` classes —

- title cell: one ``<a href="/documents/{type}/{slug}">`` plus the
  gazette header block (``div.gazette-result`` items: ``G. 51889``,
  ``RG 11783``, the notice code ``GeN 2930`` under an ``<h2>``, and a
  "Comment by <time>" deadline);
- date cell: ``<time datetime="2025-01-10T12:00:00Z">`` — the document
  date, the axis the filter runs on. The title cell may carry *another*
  ``<time>`` (the comment deadline); only the date cell counts;
- type cell: a document-type link — the search-form taxonomy
  ``/taxonomy/term/{id}`` or the portal category
  ``/documents-categories/{slug}`` (both live: the second surfaced in
  the trial run's archived failure, 2026-10-10); both normalize to the
  same native name. Row-level filtering runs on it: ``types=`` keeps
  exactly the selected native types (a comma list of TYPE_SLUGS riding
  in the task params), or ``scope=policy`` drops Tenders / Annual
  reports. Classification ladder for rows whose type cell is bare
  (legacy-migrated records, first seen 2014, archived failures
  2026-10-14): the row's own ``Act N of YYYY`` code proves an Act;
  anything else (stray bill/policy-draft rows, one provincial page) is
  unclassifiable — skipped and counted, explained in the empty answer
  when a day yields nothing, never a day-killer. Unknown category
  slugs stay loud (a real vocabulary gap needs adding).

Rows are trusted to be self-describing: a row missing its link, date or
type cell is a shape change and dies loud.
"""

from __future__ import annotations

import re
from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.zaf.sources.govza import (
    CURSOR_KEY,
    DOC_TYPE_NAMES,
    LIST_URL,
    POLICY_EXCLUDED_TYPES,
    TYPE_SLUGS,
)

__all__ = ["ListHandler"]

_PAGE_SIZE = 30

_ROW_RE = re.compile(r'<tr class="(?:odd|even)">(.*?)</tr>', re.DOTALL)

#: The date cell holds exactly one ``<time>`` — the document date. The
#: cell is located by its ``views-field-field-gcisdoc-document-date``
#: marker anywhere in the ``<td>`` tag (the live page and the 2025-06
#: legacy samples disagree on the class/headers attribute order, so the
#: anchor must not assume one).
_DATE_TD_RE = re.compile(
    r"<td[^>]*views-field-field-gcisdoc-document-date[^>]*>(.*?)</td>", re.DOTALL
)
_TAG_RE = re.compile(r"<[^>]+>")

#: Code families inside the gazette header block (all probed shapes):
#: ``G. 51889`` (Government Gazette), ``RG 11783`` (Regulation Gazette),
#: ``GeN 2930`` / ``GoN 6334`` (General / Government Notice), ``BN 74``
#: (Board Notice), ``Act 47 of 2024``.
_GAZETTE_NUM_RE = re.compile(r"\bG\.\s*(\d+)")
_RG_NUM_RE = re.compile(r"\bRG\s+(\d+)")
_NOTICE_CODE_RE = re.compile(r"\b(GeN|GoN|BN)\s+(\d+)")
_ACT_REF_RE = re.compile(r"\bAct\s+(\d+)\s+of\s+(\d{4})")
_COMMENT_BY_RE = re.compile(r'Comment by\s*<time datetime="(\d{4}-\d{2}-\d{2})')

_LINK_RE = re.compile(
    r'<a href="(/(?!taxonomy/|documents-categories/)[^"#]+)"[^>]*>(.*?)</a>', re.DOTALL
)
_DATE_RE = re.compile(r'<time datetime="(\d{4}-\d{2}-\d{2})')

#: The type cell links one of TWO shapes (both live, probed 2026-10-10 —
#: the second surfaced only in the trial run's archived failure): the
#: search-form taxonomy ``/taxonomy/term/{id}`` and the portal category
#: ``/documents-categories/{slug}``. Both normalize to the same native
#: name; the term id is kept when present.
_TERM_RE = re.compile(r'href="/taxonomy/term/(\d+)"')
_CATEGORY_RE = re.compile(r'href="/documents-categories/([a-z0-9-]+)"')


def _native_type(row_html: str) -> str:
    """The row's native document type. Classification ladder: the type
    cell's link (either shape), then — for the portal's legacy-migrated
    rows whose type cell is bare — the row's own ``Act N of YYYY`` code.
    Anything else is unclassifiable and skipped+counted by the caller
    (probed 2026-10-14: bills and stray policy drafts without a type
    cell, and one provincial page — a handful per decade)."""
    term = _TERM_RE.search(row_html)
    if term:
        return DOC_TYPE_NAMES.get(term.group(1), term.group(1))
    category = _CATEGORY_RE.search(row_html)
    if category:
        slug = category.group(1)
        if slug not in TYPE_SLUGS:
            raise _UnknownCategory(slug)
        return TYPE_SLUGS[slug]
    if _ACT_REF_RE.search(row_html):
        return "Acts"
    raise _UnclassifiableRow()


class _UnknownCategory(ValueError):
    """A /documents-categories/ slug outside the declared vocabulary —
    a genuine vocabulary gap: stays loud (needs_agent) so it gets added."""


class _UnclassifiableRow(ValueError):
    """A complete row (title + date) with no type link and no act code —
    the portal's unclassified long tail; skipped and counted, never a
    day-killer."""


def _clean_text(raw: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", raw)).strip()


def _row_label(row_html: str) -> str:
    link = _LINK_RE.search(row_html)
    return f"…/{link.group(1).rsplit('/', 1)[-1]}" if link else row_html[:80]


def _detail_seed(row_html: str, doc_date: str, native: str) -> TaskSeed:
    link = _LINK_RE.search(row_html)
    if not link:
        raise ValueError(
            f"govza_list {doc_date}: row without a document link "
            f"({_row_label(row_html)!r}) — listing row shape may have changed"
        )
    href = link.group(1)
    title = _clean_text(link.group(2))
    if not title:
        raise ValueError(
            f"govza_list {doc_date}: row {href!r} has an empty link text — "
            "listing row shape may have changed"
        )

    meta: dict[str, str] = {"href": href, "native_type": native}
    term = _TERM_RE.search(row_html)
    if term:
        meta["term_id"] = term.group(1)
    gazette_nums = sorted(set(_GAZETTE_NUM_RE.findall(row_html)))
    rg_nums = sorted(set(_RG_NUM_RE.findall(row_html)))
    notice_codes = sorted({f"{kind} {num}" for kind, num in _NOTICE_CODE_RE.findall(row_html)})
    act_refs = sorted({f"Act {num} of {year}" for num, year in _ACT_REF_RE.findall(row_html)})
    if gazette_nums:
        meta["gazette_numbers"] = ",".join(gazette_nums)
    if rg_nums:
        meta["regulation_gazette_numbers"] = ",".join(rg_nums)
    if notice_codes:
        meta["notice_codes"] = ",".join(notice_codes)
    if act_refs:
        meta["act_refs"] = ",".join(act_refs)
    comment_by = _COMMENT_BY_RE.search(row_html)
    if comment_by:
        meta["comment_by_date"] = comment_by.group(1)

    return TaskSeed(
        type="govza_detail",
        params={
            "href": href,
            "title": title,
            "doc_date": doc_date,
            "meta": meta,
        },
    )


class ListHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        params: dict[str, Any] = {
            "field_gcisdoc_doctype": "All",
            "field_gcisdoc_subjects": "All",
            "field_gcisdoc_document_date[min]": str(task.params["date"]),
            "field_gcisdoc_document_date[max]": str(task.params["date"]),
        }
        page = str(task.params.get("page", "1"))
        if page != "1":
            params["page"] = page
        return RequestSpec(url=LIST_URL, params=params)

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        doc_date = str(task.params["date"])
        scope = str(task.params.get("scope", "policy"))
        types_raw = str(task.params.get("types", "")).strip()
        keep: frozenset[str] | None = (
            frozenset(TYPE_SLUGS[s] for s in types_raw.split(",")) if types_raw else None
        )
        day = doc_date
        page = str(task.params.get("page", "1"))
        label = f"{day}#{page}"

        html = response.content.decode("utf-8", errors="replace")
        rows = [m.group(1) for m in _ROW_RE.finditer(html)]
        has_table = 'class="cols-3"' in html
        no_results = "No Results" in html

        if not rows and not no_results:
            raise ValueError(
                f"govza_list {label}: neither listing rows nor the 'No Results' "
                f"marker found (HTTP {response.status_code}, "
                f"{len(response.content)} bytes) — listing shape may have moved"
            )
        if rows and not has_table:
            raise ValueError(
                f"govza_list {label}: rows present but no results table — "
                "listing shape may have moved"
            )

        result = TaskResult()
        if not rows:
            # Clean empty answer (weekend / no gazette / page past the
            # end): a fully consumed day slice — explained empty, cursor
            # still advances (USA empty-window precedent).
            result.expected_empty = (
                f"govza_list {label}: the portal answers 'No Results' "
                "(no documents dated this day)"
            )
            result.cursor_updates = {CURSOR_KEY: doc_date}
            return result

        kept = 0
        dropped = 0
        unclassified = 0
        for row_html in rows:
            date_cell = _DATE_TD_RE.search(row_html)
            row_date = ""
            if date_cell:
                date_in_cell = _DATE_RE.search(date_cell.group(1))
                if date_in_cell:
                    row_date = date_in_cell.group(1)
            if row_date != day:
                raise ValueError(
                    f"govza_list {label}: row dated {row_date or '?'} inside the "
                    f"{day} window — date filter semantics changed "
                    f"({_row_label(row_html)!r})"
                )
            try:
                native = _native_type(row_html)
            except _UnknownCategory as exc:
                raise ValueError(f"govza_list {label}: {exc}") from None
            except _UnclassifiableRow:
                unclassified += 1
                continue
            outside = native not in keep if keep is not None else (
                scope == "policy" and native in POLICY_EXCLUDED_TYPES
            )
            if outside:
                dropped += 1
                continue
            kept += 1
            result.next_tasks.append(_detail_seed(row_html, doc_date, native))

        if not result.next_tasks:
            reasons = [f"{dropped} filtered out by type selection"]
            if unclassified:
                reasons.append(f"{unclassified} unclassified rows skipped (no type "
                               "link, no act code — the portal's legacy long tail)")
            result.expected_empty = (
                f"govza_list {label}: all {len(rows)} rows produced nothing "
                f"({'; '.join(reasons)})"
            )

        # The day cursor only moves when the day's *last* page completed
        # (a full 30-row page continues via the next page and advances
        # nothing; the overshoot page answers 'No Results' above).
        if len(rows) < _PAGE_SIZE:
            result.cursor_updates = {CURSOR_KEY: doc_date}
        else:
            next_params = dict(task.params)
            next_params["page"] = str(int(page) + 1)
            result.next_tasks.append(
                TaskSeed(type="govza_list", params=next_params)
            )
        return result
