"""Task type ``rt_timeline``: one law lineage from the native timeline.

GET ``/api/document/{numeric id}/timeline`` — the source's own version
lineage for the two timeline-capable types (documentTypeId 10 acts /
30 consolidated orders; the SPA gates it to exactly these, probed
2026-09-15). One response carries every version of the law: main act,
amending acts (LOV Æ) and consolidated re-promulgations (LBK), each with
signature date, year/number, canonical href and the three state markers
``isMainLaw`` / ``isCurrentDocument`` / ``isHistoric``. Probed shapes:

- ``isMainLaw`` may be absent from the whole list (the main act can
  predate digitisation; Retsplejeloven's 345-item timeline starts at the
  1986 consolidation with an explanatory note) — the anchor is then the
  earliest item by (signature date, href), deterministic across every
  member's query so all versions converge on one ``laws`` row;
- ``isCurrentDocument`` marks the currently valid version (none if the
  law is fully repealed) — recorded as the laws row's current pointer.

The raw timeline is stored verbatim as ``timeline.json`` under the law's
folder; ``rt_doc`` is chained with the law key so the document row gets
its ``entity_ref`` at registration time.
"""

from __future__ import annotations

from typing import Any

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.dnk.sources.retsinformation import API_BASE, parse_dk_date

__all__ = ["RtTimelineHandler"]


def _flatten(href: str) -> str:
    """``/eli/lta/1986/567`` -> ``lta-1986-567`` (law key / folder name)."""
    path = href.strip("/")
    path = path.removeprefix("eli/")
    return path.replace("/", "-")


class RtTimelineHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=f"{API_BASE}/api/document/{task.params['doc_num']}/timeline")

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        eli = str(task.params["eli"])
        items = response.json()
        if not isinstance(items, list) or not items:
            raise ValueError(f"timeline {eli}: unexpected payload (not a non-empty list)")

        def sort_key(item: dict[str, Any]) -> tuple[str, str]:
            sig = parse_dk_date(item.get("signatureDate")) or "9999-12-31"
            return sig, str(item.get("href") or "")

        main = [it for it in items if it.get("isMainLaw")]
        anchor = main[0] if main else min(items, key=sort_key)
        current = next((it for it in items if it.get("isCurrentDocument")), None)

        anchor_href = str(anchor.get("href") or "").strip()
        if not anchor_href:
            raise ValueError(f"timeline {eli}: anchor item carries no href")
        law_key = _flatten(anchor_href)
        lineage_path = f"01_raw/retsinformation/laws/{law_key}/timeline.json"

        row = {
            "law_key": law_key,
            "law_name": (anchor.get("title") or "").strip() or law_key,
            "ressort": (anchor.get("ressort") or "").strip() or None,
            "current_href": (current or {}).get("href"),
            "current_signature_date": parse_dk_date((current or {}).get("signatureDate")),
            "lineage_path": lineage_path,
        }
        next_tasks = [
            TaskSeed(
                type="rt_doc",
                params={
                    "eli": eli,
                    "pub": str(task.params.get("pub", "")),
                    "code": str(task.params.get("code", "")),
                    "law_key": law_key,
                },
            )
        ]
        return TaskResult(
            upsert_rows={"laws": [row]},
            files=[FileOut(path=lineage_path, content=response.content)],
            next_tasks=next_tasks,
        )
