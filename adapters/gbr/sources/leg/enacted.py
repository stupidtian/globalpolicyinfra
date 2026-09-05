"""Task type ``leg_enacted``: one item's original as-enacted/as-made CLML.

The whole ``data.xml`` body is the document artifact; its metadata block
carries the bibliographic fields. Probed field locations (2026-09-03,
real samples): ``ukm:EnactmentDate/@Date`` is the machine enactment date
of an Act; an instrument's made date is ``DateSigned/@Date`` in the
signature block, while the introduction block carries made / laid /
coming-into-force as human ``DateText`` — the date triple the time-series
research consumes. Static print-PDF links are recorded in meta only
(robots.txt disallows ``*/data.pdf``).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.gbr.sources.leg import (
    NOT_FOUND_MARKERS,
    SITE,
    USER_AGENT,
    VERSION_WORDS,
    _xml,
    canonical_url,
    doc_type_of,
    item_key,
)
from core.document import DocumentRecord, compute_doc_id

__all__ = ["LegEnactedHandler"]


def _attr(element: ET.Element | None, name: str) -> str:
    return (element.get(name) or "") if element is not None else ""


def _metadata(root: ET.Element) -> dict[str, str]:
    """Flatten the probed metadata fields (local names, empty dropped)."""
    fields: dict[str, str] = {}
    for key, element in {
        "identifier": _xml.find_deep(root, "identifier"),
        "title": _xml.find_deep(root, "title"),
        "subject": _xml.find_deep(root, "subject"),
        "publisher": _xml.find_deep(root, "publisher"),
        "modified": _xml.find_deep(root, "modified"),
        "year": _xml.find_deep(root, "Year"),
        "number": _xml.find_deep(root, "Number"),
        "isbn": _xml.find_deep(root, "ISBN"),
        "main_type": _xml.find_deep(root, "DocumentMainType"),
        "document_status": _xml.find_deep(root, "DocumentStatus"),
        "enactment_date": _xml.find_deep(root, "EnactmentDate"),
        "signed_date": _xml.find_deep(root, "DateSigned"),
    }.items():
        value = _attr(element, "Date") or _attr(element, "Value") or _xml.texts(element)
        if value:
            fields[key] = value
    for key, name in {
        "made_date": "MadeDate",
        "laid_date": "LaidDate",
        "coming_into_force": "ComingIntoForce",
    }.items():
        block = _xml.find_deep(root, name)
        text = _xml.texts(_xml.first_child(block, "DateText")) if block is not None else ""
        if text:
            fields[key] = text
    alt = _xml.find_deep(root, "AlternativeNumber")
    if alt is not None and alt.get("Value"):
        fields["alternative_number"] = f"{alt.get('Category', '')} {alt.get('Value')}".strip()
    for link in root.iter():
        if _xml.localname(link.tag) == "link" and link.get("type") == "application/pdf":
            fields["pdf_url"] = link.get("href", "")
            break
    provisions = root.get("NumberOfProvisions", "")
    if provisions:
        fields["number_of_provisions"] = provisions
    return fields


class LegEnactedHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        item_type = str(task.params["type"])
        year = str(task.params["year"])
        number = str(task.params["number"])
        return RequestSpec(
            url=canonical_url(item_type, year, number),
            headers={"User-Agent": USER_AGENT},
            accept_not_found=True,
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        item_type = str(task.params["type"])
        year = str(task.params["year"])
        number = str(task.params["number"])
        key = item_key(item_type, year, number)

        if response.status_code in (404, 410):
            body = response.content.decode("utf-8", "replace")
            if any(marker in body for marker in NOT_FOUND_MARKERS):
                return TaskResult(
                    upsert_rows={"items": [{"item_key": key, "xml_available": 0}]},
                    expected_empty="no XML version for this item (PDF-only or unpublished)",
                )
            raise ValueError(f"unexpected HTTP {response.status_code} body for {key}")

        if response.status_code != 200:
            raise ValueError(f"enacted fetch returned HTTP {response.status_code}")

        root = ET.fromstring(response.content)
        meta = _metadata(root)
        title = meta.get("title") or str(task.params.get("title") or key)
        publication = (
            meta.get("enactment_date")
            or meta.get("signed_date")
            or str(task.params.get("creation_date") or "")
            or None
        )
        laid = _xml.iso_date(meta.get("laid_date", "")) or meta.get("laid_date") or None
        in_force = (
            _xml.iso_date(meta.get("coming_into_force", ""))
            or meta.get("coming_into_force")
            or None
        )
        source_url = canonical_url(item_type, year, number)
        version = VERSION_WORDS[item_type]
        rel_path = f"01_raw/leg/{item_type}/{year}/{number}/{version}/data.xml"

        record = DocumentRecord(
            title=title,
            source_url=source_url,
            publication_date=publication,
            issuing_authority=meta.get("publisher"),
            doc_type=doc_type_of(item_type),
            entity_ref=f"items:{key}",
            language="eng",
            raw_metadata=meta,
        )
        row: dict[str, Any] = {
            "item_key": key,
            "uri": meta.get("identifier") or f"{SITE}/id/{key}",
            "title": title,
            "native_type": meta.get("main_type") or item_type,
            "year": year,
            "number": number,
            "enactment_date": publication,
            "laid_date": laid,
            "in_force_date": in_force,
            "xml_available": 1,
            "raw_path": rel_path,
        }
        if meta.get("number_of_provisions", "").isdigit():
            row["n_provisions"] = int(meta["number_of_provisions"])

        doc_id = compute_doc_id("GBR", source_url, publication)
        return TaskResult(
            documents=[record],
            files=[FileOut(path=rel_path, content=response.content, doc_id=doc_id)],
            upsert_rows={"items": [row]},
        )
