"""Task type ``rg_day``: one edition (day × mükerrer ordinal) of the gazette.

GET the server-rendered fihrist page and walk its hierarchy. Three probed
behaviours shape this handler (2026-09-27, samples in the task folder):

- **No edition / no such mükerrer = 302 → homepage.** The transport follows
  the redirect, so parse sees a 200 homepage body. The fingerprint is the
  issue-header block ``preview-title``: every real fihrist page has it
  (six probed editions across 2000/2014/2026, base and mükerrer), homepage
  and day pages never do. A body with neither marker is an unknown shape
  and fails loudly.
- **The İLÂN section has no heading of its own** inside the content block:
  announcement items are told apart by their file path (``/ilanlar/``).
  The default scope drops them; announcement files are also only
  category-level (one file per category per day).
- **Type subheadings come in two shapes**: a ``html-subtitle`` div (2026
  markup) or bare text between the section title and the first item (2014
  markup — ``…</div>BAKANLAR KURULU KARARLARI<div class="fihrist-item…``).
  The walk treats any tag-free gap text between matches as the current
  type. Section titles (``html-title``) are optional (many editions carry
  type subheadings only).

The task always seeds the next mükerrer probe (user-ruled 2026-09-28,
"chain-probe"): completeness is guaranteed at the cost of exactly one
homepage redirect per day; the base page's own mükerrer navigation links
are deliberately not parsed (the chain already covers every ordinal).
Every fully consumed edition — items or not — advances ``rg_last_date``;
the chain's terminal probe writes the same value, so the cursor always
lands on the task's own date.
"""

from __future__ import annotations

import re
from html import unescape
from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.tur.sources.resmigazete import API_BASE, CURSOR_KEY

__all__ = ["RgDayHandler"]

_FIHRIST_URL = f"{API_BASE}/fihrist"

_TURKISH_MONTHS: dict[str, int] = {
    "ocak": 1,
    "şubat": 2,
    "mart": 3,
    "nisan": 4,
    "mayıs": 5,
    "haziran": 6,
    "temmuz": 7,
    "ağustos": 8,
    "eylül": 9,
    "ekim": 10,
    "kasım": 11,
    "aralık": 12,
}

#: content region = html-content … filter-content (both present on every
#: probed page; the archived first-day Word-shell carries the pair too).
_CONTENT_RE = re.compile(r'id="html-content".*?(?=id="filter-content"|$)', re.DOTALL)

#: the three markables inside the content region, plus the gap text between
#: them (bare 2014-style type labels live in those gaps).
_NODE_RE = re.compile(
    r'<div class="card-title html-title"[^>]*>(?P<title>.*?)</div>'
    r'|<div class="html-subtitle"[^>]*>(?P<subtitle>.*?)</div>'
    r'|<div class="fihrist-item[^"]*"[^>]*>\s*<a[^>]+href="(?P<href>[^"]+)"[^>]*>'
    r"(?P<text>.*?)</a",
    re.DOTALL,
)

_ISSUE_NO_RE = re.compile(r"(\d+)\s+Say")
_MUKERRER_RE = re.compile(r"(\d+)\.\s*Mükerrer")
_HEADER_DATE_RE = re.compile(r"(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)\s+(\d{4})")
_ITEM_FILE_RE = re.compile(r"(\d{8})(?:M(\d+))?-(\d+)\.(htm|pdf)$", re.IGNORECASE)


def _plain(fragment: str) -> str:
    """Tag-strip, entity-unescape, collapse whitespace."""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _parse_header_date(text: str) -> tuple[int, int, int] | None:
    """'26 Eylül 2026' → (2026, 9, 26) using the Turkish month names."""
    match = _HEADER_DATE_RE.search(text)
    if not match:
        return None
    month = _TURKISH_MONTHS.get(match.group(2).lower())
    if month is None:
        return None
    return int(match.group(3)), month, int(match.group(1))


class RgDayHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        date = str(task.params["date"])
        mukerrer = int(task.params.get("mukerrer", 0))
        params: dict[str, str] = {"tarih": date}
        if mukerrer > 0:
            params["mukerrer"] = str(mukerrer)
        return RequestSpec(url=_FIHRIST_URL, params=params)

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        date = str(task.params["date"])
        mukerrer = int(task.params.get("mukerrer", 0))
        scope = str(task.params.get("scope", "mevzuat"))
        page = response.content.decode("utf-8", errors="replace")

        if "preview-title" not in page:
            if 'id="gunluk-akis"' in page:
                return TaskResult(
                    expected_empty=(
                        f"no edition for {date} at mükerrer {mukerrer} "
                        "(homepage shape: pre-2000-06-28 archive boundary or "
                        "no such extra edition)"
                    ),
                    cursor_updates={CURSOR_KEY: date},
                )
            raise ValueError(
                f"fihrist {date} M{mukerrer}: unexpected body (no preview-title, "
                f"not the known homepage shape either; {len(response.content)} bytes)"
            )

        header_match = re.search(r"preview-title[^>]*>(.*?)</div>", page, re.DOTALL)
        if header_match is None:
            raise ValueError(f"fihrist {date} M{mukerrer}: malformed preview-title block")
        header = _plain(header_match.group(1))
        issue_match = _ISSUE_NO_RE.search(header)
        if not issue_match:
            raise ValueError(f"fihrist {date} M{mukerrer}: issue header carries no number ({header!r})")
        sayi = issue_match.group(1)
        mukerrer_match = _MUKERRER_RE.search(header)
        header_m = int(mukerrer_match.group(1)) if mukerrer_match else 0
        if header_m != mukerrer:
            raise ValueError(
                f"fihrist {date}: asked for mükerrer {mukerrer} but the page is "
                f"mükerrer {header_m} ({header!r})"
            )
        ymd = _parse_header_date(header)
        if ymd is None or f"{ymd[0]:04d}-{ymd[1]:02d}-{ymd[2]:02d}" != date:
            found = "-".join(f"{v:02d}" if i else f"{v:04d}" for i, v in enumerate(ymd)) if ymd else "?"
            raise ValueError(
                f"fihrist task for {date} received an edition dated {found} "
                f"(header {header!r})"
            )

        content_match = _CONTENT_RE.search(page)
        if content_match is None:
            raise ValueError(f"fihrist {date} M{mukerrer}: no html-content block")
        content = content_match.group(0)

        seeds: list[TaskSeed] = []
        seen_paths: set[str] = set()
        bolum = ""
        tip = ""
        pos = 0
        for match in _NODE_RE.finditer(content):
            gap = _plain(content[pos : match.start()])
            if re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]", gap):
                tip = gap  # bare 2014-style type label between markables
            pos = match.end()
            if match.group("title") is not None:
                bolum = _plain(match.group("title"))
            elif match.group("subtitle") is not None:
                tip = _plain(match.group("subtitle"))
            else:
                href = unescape(match.group("href")).strip()
                title = _plain(match.group("text"))
                if href in seen_paths:
                    raise ValueError(f"fihrist {date} M{mukerrer}: item listed twice ({href})")
                seen_paths.add(href)
                if scope != "all" and "/ilanlar/" in href.lower():
                    continue  # İLÂN announcement file — outside default scope
                self._seed_item(seeds, date, mukerrer, sayi, bolum, tip, href, title)

        probe: dict[str, Any] = {"date": date, "mukerrer": mukerrer + 1, "scope": scope}
        result = TaskResult(
            next_tasks=seeds + [TaskSeed(type="rg_day", params=probe)],
            cursor_updates={CURSOR_KEY: date},
        )
        if not seeds:
            result.expected_empty = (
                f"gazette {sayi} of {date} (mükerrer {mukerrer}) carries no "
                "in-scope items (İLÂN-only or the empty first-month Word shell)"
            )
        return result

    def _seed_item(
        self,
        seeds: list[TaskSeed],
        date: str,
        mukerrer: int,
        sayi: str,
        bolum: str,
        tip: str,
        href: str,
        title: str,
    ) -> None:
        name = href.rsplit("/", 1)[-1]
        file_match = _ITEM_FILE_RE.search(name)
        if file_match is None:
            raise ValueError(
                f"fihrist {date} M{mukerrer}: item file name not in the known "
                f"shape ({href!r})"
            )
        file_ymd, file_m, seq, ext = file_match.groups()
        if file_ymd != date.replace("-", ""):
            raise ValueError(
                f"fihrist {date} M{mukerrer}: item file names another day "
                f"({href!r})"
            )
        if int(file_m or 0) != mukerrer:
            raise ValueError(
                f"fihrist {date} M{mukerrer}: item file mükerrer mark is "
                f"{file_m or 0} ({href!r})"
            )
        text = re.sub(r"^[\s–—-]+", "", title).strip() or name
        seeds.append(
            TaskSeed(
                type="rg_item",
                params={
                    "date": date,
                    "mukerrer": mukerrer,
                    "seq": int(seq),
                    "ext": ext.lower(),
                    "sayi": sayi,
                    "bolum": bolum,
                    "tip": tip,
                    "title": text,
                },
            )
        )
