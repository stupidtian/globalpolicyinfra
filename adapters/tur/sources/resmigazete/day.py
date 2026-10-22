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
#: per-item-era file link, widened for the attachment tail (probed
#: 2002–2006, residual days): any document extension, an optional
#: sub-part label after the sequence number (``20050205-5-2.htm`` page two,
#: ``20050510-10-EK I.doc`` treaty annex), and a mükerrer mark whose digit
#: may be missing (``20050601M-1.htm``). The literal file name is the
#: item's address — it seeds the fetch and the doc identity.
_ITEM_FILE_RE = re.compile(
    r"(\d{8})(?:M(\d*))?-(\d+)(?:-([^./]+))?\.(htm|html|pdf|doc|xls|gif)$", re.IGNORECASE
)


def _part_order(part: str | None) -> tuple[int, str]:
    """Sort key picking an item's primary file: the un-suffixed file first,
    then numeric parts (1, 2, … 10), then labelled parts."""
    if not part:
        return (0, "")
    return (1, part) if part.isdigit() else (2, part)


def _file_prefix(name: str) -> str | None:
    """The item-grouping key of a numbered file name (``{ymd}[M{k}]-{seq}``):
    sub-parts and alternative formats of one item share it."""
    m = _ITEM_FILE_RE.fullmatch(name)
    if m is None:
        return None
    ymd, mark, seq = m.group(1), m.group(2) or "", m.group(3)
    return f"{ymd}{'M' + mark if mark else ''}-{seq}"

#: anchor-era item link (2000-06-28 … 2004-12): every entry of the day
#: addresses one shared whole-day file via a fragment, e.g.
#: ``…/eskiler/2002/11/20021114.htm#13`` — the fragment names the
#: ``<a name=…>`` marker where the entry's text starts (probed 2026-09-28).
#: The fragment is USUALLY numeric but not always (probed 2001-03-23:
#: ``#T.C.`` opens the day).
_ANCHOR_FILE_RE = re.compile(r"(\d{8})(?:M(\d+))?\.(htm|pdf)#([A-Za-z0-9_.]+)$", re.IGNORECASE)
#: the whole-issue file (``{ymd}[M{k}].pdf|.htm``, no -N suffix, no
#: fragment) — linked from inside the content block on messy early days;
#: deliberately not collected (samples 41/48).
_ISSUE_FILE_RE = re.compile(r"\d{8}(?:M\d+)?\.(htm|html|pdf)$", re.IGNORECASE)


