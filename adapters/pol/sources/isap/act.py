"""Task type ``isap_act``: one act, its references, its texts.

``GET /eli/acts/DU/{y}/{p}`` — the full act-info response (probed
2026-09-20 on DU/2024/1, DU/2025/803 and the 1995 scan-era DU/1995/1;
samples in the task folder). One request yields the entity row, the raw
reference graph and the text inventory:

- the response is archived verbatim as ``act.json`` (the lossless copy of
  the nine-category reference graph — amendment/repeal/consolidation/
  constitutional-tribunal edges, cross-DU/MP — and of the ``texts[]``
  file inventory; type codes T/O/U/H/I, O=original PDF, I=its scan twin,
  U=consolidated variant, H=HTML, T unseen in probes and left uncalled);
- the ``acts`` row is upserted keyed on the ELI (``DU/{year}/{pos}`` —
  stable across the pre-2012 ``nr/poz`` addressing whose ``WDU`` address
  packs the issue number in);
- ``references["Inf. o tekście jednolitym"]`` lists the act's consolidation
  announcements — each spawns an isap_act of its own (they are full gazette
  entries; identity-level dedup makes the year-axis and reference-axis
  spawns converge, and cycles are structurally impossible to loop on:
  re-enqueueing a pending/done task is a no-op);
- an announcement carrying ``references["Tekst jednolity dla aktu"]`` is
  recognised as a consolidation: its document points at the BASE act
  (``entity_ref``), giving the version-series axis "one act, many states";
- text policy: textHTML → ``isap_text`` primary (HTML) + ``isap_pdf``
  typeset sibling; HTML-only-missing (consolidation announcements) →
  ``isap_pdf`` primary; neither flag → act row only, no document (the
  source has no body carrier at all).
"""

from __future__ import annotations

from typing import Any

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.pol.sources.isap import (
    ELI_BASE,
    act_folder,
    canonical_source_url,
)
from core.document import DocumentRecord, compute_doc_id

__all__ = ["IsapActHandler", "map_doc_type"]

#: Native type word (``type``) -> cross-country doc_type. The native word is
#: always kept in meta (section 5.3 labelling rules); the full ~45-word
#: vocabulary (/eli/types) falls through to OTHER here; add-only.
_NATIVE_TO_TYPE: dict[str, str] = {
    "Ustawa": "STATUTE",
    "Rozporządzenie z mocą ustawy": "STATUTE",
    "Rozporządzenie": "SECONDARY_LEGISLATION",
    "Dekret": "DECREE",
}

#: Reference categories this parse drives on (the rest ride in act.json).
_CONSOLIDATES_KEY = "Tekst jednolity dla aktu"
_CONSOLIDATIONS_KEY = "Inf. o tekście jednolitym"


def map_doc_type(native_type: str) -> str:
    return _NATIVE_TO_TYPE.get(native_type.strip(), "OTHER")


def _ref_ids(payload: dict[str, Any], key: str) -> list[str]:
    """ELI ids of one reference category: ``[{id: DU/2025/803}, …]``."""
    return [
        str(entry.get("id") or "")
        for entry in (payload.get("references") or {}).get(key) or []
        if isinstance(entry, dict)
    ]


def _split_eli(eli: str) -> tuple[str, str, str] | None:
    """``DU/2025/803`` -> ``("DU", "2025", "803")``; None when malformed."""
    parts = eli.split("/")
    if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
        return parts[0], parts[1], parts[2]
    return None


class IsapActHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        publisher = str(task.params["publisher"])
        return RequestSpec(
            url=f"{ELI_BASE}/acts/{publisher}/{task.params['year']}/{task.params['pos']}"
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        publisher = str(task.params["publisher"])
        year = str(task.params["year"])
        pos = str(task.params["pos"])
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(f"isap_act {publisher}/{year}/{pos}: body is not JSON: {exc}") from exc
        if not isinstance(payload, dict) or not payload.get("ELI"):
            raise ValueError(
                f"isap_act {publisher}/{year}/{pos}: unexpected response shape "
                f"(keys={sorted(payload)!r}) — the act detail may have moved"
            )
        answered = (
            str(payload.get("publisher") or ""),
            str(payload.get("year") or ""),
            str(payload.get("pos") or ""),
        )
        if answered != (publisher, year, str(int(pos))):
            raise ValueError(
                f"isap_act {publisher}/{year}/{pos}: response describes "
                f"{answered} instead — seed/detail identity drift"
            )

        eli = str(payload["ELI"])
        # One-off acts repealed before promulgation (status "akt jednorazowy",
        # probed: DU/2024/1723) carry no promulgation date anywhere in the
        # source — the document then registers at the 00000000 doc_id date.
        promulgation = str(payload.get("promulgation") or "")[:10] or None

        # -- consolidation relations ------------------------------------------
        consolidates = [r for r in _ref_ids(payload, _CONSOLIDATES_KEY) if r]
        if len(set(consolidates)) > 1:
            raise ValueError(
                f"isap_act {eli}: consolidation announcement points at "
                f"{consolidates!r} — expected exactly one base act"
            )
        consolidation_of = consolidates[0] if consolidates else ""
        doc_kind = "consolidation" if consolidation_of else "enacted"
        entity_ref = f"acts:{consolidation_of or eli}"

        next_tasks: list[TaskSeed] = []
        for ref in _ref_ids(payload, _CONSOLIDATIONS_KEY):
            if ref == eli:
                continue
            split = _split_eli(ref)
            if split is None:
                raise ValueError(f"isap_act {eli}: malformed consolidation ref {ref!r}")
            ref_publisher, ref_year, ref_pos = split
            next_tasks.append(
                TaskSeed(
                    type="isap_act",
                    params={
                        "publisher": ref_publisher,
                        "year": ref_year,
                        "pos": ref_pos,
                    },
                )
            )

        # -- entity row ---------------------------------------------------------
        folder = act_folder(publisher, year, pos)
        released_by = [str(v) for v in payload.get("releasedBy") or []]
        keywords = [str(v) for v in payload.get("keywords") or []]
        text_types = sorted({
            str(t.get("type") or "")
            for t in payload.get("texts") or []
            if isinstance(t, dict)
        } - {""})
        row: dict[str, Any] = {
            "eli": eli,
            "address": str(payload.get("address") or ""),
            "publisher": publisher,
            "year": int(year),
            "pos": int(pos),
            "volume": int(payload.get("volume") or 0),
            "title": str(payload.get("title") or ""),
            "native_type": str(payload.get("type") or ""),
            "status": str(payload.get("status") or ""),
            "in_force": str(payload.get("inForce") or ""),
            "promulgation": promulgation,
            "announcement_date": str(payload.get("announcementDate") or "")[:10] or None,
            "entry_into_force": str(payload.get("entryIntoForce") or "")[:10] or None,
            "change_date": str(payload.get("changeDate") or "") or None,
            "released_by": released_by,
            "keywords": keywords,
            "raw_path": f"{folder}/act.json",
        }

        result = TaskResult(upsert_rows={"acts": [row]})
        result.files = [FileOut(path=f"{folder}/act.json", content=response.content)]
        result.next_tasks = next_tasks

        # -- text policy ---------------------------------------------------------
        has_html = bool(payload.get("textHTML"))
        has_pdf = bool(payload.get("textPDF"))
        if not (has_html or has_pdf):
            # No body carrier anywhere (act row + archive only): real, but
            # must be loud — an enacted act without any text would be news.
            result.expected_empty = (
                f"isap_act {eli}: textHTML and textPDF both false — no body "
                "carrier in the source (act row registered without a document)"
            )
            return result

        source_url = canonical_source_url(publisher, int(year), int(pos))
        doc_id = compute_doc_id("POL", source_url, promulgation)
        meta: dict[str, str] = {
            "eli": eli,
            "address": str(payload.get("address") or ""),
            "pos": pos,
            "volume": str(payload.get("volume") or ""),
            "native_type": str(payload.get("type") or ""),
            "native_status": str(payload.get("status") or ""),
            "in_force": str(payload.get("inForce") or ""),
            "announcement_date": str(payload.get("announcementDate") or "")[:10],
            "entry_into_force": str(payload.get("entryIntoForce") or "")[:10],
            "change_date": str(payload.get("changeDate") or ""),
            "doc_kind": doc_kind,
            "display_address": str(payload.get("displayAddress") or ""),
            "api_url": source_url,
        }
        if released_by:
            meta["released_by"] = ",".join(released_by)
        if keywords:
            meta["keywords"] = ",".join(keywords)
        if text_types:
            meta["text_types"] = ",".join(text_types)
        if consolidation_of:
            meta["consolidation_of"] = consolidation_of

        siblings: list[str] = ["act.json"]
        if has_html:
            # HTML-primary: the act task registers the document (it holds
            # the metadata), the text task fills the primary file, the pdf
            # task rides in as the typeset sibling.
            siblings.append("text.pdf")
            meta["files"] = ",".join(siblings)
            next_tasks.append(
                TaskSeed(
                    type="isap_text",
                    params={
                        "publisher": publisher,
                        "year": year,
                        "pos": pos,
                        "doc_id": doc_id,
                    },
                )
            )
            next_tasks.append(
                TaskSeed(
                    type="isap_pdf",
                    params={"publisher": publisher, "year": year, "pos": pos},
                )
            )
            title = str(payload.get("title") or "")
            if not title:
                raise ValueError(f"isap_act {eli}: no title — shape change")
            result.documents = [
                DocumentRecord(
                    title=title,
                    source_url=source_url,
                    publication_date=promulgation,
                    issuing_authority=released_by[0] if released_by else None,
                    doc_type=map_doc_type(str(payload.get("type") or "")),
                    entity_ref=entity_ref,
                    language="pol",
                    raw_metadata=meta,
                )
            ]
        else:
            # PDF-primary (no HTML anywhere — the consolidation
            # announcements): the record travels to the pdf task in params
            # and THAT task registers the document it downloads. produced_by
            # then truthfully separates the two carriers, which keeps the
            # clean scope (isap_act-produced docs = HTML texts only) exact.
            meta["files"] = ",".join(siblings)
            next_tasks.append(
                TaskSeed(
                    type="isap_pdf",
                    params={
                        "publisher": publisher,
                        "year": year,
                        "pos": pos,
                        "doc_id": doc_id,
                        "record": {
                            "title": str(payload.get("title") or ""),
                            "source_url": source_url,
                            "publication_date": promulgation,
                            "issuing_authority": released_by[0] if released_by else None,
                            "doc_type": map_doc_type(str(payload.get("type") or "")),
                            "entity_ref": entity_ref,
                            "raw_metadata": meta,
                        },
                    },
                )
            )
        return result
