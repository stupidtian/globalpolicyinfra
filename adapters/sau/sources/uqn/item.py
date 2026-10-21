"""Task type ``uqn_item``: one gazette entry, one request, one document.

GET the item page and store the response bytes verbatim; every research
field comes from the page's embedded JSON-LD (probed shapes 2026-10-10,
samples in the task folder):

- ``NewsArticle``: ``headline`` (the native Arabic title — for decrees it
  carries the instrument number and the Hijri date, e.g. «قرار وزير
  التجارة رقم (70) وتاريخ 28/03/1448هـ») and ``datePublished`` (the
  gazette date, always 15:00+03:00 — the date part is publication_date);
- ``BreadcrumbList``: level-2/3 items name the section; the English URL
  slug (e.g. ``/decisions/ministerial-decisions``) is the stable key for
  the controlled doc_type mapping, the Arabic name is kept in meta;
- the page body's ``.article-desc`` block carries the full text inline —
  it stays in the stored HTML (cleaning is a later stage, not here).

Two native facts ride in meta without conversion (dual-calendar rule):
``native_number`` (رقم …) and ``native_date_hijri`` (the signing date in
the Islamic calendar) — both regexed out of the headline, invisible
right-to-left marks (U+200F) stripped from the captured values only (the
title itself is kept byte-faithful).

A 404 is *not* declared as data: the id came from a sitemap fetched
moments ago, so not-found means something truly broke and must fail loud.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.sau.sources.uqn import SITE
from core.document import DocumentRecord, compute_doc_id

__all__ = ["UqnItemHandler", "map_doc_type"]

_LD_BLOCK = re.compile(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', re.DOTALL)

#: Breadcrumb URL slug -> controlled doc_type (native section word always
#: kept in meta; cross-country typology is analysis-side, not here).
_SLUG_TO_TYPE: dict[str, str] = {
    "royal-decrees": "DECREE",  # مرسوم ملكي
    "royal-orders": "DECREE",  # أمر ملكي
    "council-of-ministers-decisions": "DECREE",
    "ministerial-decisions": "ORDER",
    "rules-and-regulations": "REGULATION",
}

_NUMBER = re.compile(r"رقم\s*\(([^)]+)\)")
_HIJRI = re.compile(r"(\d{1,2}[\s\u200f\u200e]*/[\s\u200f\u200e]*\d{1,2}[\s\u200f\u200e]*/[\s\u200f\u200e]*\d{4})\s*ه")
_BIDI_MARKS = str.maketrans("", "", "\u200f\u200e")


def map_doc_type(slug: str | None) -> str:
    return _SLUG_TO_TYPE.get(slug or "", "OTHER")


#: Field scrapers for the site's own malformed JSON-LD — the template emits
#: unescaped ASCII quotes inside string values (probed: item 4001950's
#: description, archived in the task folder 2026-10-11), so json.loads dies
#: on the whole block. Both fields we consume are single-line values:
#: scrape them to the last quote on their line instead of repairing JSON.
_HEADLINE_FIELD = re.compile(r'"headline"\s*:\s*"(.*)"\s*,?\s*$', re.MULTILINE)
_DATE_FIELD = re.compile(r'"datePublished"\s*:\s*"([^"]*)"')


def _extract_json_ld(content: bytes, uqn_id: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """First NewsArticle block (required) + first BreadcrumbList (optional)."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"item {uqn_id}: page is not UTF-8: {exc}") from exc
    news: dict[str, Any] | None = None
    crumbs: dict[str, Any] | None = None
    for raw in _LD_BLOCK.findall(text):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        if data.get("@type") == "NewsArticle" and news is None:
            news = data
        elif data.get("@type") == "BreadcrumbList" and crumbs is None:
            crumbs = data
    if news is None:
        # The block exists but does not parse (site-side escaping defect):
        # scrape the two single-line fields we consume from inside the
        # ld+json blocks. Everything else stays untouched — malformed
        # description/keywords are simply not collected.
        for raw in _LD_BLOCK.findall(text):
            headline = _HEADLINE_FIELD.search(raw)
            published = _DATE_FIELD.search(raw)
            if headline is not None and published is not None:
                news = {"headline": headline.group(1), "datePublished": published.group(1)}
                break
    if news is None:
        raise ValueError(f"item {uqn_id}: no NewsArticle JSON-LD — unexpected page shape")
    return news, crumbs


def _section_of(crumbs: dict[str, Any] | None, kind: str) -> tuple[str | None, str | None]:
    """(english slug, arabic name) of the section the item sits in."""
    if crumbs is None:
        return None, None
    fallback: tuple[str, str] | None = None
    for entry in crumbs.get("itemListElement", []):
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("item") or "")
        name = str(entry.get("name") or "")
        if "/decisions/" in url:
            return url.rstrip("/").rsplit("/", 1)[-1], name
        if kind == "advertisements" and url.rstrip("/").endswith("/advertisements") and name:
            fallback = ("advertisements", name)
    return fallback if fallback is not None else (None, None)


class UqnItemHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        uqn_id = str(task.params["id"])
        if str(task.params.get("kind", "decisions")) == "advertisements":
            url = f"{SITE}/advertisements/{uqn_id}"
        else:
            url = f"{SITE}/decisions-and-regulations/{uqn_id}"
        return RequestSpec(url=url)

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        uqn_id = str(task.params["id"])
        kind = str(task.params.get("kind", "decisions"))
        news, crumbs = _extract_json_ld(response.content, uqn_id)

        headline = str(news.get("headline") or "").strip()
        if not headline:
            raise ValueError(f"item {uqn_id}: NewsArticle carries no headline")
        pub_raw = str(news.get("datePublished") or "").strip()
        try:
            pub_date = date.fromisoformat(pub_raw[:10])
        except ValueError:
            pub_date = None
        # 1970-01-01 is the site's epoch-zero placeholder (probed on the
        # old-era pages' dateModified); a real gazette date never is.
        if pub_date is None or pub_date == date(1970, 1, 1):
            raise ValueError(
                f"item {uqn_id}: no usable datePublished ({pub_raw!r})"
            )
        pub_iso = pub_date.isoformat()

        slug, native = _section_of(crumbs, kind)
        meta: dict[str, str] = {"uqn_id": uqn_id, "kind": kind}
        if slug:
            meta["section"] = slug
        if native:
            meta["section_native"] = native
        number = _NUMBER.search(headline)
        if number:
            meta["native_number"] = number.group(1).translate(_BIDI_MARKS).strip()
        hijri = _HIJRI.search(headline)
        if hijri:
            meta["native_date_hijri"] = re.sub(r"\s+", "", hijri.group(1).translate(_BIDI_MARKS))

        if kind == "advertisements":
            source_url = f"{SITE}/advertisements/{uqn_id}"
        else:
            source_url = f"{SITE}/decisions-and-regulations/{uqn_id}"
        ymd = pub_iso.replace("-", "")
        path = f"01_raw/uqn/{pub_iso[:4]}/D{ymd}/{uqn_id}/item.html"

        document = DocumentRecord(
            title=headline,
            source_url=source_url,
            publication_date=pub_iso,
            doc_type=map_doc_type(slug),
            language="ara",
            raw_metadata=meta,
        )
        doc_id = compute_doc_id("SAU", source_url, pub_iso)

        return TaskResult(
            documents=[document],
            files=[FileOut(path=path, content=response.content, doc_id=doc_id)],
            # The gazette's issue page for this date carries the issue PDF;
            # task identity dedupes when many items share one issue date.
            next_tasks=[TaskSeed(type="uqn_issue", params={"date": pub_iso})],
        )
