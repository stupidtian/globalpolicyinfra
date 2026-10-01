"""Task type ``bek_item``: one Staatsblad publication, one request, one document.

GET the publication's xml-manifestation URL (taken from the SRU record —
never constructed: issue numbers are not contiguous) and store the
response bytes verbatim as ``doc.xml``. All research fields travel in the
task params from the ``bek_day`` record — the body is only shape-checked,
because several XML body generations coexist (see ``KNOWN_ROOTS``):
modern op-xsd, two legacy SDU-DTD generations, verbeterblad bodies, and
bare metadata stubs where the source holds no full text.

Every root in ``KNOWN_ROOTS`` is accepted; anything else is an unknown
shape and fails loud.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.nld.sources.bekendmakingen import (
    canonical_doc_url,
    map_doc_type,
    raw_path,
)
from core.document import DocumentRecord, compute_doc_id

__all__ = ["KNOWN_ROOTS", "BekItemHandler"]

#: XML body roots across the schema generations. Probed shapes: modern
#: ``officiele-publicatie`` (op-xsd-2014, stb-2024-1); SDU-DTD legacy
#: ``staatsbl`` (staatsbl-11.dtd, stb-1995-78) and ``staatsblad``
#: (staatsblad-1_61.dtd, stb-2010-138); ``vblad`` for verbeterbladen
#: (corrected-sheet reprints, stb-2000-30-v1 — same staatsbl-11 DTD
#: family); ``metadata`` when the source serves no full text and the xml
#: manifestation is a bare metadata stub (stb-2009-601-b1, ~305 B — the
#: ledger row still carries the full SRU metadata, the stub is stored
#: verbatim as the canonical file). All five shapes verified live
#: 2026-09-30 during the 2000-2025 backfill.
KNOWN_ROOTS = ("officiele-publicatie", "staatsbl", "staatsblad", "vblad", "metadata")


class BekItemHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=str(task.params["xml_url"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params: dict[str, Any] = task.params
        identifier = str(params["id"])
        issued = str(params["issued"])
        title = str(params.get("title", "")) or identifier
        if not issued:
            raise ValueError(f"bek_item {identifier}: no issued date in task params")

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise ValueError(
                f"bek_item {identifier}: body is not XML: {exc}"
            ) from exc
        root_name = root.tag.rsplit("}", 1)[-1]
        if root_name not in KNOWN_ROOTS:
            raise ValueError(
                f"bek_item {identifier}: unknown body root {root.tag!r} "
                f"(expected one of {KNOWN_ROOTS}) — shape change"
            )

        meta = {
            "identifier": identifier,
            "native_type": str(params.get("native_type", "")),
            "creator": str(params.get("creator", "")),
            "publisher": str(params.get("publisher", "")),
            "datum_ondertekening": str(params.get("datum_ondertekening", "")),
            "behandeld_dossier": str(params.get("behandeld_dossier", "")),
            "jaargang": str(params.get("jaargang", "")),
            "publicatienaam": str(params.get("publicatienaam", "")),
            "publicatienummer": str(params.get("publicatienummer", "")),
            "content_area": str(params.get("content_area", "")),
            "xml_url": str(params["xml_url"]),
            "preferred_url": str(params.get("preferred_url", "")),
            "pdf_url": str(params.get("pdf_url", "")),
            "html_url": str(params.get("html_url", "")),
        }
        meta = {k: v for k, v in meta.items() if v}
        meta["files"] = "doc.xml"

        source_url = meta.get(
            "preferred_url", canonical_doc_url(identifier)
        )
        path = raw_path(identifier)
        doc_id = compute_doc_id("NLD", source_url, issued)

        document = DocumentRecord(
            title=title,
            source_url=source_url,
            publication_date=issued,
            issuing_authority=meta.get("creator") or None,
            doc_type=map_doc_type(meta.get("native_type", "")),
            language="nld",
            raw_metadata=meta,
        )
        return TaskResult(
            documents=[document],
            files=[FileOut(path=path, content=response.content, doc_id=doc_id)],
        )
