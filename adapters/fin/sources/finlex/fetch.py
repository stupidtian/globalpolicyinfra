"""Task type ``sd_fetch``: one manifestation, one request, one document.

GET ``/akn/fi/act/statute/{year}/{number}/{lang}@`` — the full Akoma
Ntoso 3.0 XML (metadata + full text in one response, ``contains=
"originalVersion"``: the as-enacted gazette snapshot). The response bytes
are stored verbatim; the parse reports:

- the **statutes work row** (upsert, partial rows merge): the fin-language
  parse writes the work fields — native type/category codes plus the
  Finnish labels from the record's own TLCConcept vocabulary, both dates,
  ELI alias, the authority read from the Finnish title, list status, the
  source's file-production stamp — and the swe-language parse writes
  ``title_sv`` (plus the shared dates/status, idempotent same-values);
- one **documents row per language variant** hashing its own manifestation
  URL (CHE multilingual ruling; a single-language statute simply produces
  one row);
- **authority rule (user ruling Q7 2026-09-13: empty over wrong)**: the
  source's FRBRauthor is hard-wired to parliament — even for ministry
  decrees — so it never feeds ``issuing_authority``; it travels in meta as
  ``frbr_author`` for the record. The authority column carries the issuing
  phrase *read verbatim from the Finnish title* (the genitive phrase
  before «asetus|päätös|ilmoitus|avoin kirje|luettelo|työjärjestys», e.g.
  "Valtioneuvoston asetus …" → "Valtioneuvoston") — a title substring,
  never an inflection-reconstructed guess; titles without an issuing
  phrase (Laki… acts never carry one) stay empty. Swedish-only historical
  statutes have no authority (the phrase rules are Finnish).

Probed shapes folded into the parse (2026-09-13, samples in the task
folder): the preface carries ``docNumber`` (51/2025) and ``docTitle``;
historic statutes use compound numbers (1917/1-001) — the number is an
opaque string end to end; the entry-into-force lives only in a body
clause ("tulee voimaan …"), there is no structured field for it in the
gazette layer — recorded as a known gap, not parsed out of prose.

A 404 here is *not* declared as data: the address came from a list fetched
moments ago, so not-found means something truly broke and must fail loud
(the framework's default 404 = permanent).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.fin.sources.finlex import API_BASE
from core.document import DocumentRecord, compute_doc_id

__all__ = ["SdFetchHandler", "authority_from_title", "map_doc_type"]

_NAMESPACES = {
    "akn": "http://docs.oasis-open.org/legaldocml/ns/akn/3.0",
    "finlex": "http://data.finlex.fi/schema/finlex",
}

#: typeStatute code → controlled doc_type (native code + Finnish label
#: always kept; cross-country typology is analysis-side, not collection-
#: side; unknown codes → OTHER, never guessed).
_TYPE_TO_DOC_TYPE: dict[str, str] = {
    "act": "STATUTE",
    "decree": "DECREE",
    "decision": "SECONDARY_LEGISLATION",
}

#: The issuing phrase in a Finnish statute title, as a genitive phrase
#: directly before one of the instrument nouns the gazette uses. Matched
#: verbatim (kept as the title substring it is — no inflection reverse-
#: engineering, user ruling Q7: empty over wrong).
_AUTHORITY_RE = re.compile(
    r"^([A-ZÄÅÖ][\wäöüåÄÖÜ\- ]*?n)\s+"
    r"(asetus|päätös|ilmoitus|avoin kirje|luettelo|työjärjestys)\b"
)


def map_doc_type(type_code: str) -> str:
    return _TYPE_TO_DOC_TYPE.get(type_code.strip(), "OTHER")


def authority_from_title(title: str) -> str | None:
    match = _AUTHORITY_RE.match(title.strip())
    if match is None:
        return None
    return match.group(1).strip()


def _text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


class SdFetchHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        year = str(task.params["year"])
        number = str(task.params["number"])
        lang = str(task.params["lang"])
        return RequestSpec(
            url=f"{API_BASE}/akn/fi/act/statute/{year}/{number}/{lang}@",
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        year = str(task.params["year"])
        number = str(task.params["number"])
        lang = str(task.params["lang"])

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise ValueError(f"statute {year}/{number}/{lang}: body is not XML: {exc}") from exc
        if not root.tag.endswith("akomaNtoso"):
            raise ValueError(
                f"statute {year}/{number}/{lang}: unexpected root element {root.tag!r}"
            )

        act = root.find("akn:act", _NAMESPACES)
        if act is None:
            raise ValueError(f"statute {year}/{number}/{lang}: no act element")
        meta = act.find("akn:meta", _NAMESPACES)
        if meta is None:
            raise ValueError(f"statute {year}/{number}/{lang}: no meta block")

        work = meta.find("akn:identification/akn:FRBRWork", _NAMESPACES)
        if work is None:
            raise ValueError(f"statute {year}/{number}/{lang}: no FRBRWork")

        def work_date(name: str) -> str | None:
            node = work.find(f"akn:FRBRdate[@name='{name}']", _NAMESPACES)
            return (node.get("date") or "").strip() or None if node is not None else None

        date_issued = work_date("dateIssued")
        date_published = work_date("datePublished")
        # Three probed date shapes: modern records carry dateIssued +
        # datePublished; pre-modern records (1917/1-001, imperial-era
        # Senate decisions) carry dateIssued only; some directory-only
        # entries (e.g. 1994/787 sv, Högsta domstolens arbetsordning)
        # carry a generated approximation instead — dateIssuedGenerated
        # (the source's own honesty marker; flagged in meta). Empty over
        # wrong: the document's publication_date stays empty when no real
        # publication date exists (doc_id dates to 00000000).
        date_issued_generated = False
        if not date_issued:
            date_issued = work_date("dateIssuedGenerated")
            date_issued_generated = date_issued is not None
        if not date_published and not date_issued:
            raise ValueError(
                f"statute {year}/{number}/{lang}: no usable date on the work "
                "(datePublished / dateIssued / dateIssuedGenerated all absent)"
            )

        uri = _text_or_none(work.find("akn:FRBRuri", _NAMESPACES), "value")
        if uri is not None and uri.strip("/") != f"akn/fi/act/statute/{year}/{number}":
            raise ValueError(
                f"statute {year}/{number}/{lang}: response describes {uri!r} instead"
            )

        eli_node = work.find("akn:FRBRalias[@name='eli']", _NAMESPACES)
        eli = (eli_node.get("value") or "").strip() or None if eli_node is not None else None

        frbr_author_node = work.find("akn:FRBRauthor", _NAMESPACES)
        frbr_author = (
            (frbr_author_node.get("href") or "").strip() or None
            if frbr_author_node is not None
            else None
        )

        produced_node = meta.find(
            "akn:identification/akn:FRBRManifestation/"
            "akn:FRBRdate[@name='dateProduced']",
            _NAMESPACES,
        )
        date_produced = (
            (produced_node.get("date") or "").strip() or None
            if produced_node is not None
            else None
        )

        # Native type/category: the proprietary codes are authoritative, the
        # record's own TLCConcept block carries the Finnish labels.
        proprietary = meta.find("akn:proprietary", _NAMESPACES)
        type_code = self._ref_code(proprietary, "typeStatute")
        category_code = self._ref_code(proprietary, "categoryStatute")
        labels = {
            concept.get("eId") or "": (concept.get("showAs") or "").strip()
            for concept in meta.findall(".//akn:TLCConcept", _NAMESPACES)
        }

        preface = act.find("akn:preface", _NAMESPACES)
        doc_number = _text(preface.find(".//akn:docNumber", _NAMESPACES)) if preface is not None else ""
        title = _text(preface.find(".//akn:docTitle", _NAMESPACES)) if preface is not None else ""
        if not title:
            raise ValueError(f"statute {year}/{number}/{lang}: no docTitle in the preface")

        list_status = str(task.signal) if task.signal else None

        statute_row: dict[str, str] = {
            "year": year,
            "number": number,
            "date_issued": date_issued or "",
            "date_published": date_published or "",
            "list_status": list_status or "",
            "date_produced": date_produced or "",
        }
        if type_code:
            statute_row["type_code"] = type_code
            statute_row["type_label"] = labels.get(type_code, "")
        if category_code:
            statute_row["category_code"] = category_code
            statute_row["category_label"] = labels.get(category_code, "")
        if eli:
            statute_row["eli"] = eli
        authority: str | None = None
        if lang == "fin":
            statute_row["title_fi"] = title
            authority = authority_from_title(title)
            if authority:
                statute_row["authority"] = authority
        else:
            statute_row["title_sv"] = title

        meta_out: dict[str, str] = {"doc_number": doc_number} if doc_number else {}
        if type_code:
            meta_out["type_code"] = type_code
            meta_out["type_label"] = labels.get(type_code, "")
        if date_issued:
            meta_out["date_issued"] = date_issued
        if eli:
            meta_out["eli"] = eli
        if list_status:
            meta_out["list_status"] = list_status
        if date_produced:
            meta_out["date_produced"] = date_produced
        if date_issued_generated:
            meta_out["date_issued_generated"] = "1"
        if frbr_author:
            meta_out["frbr_author"] = frbr_author

        filename = f"{lang}.xml"
        meta_out["files"] = filename
        source_url = (
            f"{API_BASE}/akn/fi/act/statute/{year}/{number}/{lang}@"
        )
        document = DocumentRecord(
            title=title,
            source_url=source_url,
            publication_date=date_published,
            issuing_authority=authority,
            doc_type=map_doc_type(type_code),
            entity_ref=f"statutes:{year}/{number}",
            language=lang,
            raw_metadata=meta_out,
        )
        doc_id = compute_doc_id("FIN", source_url, date_published)

        return TaskResult(
            upsert_rows={"statutes": [statute_row]},
            documents=[document],
            files=[
                FileOut(
                    path=f"01_raw/finlex/sd/{year}/{number}/{filename}",
                    content=response.content,
                    doc_id=doc_id,
                )
            ],
        )

    @staticmethod
    def _ref_code(proprietary: ET.Element | None, tag: str) -> str:
        if proprietary is None:
            return ""
        node = proprietary.find(f"finlex:{tag}", _NAMESPACES)
        if node is None:
            return ""
        return (node.get("refersTo") or "").lstrip("#").strip()


def _text_or_none(element: ET.Element | None, attr: str) -> str | None:
    if element is None:
        return None
    return (element.get(attr) or "").strip() or None
