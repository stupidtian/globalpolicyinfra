"""Task type ``rt_doc``: one document — official XML, metadata, registration.

GET ``{canonical}/xml`` — the source's own LexDania 2.1 XML (the harvest
API's hrefs point to the same ``/xml`` form, so it is the official machine
channel). The ``<Meta>`` block carries the structured fields; the
``<DokumentIndhold>`` element (when present) is the full text.

Publication-date policy (probed 2026-09-15/16): the search row's
``offentliggoerelsesDato`` (task param ``pub``) is the publication date;
the XML's ``DiesEdicti`` is NOT one — it tracks the current XML rendition
(a 1986 stub carries DiesEdicti 2007-03-16, its digitisation date) and
only lands in meta. Sitemap-mode documents have no ``pub`` param: their
doc_id dates as 00000000 (the documented missing-date form) and the real
date is recoverable from meta ``dies_signi`` / ``doc_texts``.

Stub detection: no ``DokumentIndhold`` child = metadata-only stub
(pre-2007 era, and by nature the textless Lovtidende B notices) — the
task chains ``rt_text`` for the POST-channel full text. Note the chain
order: ``rt_doc`` owns the documents row (primary file ``doc.xml``);
``write_batch`` ignores second inserts for the same doc_id, so the
sibling text registers through the ``doc_texts`` domain table instead.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.dnk.sources.retsinformation import (
    API_BASE,
    map_doc_type,
    parse_dk_date,
    split_eli,
)
from core.document import DocumentRecord, compute_doc_id

__all__ = ["RtDocHandler"]


class RtDocHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=f"{API_BASE}{task.params['eli']}/xml")

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        eli = str(task.params["eli"])
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise ValueError(f"doc {eli}: body is not XML: {exc}") from exc
        if root.tag != "Dokument":
            raise ValueError(f"doc {eli}: unexpected root element {root.tag!r}")
        meta = root.find("Meta")
        if meta is None:
            raise ValueError(f"doc {eli}: no Meta block")

        def get(tag: str) -> str:
            node = meta.find(tag)
            return (node.text or "").strip() if node is not None else ""

        title = get("DocumentTitle") or eli
        pub = str(task.params.get("pub", "")).strip() or None
        code = str(task.params.get("code", "")).strip()
        law_key = str(task.params.get("law_key", "")).strip()
        media, year, _number, flat = split_eli(eli)

        refs = sorted({
            (node.text or "").strip()
            for node in meta.findall("Ref_Accn")
            if (node.text or "").strip()
        })

        raw_meta: dict[str, str] = {
            "eli": eli,
            "media": media,
            "eli_code": code,
            "native_type": get("DocumentType"),
            "pubdate_source": "search" if pub else "none",
            "accession_number": get("AccessionNumber"),
            "document_id": get("DocumentId"),
            "unique_id": get("UniqueDocumentId"),
            "year": get("Year"),
            "number": get("Number"),
            "dies_signi": parse_dk_date(get("DiesSigni")) or get("DiesSigni"),
            "dies_edicti": parse_dk_date(get("DiesEdicti")) or get("DiesEdicti"),
            "announced_in": get("AnnouncedIn"),
            "status": get("Status"),
            "rank": get("Rank"),
            "ministry": get("Ministry"),
            "journal_number": get("JournalNumber"),
        }
        if refs:
            raw_meta["change_refs"] = ";".join(refs)
        for tag, key in (("StartDate", "valid_from"), ("EndDate", "valid_to")):
            value = parse_dk_date(get(tag))
            if value:
                raw_meta[key] = value

        document = DocumentRecord(
            title=title,
            source_url=f"{API_BASE}{eli}",
            publication_date=pub,
            issuing_authority=get("Ministry") or None,
            doc_type=map_doc_type(code),
            entity_ref=f"laws:{law_key}" if law_key else None,
            language="dan",
            raw_metadata=raw_meta,
        )
        doc_id = compute_doc_id("DNK", document.source_url, pub)

        if media == "accn":  # harvest-fallback identity (media-map miss)
            folder = f"01_raw/retsinformation/accn/{flat}"
        else:
            folder = f"01_raw/retsinformation/{media}/{year}/{flat}"
        files = [FileOut(path=f"{folder}/doc.xml", content=response.content, doc_id=doc_id)]
        next_tasks: list[TaskSeed] = []
        if root.find("DokumentIndhold") is None:
            # metadata-only stub (or a naturally textless Lovtidende B
            # notice): the full text, when it exists, lives behind the POST
            # channel — rt_text stores it as a doc_texts-registered sibling.
            next_tasks.append(
                TaskSeed(
                    type="rt_text",
                    params={"eli": eli, "pub": str(task.params.get("pub", "")), "text": "1"},
                )
            )
        return TaskResult(documents=[document], files=files, next_tasks=next_tasks)
