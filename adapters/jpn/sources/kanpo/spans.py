"""Task types ``kanpo_span_issue`` / ``kanpo_page``: the continuation-page
backfill (gap found 2026-10-15, user-approved repair).

The gazette portal serves one PDF per *page* of an issue; the TOC links
only each entry's START page, so the original collection fetched exactly
those. A multi-page entry's remaining pages — separate one-page files no
page ever links to — were never fetched (~97k interior pages quantified
from URL page segments).

The repair chain, seeded from a ledger-derived kv manifest
(``span_manifest.py`` → ``kanpo_span_manifest``):

===============  =====================================================
kanpo_span_issue re-fetch one issue's TOC with **all** sections (the
                 original collection parsed only the law-family scope,
                 so non-law starts — which bound a law entry's span —
                 were never recorded). Walks every entry in page order,
                 groups same-page starts into blocks, and for every
                 law-owned block seeds one ``kanpo_page`` per unfetched
                 page up to the next block's start. The last block of
                 the issue probes past its last known page via a chain
                 (each page seeds the next until the portal answers its
                 fixed 404 = issue end).
kanpo_page       GET one continuation-page PDF (``{issue}/pdf/
                 {issue}{page:04d}.pdf``). Registers a **page-level
                 continuation document** — the entry stays the research
                 unit; the page carries ``meta.span_from`` (the block's
                 start page) and a descriptive owner title so analysis
                 side joins entry text = its start page + its span's
                 continuation docs, ordered by ``meta.page``. A 404 with
                 the portal's known error shape is the chain's clean end
                 (expected_empty); unknown shapes escalate loudly.
===============  =====================================================

Filing: ``01_raw/kanpo/{YYYY}/D{date}/{issue}/{issue}{page:04d}/
{issue}{page:04d}.pdf`` — the page folder lacks the ``e{n}`` suffix of
entry folders, so the two populations are distinguishable on disk.

Scope stays disciplined: only pages whose owning block contains a
law-family entry are fetched (non-law spans between law entries, e.g.
year-end announcement annexes, remain out of scope exactly as the
section filter always intended).
"""

from __future__ import annotations

from adapters.base import (
    FileOut,
    RequestSpec,
    Response,
    TaskResult,
    TaskSeed,
    TaskView,
)
from adapters.jpn.sources.kanpo import SITE, USER_AGENT
from adapters.jpn.sources.kanpo.enumerate import (
    _HEADERS,
    _decode,
    _doc_seed,
    _Entry,
    _is_known_not_found,
    _section_filter,
    _walk_entries,
    map_doc_type,
)
from core.document import DocumentRecord, compute_doc_id

__all__ = ["KanpoPageHandler", "KanpoSpanIssueHandler"]

_LAW_PREDICATE = _section_filter("law")


def _law_scope(h2: str) -> bool:
    assert _LAW_PREDICATE is not None  # "law" scope always yields a predicate
    return bool(_LAW_PREDICATE(h2))


class KanpoSpanIssueHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        date8 = str(task.params["date"]).replace("-", "")
        issue = str(task.params["issue"])
        prefix = "" if task.params.get("ns") == "root" else "/old"
        return RequestSpec(
            url=f"{SITE}{prefix}/{date8}/{issue}/{issue}0000f.html",
            headers=dict(_HEADERS),
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        issue = str(task.params["issue"])
        date = str(task.params["date"])
        fetched = {
            int(p)
            for p in str(task.params.get("fetched", "")).split(",")
            if p.strip()
        }

        html = _decode(response, f"span-issue {issue}")
        start = html.find("contentsBox")
        body = html[start:] if start >= 0 else html
        entries = _walk_entries(body)
        if not entries:
            raise ValueError(
                f"span-issue {issue}: TOC carries no linked entries — "
                "unexpected for an issue present in the ledger"
            )

        # Issue label parts derived from the code (h/g/t … + ordinal) so
        # entry-harvest seeds carry the same issue_no/issue_type strings
        # the original enumeration produced from the TOC label.
        issue_type = {"h": "本紙", "g": "号外", "t": "特別号外", "c": "政府調達"}.get(
            issue[8], ""
        )
        issue_no = str(int(issue[9:14]))

        # Blocks of same-page starts, page order (TOC order kept within a
        # page). Ordinals count over ALL linked entries in TOC order — the
        # same semantics as the original kanpo_issue/kanpo_day enumeration,
        # so re-seeded kanpo_doc tasks collide with existing ones by task
        # identity and dedupe for free.
        blocks: list[list[tuple[int, _Entry]]] = []  # (ordinal, entry)
        for ordinal, entry in sorted(
            enumerate(entries, start=1), key=lambda pair: int(pair[1].base[-4:])
        ):
            page = int(entry.base[-4:])
            if blocks and int(blocks[-1][-1][1].base[-4:]) == page:
                blocks[-1].append((ordinal, entry))
            else:
                blocks.append([(ordinal, entry)])

        seeds: list[TaskSeed] = []
        for idx, block in enumerate(blocks):
            start_page = int(block[0][1].base[-4:])
            owner = block[-1][1]  # descriptive owner: last entry on the page
            law_owned = any(_law_scope(e.h2) for _, e in block)
            next_start = (
                int(blocks[idx + 1][0][1].base[-4:]) if idx + 1 < len(blocks) else None
            )
            chain = next_start is None  # last block of the issue: probe the tail
            if law_owned:
                # Entry harvest (vocabulary-repair channel, 2026-10-18):
                # seed kanpo_doc for EVERY law-scoped entry of the block —
                # already-collected entries dedupe by task identity, entries
                # of sections added to the vocabulary later (e.g. 復興庁令)
                # get fetched for the first time.
                for ordinal, entry in block:
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
                pages: list[int] = []
                if next_start is not None:
                    pages = [
                        p for p in range(start_page + 1, next_start) if p not in fetched
                    ]
                else:
                    # Unknown issue end: probe the first page past the last
                    # start; each fetched page chains the next until 404.
                    pages = [start_page + 1] if start_page + 1 not in fetched else []
                for page in pages:
                    seeds.append(
                        TaskSeed(
                            type="kanpo_page",
                            params={
                                "date": date,
                                "ns": str(task.params.get("ns", "old")),
                                "issue": issue,
                                "page": page,
                                "span_from": start_page,
                                "owner_title": owner.title,
                                "owner_type": map_doc_type(owner.h2),
                                "native_type": owner.h2,
                                "chain": "1" if chain else "0",
                            },
                        )
                    )
        if not seeds:
            return TaskResult(
                expected_empty=(
                    f"span-issue {issue}: no law-scoped entries and no unfetched "
                    "law-owned span pages"
                )
            )
        return TaskResult(next_tasks=seeds)


class KanpoPageHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        date8 = str(task.params["date"]).replace("-", "")
        issue = str(task.params["issue"])
        page = int(task.params["page"])
        prefix = "" if task.params.get("ns") == "root" else "/old"
        return RequestSpec(
            url=f"{SITE}{prefix}/{date8}/{issue}/pdf/{issue}{page:04d}.pdf",
            headers={"User-Agent": USER_AGENT},
            accept_not_found=True,  # the tail probe's 404 = issue end
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = task.params
        issue = str(params["issue"])
        page = int(params["page"])
        date = str(params["date"])

        if response.status_code in (404, 410):
            if not _is_known_not_found(response):
                raise ValueError(
                    f"page {issue}p{page}: HTTP {response.status_code} with an "
                    "unexpected body — not the known no-page shape"
                )
            return TaskResult(
                expected_empty=(
                    f"issue {issue} has no page {page} (tail probe ended at the "
                    "portal's fixed 404)"
                )
            )

        if not response.content.startswith(b"%PDF"):
            head = response.content[:80]
            raise ValueError(
                f"page {issue}p{page}: response is not a PDF "
                f"(status {response.status_code}, head {head!r})"
            )

        date8 = date.replace("-", "")
        source_url = f"{SITE}/old/{date8}/{issue}/{issue}{page:04d}f.html"
        meta: dict[str, str] = {
            "continuation": "1",
            "issue_code": issue,
            "page": str(page),
            "span_from": str(params["span_from"]),
            "native_type": str(params.get("native_type", "")),
            "files": f"{issue}{page:04d}.pdf",
        }
        record = DocumentRecord(
            title=f"（続き{page:04d}）{params['owner_title']}",
            source_url=source_url,
            publication_date=date,
            issuing_authority=None,
            doc_type=str(params.get("owner_type")) or None,
            language="jpn",
            raw_metadata=meta,
        )
        doc_id = compute_doc_id("JPN", source_url, date)
        path = (
            f"01_raw/kanpo/{date8[:4]}/D{date8}/{issue}/"
            f"{issue}{page:04d}/{issue}{page:04d}.pdf"
        )

        next_tasks: list[TaskSeed] = []
        if str(params.get("chain", "0")) == "1":
            nxt = dict(params)
            nxt["page"] = page + 1
            next_tasks.append(TaskSeed(type="kanpo_page", params=nxt))

        return TaskResult(
            documents=[record],
            files=[FileOut(path=path, content=response.content, doc_id=doc_id)],
            next_tasks=next_tasks,
        )
