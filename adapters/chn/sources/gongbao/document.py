"""Task type ``gongbao_doc``: one gazette article = one document.

The article page (probed 2026-10-02 on four real documents across both
generations: a State Council decree 国务院令第846号, a ministerial rule
市监总局令第128号, a State Council Office notification 国办发〔2026〕24号,
and a 2000-era CPC document 中发〔2000〕16号; samples archived) carries the
whole document inline in ``<div class="pages_content" id="UCAP-CONTENT">``,
a hidden ``.share-title`` block with the article title (present in BOTH
generations), and — decree/rule shapes — a ``.share-substr`` block quoting
the promulgation statement.

Chinese official documents date themselves in four distinct shapes; the
publication date is picked in this order (each rule only fires when the
probed shape is really there, and everything it found travels to ``meta``):

1. **Signature line** (decree shapes): a date shortly after a title-holder
   signature — 总理 李强 2026年9月6日. The legal promulgation date of
   令-type documents.
2. **Tail date** (document shapes, GB/T 9704 layout): the last date of the
   body preceded by the issuing organ and followed only by a short
   annotation — 国务院办公厅 2026年9月3日 （本文有删减）. The 成文日期.
3. **Head parenthetical** (rule/CPC shapes): a leading （…通过…公布…施行）
   block — publication is the 公布 date (or the 通过 date when no 公布
   date exists, e.g. （2000年10月11日…通过）).
4. **First date in the head** — fallback, flagged ``date_fallback=text_head``;
   nothing at all → ``date_fallback=none``.

The site's ``firstpublishedtime`` meta is the *upload* timestamp and is
never used as a publication date.

Issue context (``year``/``issue_id``/``issue_no``) rides in the task params
from the TOC parse — the raw file lands in that issue's folder regardless
of which link generation the canonical path came from.
"""

from __future__ import annotations

import re

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.chn.sources.gongbao import (
    canonical_article_url,
    issue_folder,
    normalize_space,
)
from core.document import DocumentRecord, compute_doc_id
from runtime.stages.cleaning import html_to_text

__all__ = ["GongbaoDocHandler", "map_doc_type", "parse_publication_date"]

_CN_DATE = r"(\d{4})年(\d{1,2})月(\d{1,2})日"
_CN_DATE_RE = re.compile(_CN_DATE)
_SHARE_TITLE_RE = re.compile(r'<div class="share-title"[^>]*>(.*?)</div>', re.DOTALL)
_TITLE_TAG_RE = re.compile(r"<title>(.*?)</title>", re.DOTALL)
_SITE_SUFFIX_RE = re.compile(r"__\d{4}年第\d+号国务院公报_中国政府网\s*$")
_UPLOAD_DATE_RE = re.compile(
    r'firstpublishedtime"[^>]*content="(\d{4})-(\d{2})-(\d{2})'
)
_SIGNATURE_DATE_RE = re.compile(
    r"(?:总\s*理|副总?\s*理|部\s*长|副部\s*长|署\s*长|行\s*长|董\s*事\s*长|"
    r"审\s*计\s*长|主\s*任|委\s*员\s*长|主\s*席)[\s\S]{0,40}?" + _CN_DATE
)
# GB/T 9704 signature block: the issuing organ on its own line, the date on
# the next. Line-anchored (MULTILINE) on purpose: rule texts end with dates
# inside sentences (…自…起施行。《…》同时废止。) and must not match, while
# the 成文日期 may legitimately be followed by an attachment section
# （附　件…, probed 2026-10-02 on 人社部发〔2026〕44号）.
_TAIL_DATE_RE = re.compile(
    r"(?m)^([\u4e00-\u9fff][\u4e00-\u9fff·]{1,24})\s*\n" + _CN_DATE + r"\s*$"
)
_PAREN_BLOCK_RE = re.compile(r"[（(][^（）()]{4,120}[）)]")
_ADOPTED_RE = re.compile(_CN_DATE + r"[^）)]{0,60}?通过")
# The 公布 date's suffix is the order number (…令第N号公布, short); the gap
# must not swallow a *second* date — the probed rule shape carries 通过 and
# 公布 dates in one parenthetical and the leftmost date must not claim the
# other's 公布 (2026-10-02, 市监总局令第128号: 05-19 通过 / 05-25 公布).
_PUBLISHED_RE = re.compile(
    _CN_DATE + r"(?:(?!\d{4}年)[^）)]){0,25}?公布"
)
_EFFECTIVE_RE = re.compile(r"自\s*" + _CN_DATE + r"\s*起施行")
_WENHAO_RE = re.compile(r"[\u4e00-\u9fff]{1,14}〔(\d{4})〕(\d{1,5})号")
_PROMULGATION_NO_RE = re.compile(r"[令号]\s*[（(]\s*第?\s*(\d{1,6})\s*号?\s*[）)]")
_LEADER_RE = re.compile(r"[·•‧\u2026]{2,}")
# Joint orders carry whitespace/顿号 between organs (probed 2026-10-02:
# 国家互联网信息办公室 中华人民共和国公安部令（第25号）)
_ORGAN_ORDER_RE = re.compile(r"^([\u4e00-\u9fff][\u4e00-\u9fff\s、]{0,40}?)令\s*[（(]")


