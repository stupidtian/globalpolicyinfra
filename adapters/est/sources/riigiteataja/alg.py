"""Task type ``rt_alglist``: one page of the as-published layer walk.

``POST /public-api/api/v1/otsing/alg-tekst`` — the as-published search
(the algtekstide otsing backend, probed 2026-11-05, samples in the task
folder). With an empty query it answers the WHOLE adoption-time layer:
``koik = 162,166`` rows, one per act adoption original (amendment acts
are acts too and carry their own original; consolidated versions are
NOT in this corpus — they belong to the rt_sweep inventory). Page size
is fixed at 30 rows server-side (limit/size params silently ignored);
pagination is ``general.searchAfter`` = plain row offset (0, 30, 60, …),
sorted newest first.

Rows carry the act inline: ``id`` (globaalID of the original — directly
blob-xml addressable), ``reportIssuer`` / ``reportType`` (issuer and
native type — the same words the sweep rows use), ``title``,
``groupId`` (often null on modern rows), ``actDate`` (adoption date;
the publication date still comes from the blob's metaandmed), and
``localGovernment``. Court decisions appear in keyword searches; the
default walk sample showed none (0 of 1,620), and court issuers are
dropped structurally anyway (``kohus`` substring — brief boundary: no
case law).

Each kept row yields one ``rt_act`` seed (the SAME handler as the sweep
channel: the original's XML parses identically, meta carries
``channel=algtekst``, and unamended acts resolve to the same document id
in both channels — the engine dedupes). The walk continues via a
same-type seed at ``offset + 30`` until an empty page (the corpus tail
— a clean expected empty) or ``offset >= koik``.

Offset pagination drifts while the walk runs (new publications prepend
to the newest-first order); the document identity layer absorbs it —
a rerun or a ``refresh=`` walk under a new identity closes any gap.
"""

from __future__ import annotations

from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.est.sources.riigiteataja import (
    PUBLIC_API_BASE,
    REQUEST_HEADERS,
    is_court_issuer,
    is_municipal_issuer,
)

__all__ = ["AlgListHandler"]

_SEARCH_URL = f"{PUBLIC_API_BASE}/otsing/alg-tekst"

#: Server-fixed page size of the search walk (probed 2026-11-05: limit /
#: size / limiit params, top-level and inside general, all ignored).
PAGE_SIZE = 30


def _search_body(offset: int) -> dict[str, Any]:
    """The exact query the site's own algtekstide otsing sends for an
    unfiltered listing (shape captured 2026-11-05 from the SPA)."""
    return {
        "general": {
            "searchInText": False,
            "searchInTitle": True,
            "searchText": "",
            "searchText2": "",
            "logicalOperator": "AND",
            "morphSearch": False,
            "searchAfter": offset,
        },
        "precise": {
            "reportIssuerList": ["all"],
            "reportTypeList": ["all"],
            "localGovernmentReportIssuerList": ["all"],
            "reportNumber": None,
            "reportNumberStart": None,
            "reportNumberEnd": None,
            "rtArticleNumber": None,
            "rtIssueNumber": None,
            "rtOsa": None,
        },
    }


def _act_seed(row: dict[str, Any], scope: str) -> TaskSeed:
    return TaskSeed(
        type="rt_act",
        params={
            "id": str(row["id"]),
            "group": str(row.get("groupId") or ""),
            "liik": str(row.get("reportType") or ""),
            "valjaandja": str(row.get("reportIssuer") or ""),
            "title": str(row.get("title") or ""),
            "scope_slice": scope,
            "channel": "algtekst",
        },
    )


class AlgListHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        offset = int(str(task.params["offset"]))
        return RequestSpec(
            url=_SEARCH_URL,
            method="POST",
            json_body=_search_body(offset),
            headers=REQUEST_HEADERS,
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        offset = int(str(task.params["offset"]))
        scope = str(task.params.get("scope", "state"))
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(
                f"rt_alglist offset={offset}: body is not JSON: {exc}"
            ) from exc
        if "results" not in payload or "koik" not in payload:
            raise ValueError(
                f"rt_alglist offset={offset}: unexpected response shape "
                f"(keys={sorted(payload)!r}) — the search endpoint may have moved"
            )
        rows = payload["results"] or []
        koik = int(payload.get("koik") or 0)

        seeds: list[TaskSeed] = []
        kept = 0
        municipal = 0
        court = 0
        for row in rows:
            if not row.get("id"):
                raise ValueError(
                    f"rt_alglist offset={offset}: row without id "
                    f"({ {k: row.get(k) for k in ('id', 'title', 'reportIssuer')} }) — "
                    "search row shape may have changed"
                )
            issuer = str(row.get("reportIssuer") or "")
            if is_court_issuer(issuer):
                court += 1
                continue
            if scope == "state" and (
                is_municipal_issuer(issuer) or bool(row.get("localGovernment"))
            ):
                municipal += 1
                continue
            kept += 1
            seeds.append(_act_seed(row, scope))

        results = TaskResult()
        if kept:
            results.next_tasks.extend(seeds)
        elif rows:
            results.expected_empty = (
                f"rt_alglist offset={offset}: all {len(rows)} rows fall outside the "
                f"channel (courts: {court}, municipal under scope={scope}: {municipal})"
            )
        else:
            results.expected_empty = (
                f"rt_alglist offset={offset}: empty page — corpus tail fully "
                "consumed"
            )

        # Chain while the declared window allows AND the corpus is not
        # exhausted (koik is the server's own total). offsets_end is
        # EXCLUSIVE in row terms: offsets=0:60 walks the pages at offsets
        # 0 and 30 — rows 0..59.
        offsets_end = task.params.get("offsets_end")
        within_window = offsets_end is None or (offset + PAGE_SIZE) < int(str(offsets_end))
        exhausted = koik and offset + PAGE_SIZE >= koik
        if rows and within_window and not exhausted:
            next_params = dict(task.params)
            next_params["offset"] = str(offset + PAGE_SIZE)
            results.next_tasks.append(TaskSeed(type="rt_alglist", params=next_params))
        return results
