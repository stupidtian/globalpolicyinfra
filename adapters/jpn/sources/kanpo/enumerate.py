"""Task types ``kanpo_day`` / ``kanpo_month`` / ``kanpo_issue``: the
enumeration chain of the Kanpo gazette (see the source docstring in
``adapters/jpn/sources/kanpo/__init__.py``).

All three parse the same machine-generated markup family (shapes probed
2026-09-07, samples archived with the task; see docs/countries/jpn/
kanpo-zh.md):

- day pages: ``<dt><a href="javascript:void(0);">本紙　第1780号</a></dt>``
  heads each issue block; inside, ``<section>`` blocks carry
  ``<h2|h3|h4 class="title"><span class="text">省令</span></h2>`` headings
  and ``<li><a href="…f.html"><span class="text">TITLE</span><span
  class="date">2</span></a></li>`` entries. Entries appear **only as
  links** on day pages (old and new alike — the page simply omits what
  the archive does not retain).
- issue TOC pages: same section/entry walk inside ``contentsBox``; on
  pre-2025-04-01 issues, non-retained entries show up **linkless**
  (``<li><span class="text">…</span><span class="date">6</span></li>``) —
  counted, never fetched. Navigation links (前ページ/次ページ) never carry
  the span pair, so the entry shape itself excludes them.
- month pages: one ``<a href="…/{YYYYMMDD}{letter}{seq}/{…}0000f.html">``
  per issue, labelled ``本紙<br>(第1698号)`` — era-tolerant (2003 issues
  carry plain relative hrefs, 2024+ ones a ``./`` prefix plus a sibling
  whole-issue PDF link that never matches the TOC shape).

Entry identity: the gazette addresses *pages*, not entries — several
entries routinely share one page PDF (2026-09-04 号外 page 2 carries four
政令). The ``e`` ordinal (position among the issue's linked entries, TOC
order) disambiguates and travels into the doc task's params.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.jpn.sources.kanpo import CURSOR_KEY, LAW_SECTIONS, SITE, USER_AGENT

__all__ = [
    "KanpoDayHandler",
    "KanpoIssueHandler",
    "KanpoMonthHandler",
    "map_doc_type",
]

_HEADERS = {"User-Agent": USER_AGENT}

#: Issue label on a day page: ``本紙　第1780号`` (full-width space).
_DT_ISSUE_RE = re.compile(
    r'<dt><a href="javascript:void\(0\);">([^<]+)</a></dt>'
)
#: Issue-type word + number inside any label.
_ISSUE_NO_RE = re.compile(r"(本紙|号外|特別号外|政府調達)[\s\u3000(（]*第(\d+)号")
#: Section heading of either level; text in the first span.text (some
#: headings append a page span, some old ones have bare text).
_HEADING_RE = re.compile(r"<h([234])[^>]*>(.*?)</h\1>", re.DOTALL)
#: A linked entry: the span pair is the shape that separates real entries
#: from every navigation link on these pages.
_ENTRY_RE = re.compile(
    r'<a href="([^"]+)">\s*<span class="text">(.*?)</span>\s*'
    r'<span class="date">(\d+)</span>\s*</a>',
    re.DOTALL,
)
#: An issue-TOC link on a month page (``{date}/{date}{letter}{seq}/
#: {date}{letter}{seq}0000f.html`` — 2003 issues carry plain relative
#: hrefs, 2024+ ones a ``./`` prefix; their sibling whole-issue PDF links
#: never match the TOC shape).
_MONTH_LINK_RE = re.compile(
    r'<a href="\.?/?(\d{8}/\d{8}[a-z]\d+/\d{8}[a-z]\d+0000f\.html)"[^>]*>(.*?)</a>',
    re.DOTALL,
)
_BASE_RE = re.compile(r"^(\d{8}[a-z]\d+\d{4})f\.html$")

_ORDINANCE_PARTS = frozenset(
    {"府令", "省令", "庁令", "内閣官房令", "内閣府令", "デジタル庁令", "内閣総理府令"}
)


def map_doc_type(section_h2: str) -> str:
    """Native section word -> controlled doc_type (native always kept in
    meta; cross-country typology is analysis-side, not collection-side)."""
    if section_h2 == "法律":
        return "STATUTE"
    if section_h2 == "政令":
        return "DECREE"
    if section_h2 in _ORDINANCE_PARTS or (
        "・" in section_h2
        and all(part in _ORDINANCE_PARTS for part in section_h2.split("・"))
    ):
        return "SECONDARY_LEGISLATION"
    if section_h2 == "法規的告示":
        return "REGULATION"
    return "OTHER"


def _in_law_scope(section_h2: str) -> bool:
    if section_h2 in LAW_SECTIONS:
        return True
    return "・" in section_h2 and all(
        part in _ORDINANCE_PARTS for part in section_h2.split("・")
    )


def _section_filter(raw: str) -> Any:
    """Resolve the sections param into a predicate over H2 names."""
    if raw == "all":
        return None
    if raw == "law":
        return _in_law_scope
    names = {p.strip() for p in raw.split(",") if p.strip()}
    return lambda h2: h2 in names


def _clean_text(fragment: str) -> str:
    text = html_lib.unescape(re.sub(r"<[^>]+>", "", fragment))
    return text.strip()


def _heading_text(inner: str) -> str:
    span = re.search(r'<span class="text">(.*?)</span>', inner, re.DOTALL)
    return _clean_text(span.group(1) if span else inner)


@dataclass(frozen=True)
class _Entry:
    base: str  # e.g. 20260901h017800002 (page-level, several entries may share it)
    title: str
    page: str
    h2: str
    h3: str
    h4: str


def _walk_entries(body: str) -> list[_Entry]:
    """Walk section headings and collect linked entries in TOC order."""
    entries: list[_Entry] = []
    headings = [(m.start(), m.end(), m.group(1), _heading_text(m.group(2)))
                for m in _HEADING_RE.finditer(body)]
    levels = {"2": "", "3": "", "4": ""}
    for idx, (start, end, level, text) in enumerate(headings):
        levels[level] = text
        segment_end = headings[idx + 1][0] if idx + 1 < len(headings) else len(body)
        segment = body[end:segment_end]
        for m in _ENTRY_RE.finditer(segment):
            filename = m.group(1).split("/")[-1]
            base_match = _BASE_RE.match(filename)
            if not base_match:
                continue  # e.g. the whole-issue bundle links on month pages
            entries.append(
                _Entry(
                    base=base_match.group(1),
                    title=_clean_text(m.group(2)),
                    page=m.group(3),
                    h2=levels["2"],
                    h3=levels["3"],
                    h4=levels["4"],
                )
            )
    return entries


def _count_linkless(body: str) -> int:
    return sum(
        1
        for block in re.findall(r"<li>(.*?)</li>", body, re.DOTALL)
        if "<a " not in block and 'class="text"' in block
    )


def _is_known_not_found(response: Response) -> bool:
    """The portal's fixed 158-byte 404 page (weekend/no-edition days,
    months beyond the 2003-07-15 archive start)."""
    return (
        response.status_code in (404, 410)
        and response.content.startswith(b"<!DOCTYPE HTML PUBLIC")
        and b"Not Found" in response.content
        and len(response.content) < 1024
    )


def _decode(response: Response, what: str) -> str:
    try:
        return response.content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{what}: body is not UTF-8: {exc}") from exc


def _doc_seed(
    *,
    date: str,
    ns: str,
    issue: str,
    entry: _Entry,
    ordinal: int,
    issue_no: str,
    issue_type: str,
) -> TaskSeed:
    params: dict[str, Any] = {
        "date": date,
        "ns": ns,
        "issue": issue,
        "base": entry.base,
        "e": ordinal,
        "title": entry.title,
        "page": entry.page,
        "issue_no": issue_no,
        "issue_type": issue_type,
        "h2": entry.h2,
    }
    if entry.h3:
        params["h3"] = entry.h3
    if entry.h4:
        params["h4"] = entry.h4
    return TaskSeed(type="kanpo_doc", params=params)


class KanpoDayHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        ymd = str(task.params["date"]).replace("-", "")
        prefix = "" if task.params.get("ns") == "root" else "/old"
        return RequestSpec(
            url=f"{SITE}{prefix}/{ymd}/{ymd}.fullcontents.html",
            headers=dict(_HEADERS),
            accept_not_found=True,
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        date = str(task.params["date"])
        ns = str(task.params.get("ns", "old"))
        types = {t for t in str(task.params.get("types", "h,g,t")).split(",") if t}
        scope = _section_filter(str(task.params.get("sections", "law")))

        if response.status_code in (404, 410):
            if not _is_known_not_found(response):
                raise ValueError(
                    f"day {date}: HTTP {response.status_code} with an unexpected "
                    f"body ({len(response.content)} bytes) — not the known "
                    "no-edition page"
                )
            return TaskResult(
                expected_empty=f"Kanpo has no edition on {date} (known 404 page)",
                cursor_updates={CURSOR_KEY: date},
            )

        html = _decode(response, f"day {date}")
        parts = _DT_ISSUE_RE.split(html)
        if len(parts) == 1:
            raise ValueError(
                f"day {date}: no issue blocks found (root element changed?)"
            )

        seeds: list[TaskSeed] = []
        issues_seen: list[str] = []
        entries_seen = 0
        for label, body in zip(parts[1::2], parts[2::2], strict=True):
            number = _ISSUE_NO_RE.search(label)
            if not number:
                raise ValueError(f"day {date}: issue label {label!r} carries no number")
            issue_type, issue_no = number.group(1), number.group(2)
            entries = _walk_entries(body)
            if not entries:
                continue  # nothing retained for this issue at all
            issue = entries[0].base[:14]  # {YYYYMMDD}{letter}{seq5}
            letter = issue[8]
            issues_seen.append(f"{issue_type}第{issue_no}号({letter})")
            if letter not in types:
                continue
            for ordinal, entry in enumerate(entries, start=1):
                entries_seen += 1
                if scope is not None and not scope(entry.h2):
                    continue
                seeds.append(
                    _doc_seed(
                        date=date,
                        ns=ns,
                        issue=issue,
                        entry=entry,
                        ordinal=ordinal,
                        issue_no=issue_no,
                        issue_type=issue_type,
                    )
                )

        if not seeds:
            return TaskResult(
                expected_empty=(
                    f"day {date}: issues [{','.join(issues_seen) or 'none'}] carry no "
                    f"entries within scope (types={sorted(types)}, "
                    f"{entries_seen} entries seen)"
                ),
                cursor_updates={CURSOR_KEY: date},
            )
        return TaskResult(next_tasks=seeds, cursor_updates={CURSOR_KEY: date})


class KanpoMonthHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        ym = str(task.params["ym"]).replace("-", "")
        return RequestSpec(
            url=f"{SITE}/old/{ym}.html",
            headers=dict(_HEADERS),
            accept_not_found=True,
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        ym = str(task.params["ym"])
        types = {t for t in str(task.params.get("types", "h,g,t")).split(",") if t}
        sections = str(task.params.get("sections", "law"))

        if response.status_code in (404, 410):
            if not _is_known_not_found(response):
                raise ValueError(
                    f"month {ym}: HTTP {response.status_code} with an unexpected "
                    "body — not the known archive-edge page"
                )
            return TaskResult(
                expected_empty=(
                    f"no online archive for {ym} (the archive starts 2003-07)"
                )
            )

        html = _decode(response, f"month {ym}")
        seeds: list[TaskSeed] = []
        issues_seen = 0
        for m in _MONTH_LINK_RE.finditer(html):
            issue = m.group(1).split("/")[1]  # {YYYYMMDD}{letter}{seq5}
            letter = issue[8]
            issues_seen += 1
            if letter not in types:
                continue
            number = _ISSUE_NO_RE.search(_clean_text(m.group(2)))
            if not number:
                raise ValueError(
                    f"month {ym}: issue link {m.group(1)!r} carries no label"
                )
            seeds.append(
                TaskSeed(
                    type="kanpo_issue",
                    params={
                        "date": f"{issue[:4]}-{issue[4:6]}-{issue[6:8]}",
                        "issue": issue,
                        "issue_no": number.group(2),
                        "issue_type": number.group(1),
                        "types": ",".join(sorted(types)),
                        "sections": sections,
                    },
                )
            )
        if not seeds:
            return TaskResult(
                expected_empty=(
                    f"month {ym}: {issues_seen} issues, none within types "
                    f"{sorted(types)}"
                )
            )
        return TaskResult(next_tasks=seeds)


class KanpoIssueHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        ymd = str(task.params["date"]).replace("-", "")
        issue = str(task.params["issue"])
        prefix = "" if task.params.get("ns") == "root" else "/old"
        return RequestSpec(
            url=f"{SITE}{prefix}/{ymd}/{issue}/{issue}0000f.html",
            headers=dict(_HEADERS),
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        date = str(task.params["date"])
        issue = str(task.params["issue"])
        issue_no = str(task.params.get("issue_no", ""))
        issue_type = str(task.params.get("issue_type", ""))
        scope = _section_filter(str(task.params.get("sections", "law")))

        html = _decode(response, f"issue {issue}")
        start = html.find("contentsBox")
        body = html[start:] if start >= 0 else html
        entries = _walk_entries(body)
        linkless = _count_linkless(body)
        if not entries:
            if linkless:
                # A listed issue whose entire content the archive never
                # retained (pre-2025-04-01): every entry is linkless.
                return TaskResult(
                    expected_empty=(
                        f"issue {issue}: {linkless} entries, all outside the "
                        "online archive's retention (linkless TOC rows)"
                    )
                )
            raise ValueError(
                f"issue {issue}: contentsBox carries no entries at all — "
                "unexpected for a listed issue"
            )

        seeds: list[TaskSeed] = []
        for ordinal, entry in enumerate(entries, start=1):
            if scope is not None and not scope(entry.h2):
                continue
            seeds.append(
                _doc_seed(
                    date=date,
                    ns=str(task.params.get("ns", "old")),
                    issue=issue,
                    entry=entry,
                    ordinal=ordinal,
                    issue_no=issue_no,
                    issue_type=issue_type,
                )
            )
        if not seeds:
            return TaskResult(
                expected_empty=(
                    f"issue {issue}: {len(entries)} linked entries, none within "
                    f"section scope ({_count_linkless(body)} linkless skipped)"
                )
            )
        return TaskResult(next_tasks=seeds)
