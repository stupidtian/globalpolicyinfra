"""Task type ``fr_list_page``: one page of a Federal Register date window.

GET /api/v1/documents.json with publication_date bounds, 1,000 per page —
every FR document published in the window. Parse yields one partial
``fr_documents`` row per item (the listing already carries most fields),
the next-page task while pages remain, and — when ``deep`` says so — an
``fr_detail`` seed per document.

FR documents are immutable once published (mistakes become separate
Correction documents), so unlike bills there is no reopen signal: an
already-fetched detail is simply never re-enqueued.
"""

from __future__ import annotations

from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.usa.schema import fr_folder, president_name

__all__ = ["API_BASE", "LISTING_FIELDS", "PAGE_SIZE", "FrListPageHandler"]

API_BASE = "https://www.federalregister.gov/api/v1"
PAGE_SIZE = 1000

#: Ask for the rich field set so listing rows are near-complete on their own
#: (the detail endpoint adds subtype/dates/corrections/topics and friends).
LISTING_FIELDS: tuple[str, ...] = (
    "document_number",
    "title",
    "type",
    "publication_date",
    "abstract",
    "action",
    "citation",
    "volume",
    "start_page",
    "end_page",
    "html_url",
    "raw_text_url",
    "pdf_url",
    "agencies",
    "president",
    "executive_order_number",
    "proclamation_number",
    "docket_ids",
    "regulation_id_numbers",
    "cfr_references",
)


def _first_rin(rids: list[Any]) -> str | None:
    for rid in rids:
        if rid:
            return str(rid)
    return None


class FrListPageHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        params: dict[str, Any] = {
            "conditions[publication_date][gte]": task.params["from"],
            "conditions[publication_date][lte]": task.params["to"],
            "per_page": PAGE_SIZE,
            "page": int(task.params.get("page", 1)),
            "fields[]": list(LISTING_FIELDS),
        }
        return RequestSpec(url=f"{API_BASE}/documents.json", params=params)

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        payload = response.json()
        items = payload.get("results", [])
        params = task.params

        rows = []
        next_tasks: list[TaskSeed] = []
        deep = params.get("deep", "none")
        cases = params.get("cases") or []
        for item in items:
            document_number = str(item.get("document_number") or "")
            if not document_number:
                continue
            publication_date = item.get("publication_date")
            rids = [str(r) for r in (item.get("regulation_id_numbers") or []) if r]
            rows.append(
                {
                    "document_number": document_number,
                    "publication_date": publication_date,
                    "title": item.get("title") or document_number,
                    "type": item.get("type"),
                    "abstract": item.get("abstract"),
                    "action": item.get("action"),
                    "citation": item.get("citation"),
                    "volume": item.get("volume"),
                    "start_page": item.get("start_page"),
                    "end_page": item.get("end_page"),
                    "agencies": item.get("agencies") or [],
                    "president": president_name(item.get("president")),
                    "executive_order_number": item.get("executive_order_number"),
                    "proclamation_number": item.get("proclamation_number"),
                    "docket_ids": item.get("docket_ids") or [],
                    "rins": rids,
                    "rin": _first_rin(rids),
                    "cfr_references": item.get("cfr_references") or [],
                    "html_url": item.get("html_url"),
                    "raw_text_url": item.get("raw_text_url"),
                    "pdf_url": item.get("pdf_url"),
                    "folder": fr_folder(str(publication_date), document_number),
                }
            )
            if deep == "all" or document_number in cases:
                next_tasks.append(
                    TaskSeed(
                        type="fr_detail",
                        params={
                            "document_number": document_number,
                            "formats": params.get("formats", "txt,xml"),
                        },
                    )
                )

        # chain the next page until the API runs out or max_pages says stop
        page = int(params.get("page", 1))
        total_pages = int(payload.get("total_pages") or 0)
        max_pages = params.get("max_pages")
        more_pages = page < total_pages
        if more_pages and (max_pages is None or page < int(max_pages)):
            chain_params = dict(params)
            chain_params["page"] = page + 1
            next_tasks.append(TaskSeed(type="fr_list_page", params=chain_params))

        result = TaskResult(upsert_rows={"fr_documents": rows}, next_tasks=next_tasks)
        # FR is date-partitioned: any fully swept window justifies advancing
        # the cursor to its end (unlike congress-enumerated bills). A later
        # backfill into an earlier window may move it back — harmless, the
        # next sync re-sweeps idempotently.
        if not more_pages:
            result.cursor_updates = {"fr_last_pub_date": str(params["to"])}
        return result