def _normalize_typo(href: str, ymd: str) -> str:
    """The source occasionally mis-types the day prefix with one extra
    digit (probed 2000-07-31: ``200007031-3.pdf`` for ``20000731``). If
    deleting exactly one digit of a 9-digit prefix yields the task's day,
    rewrite the href to the canonical name — the addressed file is the
    day's own (a same-day fetch; anything else still fails its check)."""
    name = href.rsplit("/", 1)[-1]
    digits = re.match(r"\d+", name)
    if not digits:
        return href
    run = digits.group(0)
    if run == ymd or len(run) != 9:
        return href
    for i in range(9):
        if run[:i] + run[i + 1 :] == ymd:
            return href.replace(name, ymd + name[len(run) :], 1)
    return href


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
        # A fihrist-shaped page whose title block carries no issue number is
        # the probed degenerate shell (holidays / sparse early days answer
        # this instead of the homepage redirect; sample 42, 2026-10-09). It
        # is a legal empty only when the content block carries no items —
        # checked after the walk below.
        header_ok = issue_match is not None
        sayi = issue_match.group(1) if issue_match is not None else ""
        if header_ok:
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

        # Collect raw items first: the anchor era (2000-06-28…2004-12) and
        # the per-item era (2005-01…) get different task shapes below.
        raw_items: list[dict[str, str]] = []
        item_index_by_href: dict[str, int] = {}
        part_names: dict[str, list[str]] = {}
        freeform_links: list[str] = []
        bolum = ""
        tip = ""
        pos = 0
        for match in _NODE_RE.finditer(content):
            gap = _plain(content[pos : match.start()])
            gap = re.sub(r"^[^A-Za-zÇĞİÖŞÜçğıöşü]+", "", gap)  # stray "> " etc.
            if gap:
                tip = gap  # bare 2014-style type label between markables
            pos = match.end()
            if match.group("title") is not None:
                bolum = _plain(match.group("title"))
            elif match.group("subtitle") is not None:
                tip = _plain(match.group("subtitle"))
            else:
                href = _normalize_typo(unescape(match.group("href")).strip(), date.replace("-", ""))
                title = _plain(match.group("text"))
                name = href.rsplit("/", 1)[-1]
                is_anchor_form = bool(_ANCHOR_FILE_RE.search(href))
                if not name:
                    continue  # broken/empty link (probed 2002-03-27)
                # The whole-issue file link (``{ymd}[M{k}].pdf`` with no -N
                # and no fragment) also appears inside the content block —
                # not an item, deliberately not collected (samples 41/48).
                if not is_anchor_form and "#" not in href and _ISSUE_FILE_RE.fullmatch(name):
                    continue
                # Free-form annex blobs (``F01.htm``, ``RG 1.doc``,
                # ministry spreadsheets — no {ymd}-{seq} name): skipped,
                # counted, and named in the day's empty note when they are
                # the day's only links (probed annex editions 2004-12-29…).
                if (
                    not is_anchor_form
                    and "#" not in href
                    and not _ITEM_FILE_RE.fullmatch(name)
                ):
                    freeform_links.append(name)
                    continue
                if scope != "all" and "/ilanlar/" in href.lower():
                    continue  # İLÂN announcement file — outside default scope
                # İLÂN headings: in the anchor era the announcements live
                # inside the same day file, addressed by anchors like every
                # other entry — told apart by the section heading only.
                if scope != "all" and "İLÂN" in bolum.upper():
                    continue
                if href in item_index_by_href:
                    # A repeated href is either a TITLE CONTINUATION row
                    # (long titles wrap: the second row carries no list
                    # marker "—" and may even be empty; probed 2000-07-02
                    # #1 "2000/850" + treaty name) or — anchor form only —
                    # a second document sharing the section (both rows start
                    # with the marker; probed 2002-11-14 #13).
                    if title and not re.match(r"^[—–-]", title):
                        prior = raw_items[item_index_by_href[href]]
                        prior["title"] = (prior["title"] + " " + title).strip()
                    elif is_anchor_form and title:
                        raw_items.append(
                            {"href": href, "title": title, "bolum": bolum, "tip": tip}
                        )
                    # empty continuation row / per-item relisting: nothing to add
                    continue
                if not is_anchor_form:
                    file_match = _ITEM_FILE_RE.fullmatch(name)
                    if file_match:
                        y, mk, sq = file_match.group(1), file_match.group(2) or "", file_match.group(3)
                        # İLÂN files share basenames with items but live under
                        # ilanlar/eskiilanlar/ — the group key and identity
                        # carry the directory to keep them apart
                        rel = href.split("resmigazete.gov.tr/", 1)[-1]
                        part_names.setdefault(
                            f"{rel.rsplit('/', 1)[0]}::{y}{'M' + mk if mk else ''}-{sq}", []
                        ).append(name)
                item_index_by_href[href] = len(raw_items)
                raw_items.append(
                    {"href": href, "title": title, "bolum": bolum, "tip": tip}
                )

        if not header_ok:
            if not raw_items:
                return TaskResult(
                    expected_empty=(
                        f"degenerate fihrist shell for {date} M{mukerrer} — no issue "
                        "header and no items (holiday / sparse-day shape, sample 42)"
                    ),
                    cursor_updates={CURSOR_KEY: date},
                )
            raise ValueError(
                f"fihrist {date} M{mukerrer}: issue header carries no number but "
                f"{len(raw_items)} items are listed ({header!r})"
            )

        seeds: list[TaskSeed] = []
        anchor_items = [it for it in raw_items if _ANCHOR_FILE_RE.search(it["href"])]
        file_items = [it for it in raw_items if not _ANCHOR_FILE_RE.search(it["href"])]
        if anchor_items:
            # One fetch per day: the single rg_item splits the day file into
            # per-entry slices (user-ruled 2026-09-28; the anchors are the
            # source's own entry boundaries). A day may legitimately carry
            # per-item links alongside (probed 2000-07-02: those were the
            # whole-issue PDF, already skipped — but genuine mixed days get
            # both task shapes rather than an error).
            entries: list[dict[str, Any]] = []
            for ordinal, item in enumerate(anchor_items, start=1):
                anchor_match = _ANCHOR_FILE_RE.search(item["href"])
                if anchor_match is None:  # pragma: no cover — anchor_items is pre-filtered
                    raise ValueError(f"not an anchor link: {item['href']!r}")
                file_ymd, file_m, ext, anchor_no = anchor_match.groups()
                # An unmarked file name on a mükerrer TOC is the source's
                # own sloppiness (probed 2000-10-04 M1: distinct content, the
                # marked day file exists) — fetch and identity stay on the
                # marked form; any other mismatch is real drift.
                if file_ymd != date.replace("-", "") or (
                    int(file_m or 0) != mukerrer and not (int(file_m or 0) == 0 and mukerrer > 0)
                ):
                    raise ValueError(
                        f"fihrist {date} M{mukerrer}: anchor item names another "
                        f"edition ({item['href']!r})"
                    )
                entries.append(
                    {
                        "i": ordinal,
                        "k": anchor_no,  # usually numeric; "T.C." occurs (2001-03-23)
                        "ext": ext.lower(),
                        "bolum": item["bolum"],
                        "tip": item["tip"],
                        "title": re.sub(r"^[\s–—-]+", "", item["title"]).strip(),
                    }
                )
            seeds.append(
                TaskSeed(
                    type="rg_item",
                    params={
                        "mode": "dayfile",
                        "date": date,
                        "mukerrer": mukerrer,
                        "sayi": sayi,
                        "entries": entries,
                    },
                )
            )
        # seed one task per numbered item; sub-part files of the same item
        # (page/annex splits sharing the seq) ride as recorded siblings
        seeded_prefixes: set[str] = set()
        for item in file_items:
            name = item["href"].rsplit("/", 1)[-1]
            item_match = _ITEM_FILE_RE.fullmatch(name)
            if item_match is None:
                raise ValueError(
                    f"fihrist {date} M{mukerrer}: item file name not in the known "
                    f"shape ({item['href']!r})"
                )
            y, mk, sq = item_match.group(1), item_match.group(2) or "", item_match.group(3)
            rel = item["href"].split("resmigazete.gov.tr/", 1)[-1]
            dirkey = rel.rsplit("/", 1)[0]
            prefix = f"{dirkey}::{y}{'M' + mk if mk else ''}-{sq}"
            if prefix in seeded_prefixes:
                continue
            seeded_prefixes.add(prefix)
            group = [
                it
                for it in file_items
                if it["href"].split("resmigazete.gov.tr/", 1)[-1].rsplit("/", 1)[0] == dirkey
                and _file_prefix(it["href"].rsplit("/", 1)[-1])
                == f"{y}{'M' + mk if mk else ''}-{sq}"
            ]
            def _part_of(href: str) -> str | None:
                m = _ITEM_FILE_RE.fullmatch(href.rsplit("/", 1)[-1])
                return m.group(4) if m else None

            primary = min((it["href"] for it in group), key=lambda h: _part_order(_part_of(h)))
            titled = next((it for it in group if it["title"]), group[0])
            self._seed_item(
                seeds, date, mukerrer, sayi,
                titled["bolum"], titled["tip"], primary, titled["title"],
                [
                    n
                    for n in part_names.get(prefix, [])
                    if n != primary.rsplit("/", 1)[-1]
                ],
            )

        probe: dict[str, Any] = {"date": date, "mukerrer": mukerrer + 1, "scope": scope}
        result = TaskResult(
            next_tasks=seeds + [TaskSeed(type="rg_day", params=probe)],
            cursor_updates={CURSOR_KEY: date},
        )
        if not seeds:
            note = (
                f"gazette {sayi or '?'} of {date} (mükerrer {mukerrer}) carries no "
                "in-scope items (İLÂN-only or the empty first-month Word shell)"
            )
            if freeform_links:
                note += (
                    f"; {len(freeform_links)} free-form annex file link(s) skipped "
                    f"({freeform_links[0]!r}…)"
                )
            result.expected_empty = note
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
        siblings: list[str],
    ) -> None:
        """Seed one numbered item from its PRIMARY literal link — the site
        path is both the fetch address and the identity base, carrying
        whatever mark/case/part/directory the source itself used. Sub-part
        siblings are recorded, not fetched (the MBS pdf/doc URL rule)."""
        name = href.rsplit("/", 1)[-1]
        rel = href.split("resmigazete.gov.tr/", 1)[-1]
        file_match = _ITEM_FILE_RE.fullmatch(name)
        if file_match is None:
            raise ValueError(
                f"fihrist {date} M{mukerrer}: item file name not in the known "
                f"shape ({name!r})"
            )
        file_ymd, file_m, seq, _part, ext = file_match.groups()
        # A link naming ANOTHER day (probed 2005-05-02 item 7 → 20050505-7)
        # or another edition (base TOC linking an M-file) is the source's
        # cross-reference: the file belongs to its own day's walk, which
        # collects it — skip here rather than double-collect.
        mark_digits = file_m or ""
        if file_ymd != date.replace("-", "") or (
            mark_digits != (str(mukerrer) if mukerrer else "")
            and not (mark_digits == "" and mukerrer > 0)
        ):
            return
        text = re.sub(r"^[\s–—-]+", "", title).strip() or name
        seeds.append(
            TaskSeed(
                type="rg_item",
                params={
                    "date": date,
                    "mukerrer": mukerrer,
                    "seq": int(seq),
                    "name": name,
                    "rel": rel,
                    "ext": ext.lower(),
                    "siblings": siblings,
                    "sayi": sayi,
                    "bolum": bolum,
                    "tip": tip,
                    "title": text,
                },
            )
        )