def _iso(match: re.Match[str]) -> str:
    year, month, day = (int(g) for g in match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


def map_doc_type(title: str) -> tuple[str, str]:
    """Title-shape → (doc_type, native_type); nothing guessed beyond the
    probed shapes, everything else stays OTHER with native_type empty."""
    if "国务院令" in title:
        return "DECREE", "国务院令"
    match = _ORGAN_ORDER_RE.match(title)
    if match is not None:  # 部门令 shapes (总局令/部令/委员会令/联合令…)
        return "SECONDARY_LEGISLATION", f"{match.group(1)}令"
    if title.startswith("国务院办公厅"):
        return "OTHER", "国办文件"
    if re.match(r"^国务院(?![办公厅令])", title):
        return "OTHER", "国务院文件"
    return "OTHER", ""


def _extract_title(html: str) -> str:
    share = _SHARE_TITLE_RE.search(html)
    if share is not None:
        return normalize_space(share.group(1))
    title_tag = _TITLE_TAG_RE.search(html)
    if title_tag is None:
        raise ValueError("article page carries neither share-title nor <title>")
    return normalize_space(_SITE_SUFFIX_RE.sub("", title_tag.group(1)))


def _extract_body(html_bytes: bytes, path: str) -> str:
    """Body text via the framework's pure extraction stage on the probed
    container (``#UCAP-CONTENT`` — one stable container across both page
    generations; the surrounding page is site furniture). Zero match raises
    ValueError: unseen shapes are production shapes — escalate, never guess."""
    try:
        return html_to_text(html_bytes, keep="#UCAP-CONTENT")
    except ValueError as exc:
        raise ValueError(f"article {path}: {exc}") from exc


def _tail_date(body: str) -> str:
    """GB/T 9704 tail shape: the issuing organ alone on one line, the 成文
    date alone on the next (an attachment section or annotation may follow —
    the LAST such block wins, probed 2026-10-02 on 人社部发〔2026〕44号 where
    附件 follows the date). Sentence-internal dates never match because they
    are not standalone lines."""
    tail = ""
    for match in _TAIL_DATE_RE.finditer(body):
        date = _CN_DATE_RE.search(match.group(0))
        assert date is not None  # the tail pattern embeds the date shape
        tail = _iso(date)
    return tail


def parse_publication_date(
    body: str, upload_date: str | None = None
) -> dict[str, str]:
    """Ordered publication-date resolution; returns whatever it found —
    keys: publication_date, effective_date, adoption_date, date_fallback.

    ``upload_date`` is the page's ``firstpublishedtime`` meta — the site's
    own online-publication timestamp, used only as a *flagged* last resort
    (``date_fallback=firstpublished``) for documents whose text carries no
    legal date at all (probed at backfill scale, 2026-10-03: on 400 random
    dateless pages its year matched the document year 400/400 — the old-era
    pages went online contemporaneously, not in a later re-upload)."""
    out: dict[str, str] = {}

    effective = _EFFECTIVE_RE.search(body)
    if effective is not None:
        out["effective_date"] = _iso(effective)

    adopted = _ADOPTED_RE.search(body)
    if adopted is not None:
        out["adoption_date"] = _iso(adopted)

    signature = _SIGNATURE_DATE_RE.search(body[:800])
    if signature is not None:
        out["publication_date"] = _iso(signature)
        return out

    tail = _tail_date(body)
    if tail:
        out["publication_date"] = tail
        return out

    head = body[:800]
    for block in _PAREN_BLOCK_RE.findall(head):
        published = _PUBLISHED_RE.search(block)
        if published is not None:
            out["publication_date"] = _iso(published)
            return out
        adopted_in_block = _ADOPTED_RE.search(block)
        if adopted_in_block is not None:
            # （2000年10月11日…通过）: adoption doubles as the publication date
            out.setdefault("adoption_date", _iso(adopted_in_block))
            out["publication_date"] = _iso(adopted_in_block)
            return out

    first = _CN_DATE_RE.search(head)
    if first is not None:
        out["publication_date"] = _iso(first)
        out["date_fallback"] = "text_head"
        return out

    if upload_date:
        out["publication_date"] = upload_date
        out["date_fallback"] = "firstpublished"
        return out

    out["date_fallback"] = "none"
    return out


def _authority(title: str, toc: str) -> str:
    if "国务院令" in title:
        return "中华人民共和国国务院"
    match = _ORGAN_ORDER_RE.match(title)
    if match is not None:
        return match.group(1)
    # TOC-line authority suffix: "标题 ……… 机关 署名"
    if toc:
        parts = _LEADER_RE.split(toc)
        if len(parts) > 1 and parts[-1].strip():
            return parts[-1].strip()
    return ""


class GongbaoDocHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=canonical_article_url(str(task.params["path"])))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = task.params
        path = str(params["path"])
        toc = str(params.get("toc", ""))
        year = str(params["year"])  # the catalog year (meta), not necessarily
        issue_path = str(params["issue_path"])  # the URL's first segment
        if response.status_code != 200:
            raise ValueError(
                f"article {path} returned HTTP {response.status_code}"
            )
        html = response.content.decode("utf-8", errors="replace")

        title = _extract_title(html)
        if not title:
            raise ValueError(f"article {path} carries an empty title")
        body = _extract_body(response.content, path)

        upload = _UPLOAD_DATE_RE.search(html)
        dates = parse_publication_date(
            body, f"{upload.group(1)}-{upload.group(2)}-{upload.group(3)}" if upload else None
        )

        meta: dict[str, str] = {
            "native_type": map_doc_type(title)[1],
            "year": year,
            # the URL's last segment minus the modern "issue_" prefix
            # ("13006", or a legacy bare number such as "2006")
            "issue_id": issue_path.rsplit("/", 1)[-1].removeprefix("issue_"),
            "issue_no": str(params.get("issue_no", "")),
            "content_id": path.rsplit("/", 1)[-1],
            "toc_title": toc,
        }
        for key in ("effective_date", "adoption_date", "date_fallback"):
            if dates.get(key):
                meta[key] = dates[key]
        wenhao = _WENHAO_RE.search(body[:800])
        if wenhao is not None:
            meta["wenhao"] = wenhao.group(0)
        promulgation_no = _PROMULGATION_NO_RE.search(title)
        if promulgation_no is not None:
            meta["promulgation_no"] = promulgation_no.group(1)

        publication_date = dates.get("publication_date") or None
        record = DocumentRecord(
            title=title,
            source_url=canonical_article_url(path),
            publication_date=publication_date,
            issuing_authority=_authority(title, toc) or None,
            doc_type=map_doc_type(title)[0],
            language="zho",
            raw_metadata=meta,
        )
        doc_id = compute_doc_id("CHN", record.source_url, publication_date)
        content_id = meta["content_id"]
        file_path = f"{issue_folder(issue_path)}/{content_id}"
        return TaskResult(
            documents=[record],
            files=[FileOut(path=file_path, content=response.content, doc_id=doc_id)],
        )
