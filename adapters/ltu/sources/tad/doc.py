"""Task type ``tad_doc``: one document's detail page, one request.

GET ``showdoc_l?p_id=…`` — the transport follows the 302 onto the
e-seimas.lrs.lt document page (UTF-8 JSF), whose labelled cells carry
the research metadata. Probed shapes 2026-09-15 (samples in the task
folder); the parse keeps native values losslessly:

- three dates: Priėmimo data (adoption) / Paskelbta (publication — the
  timeline date, naming the medium: TAR since 2014, Valstybės žinios
  before) / Įsigalioja (entry into force, ``class="validFrom"``);
- Rūšis (native type word) mapped to the pack's controlled doc_type
  vocabulary, native always preserved;
- the TAD id (``TAIS.<p_id>`` for legacy acts, a 32-hex id for newer
  ones) extracted from the page's own ``legalAct/lt/TAD/…`` links — it
  is not derivable from p_id for newer acts, and the /rs/ text layer
  addresses documents by it;
- registration data, official number, Eurovoc terms, EU-law relation
  and the current-consolidation stamp are kept as strings; consolidation
  and status fields are the source's *live* view — collection semantics
  = snapshot at fetch time.

A missing Paskelbta on a Lithuanian-language record is a shape failure
(loud), while official translations (Kalba other than Lietuvių) are
separate records without a publication reference — they are
explained-away skips, keeping the corpus single-language.
"""

from __future__ import annotations

import re

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.ltu.sources.tad import PORTAL_BASE, decode_response, source_url_for
from core.document import DocumentRecord

__all__ = ["TadDocHandler", "map_doc_type"]

_TAD_ID_RE = re.compile(r"legalAct/lt/TAD/([A-Za-z0-9.]+)")
_TITLE_RE = re.compile(r'<span id="mainForm:laTitle">(.*?)</span>', re.DOTALL)
_SCRIPT_RE = re.compile(r"<script.*?</script>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_PUBLISHED_RE = re.compile(r"^(?P<medium>[^,]+),\s*(?P<date>\d{4}-\d{2}-\d{2}),\s*Nr\.\s*(?P<number>\S+)")
_VALID_FROM_RE = re.compile(r'class="validFrom">\s*Įsigalioja\s+([\d-]+)')

#: Rūšis (native type word) -> controlled doc_type. The native word is
#: always kept in meta; cross-country typology is analysis-side.
_RUSIS_TO_TYPE: dict[str, str] = {
    "Konstitucija": "CONSTITUTION",
    "Įstatymas": "STATUTE",
    "Kodeksas": "STATUTE",
    "Konstitucinis įstatymas": "STATUTE",
    "Konstitucinis aktas": "STATUTE",
    "Dekretas": "DECREE",
    "Nutarimas": "DECREE",
    "Įsakymas": "ORDER",
}


def map_doc_type(rusis: str) -> str:
    return _RUSIS_TO_TYPE.get(rusis.strip(), "OTHER")


def _cell(html: str, label: str) -> str | None:
    """Value of a labelled detail cell. Two probed label shapes: plain
    ``<td>Label:</td><td>value…</td>`` and bold-wrapped
    ``<span …>Label:</span></td><td>value…</td>``. OverlayPanel scripts
    ride inside value cells and are removed before the value is read."""
    for pattern in (
        re.escape(label) + r"\s*:?\s*</span>\s*</td>\s*<td[^>]*>(.*?)</td>",
        re.escape(label) + r"\s*:\s*</td>\s*<td[^>]*>(.*?)</td>",
    ):
        match = re.search(pattern, html, re.DOTALL)
        if match is None:
            continue
        value = _SCRIPT_RE.sub("", match.group(1))
        value = _TAG_RE.sub(" ", value)
        value = re.sub(r"\s+", " ", value).strip()
        if value:
            return value
    return None


def _tidy(value: str) -> str:
    return re.sub(r"\s*-\s*$", "", value).strip()


class TadDocHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=source_url_for(str(task.params["pid"])),
            params={"p_tr2": "2"},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        pid = str(task.params["pid"])
        html = decode_response(response.content)

        if "legalActNotFoundForm" in html:
            raise ValueError(
                f"tad_doc {pid}: the register answers 'nerastas' — a pid from a fresh "
                "enumeration must exist; the detail entry may have moved"
            )

        title_match = _TITLE_RE.search(html)
        if title_match is None:
            raise ValueError(f"tad_doc {pid}: no mainForm:laTitle title span in the page")
        title = re.sub(r"\s+", " ", _SCRIPT_RE.sub("", title_match.group(1))).strip()

        tad_id_match = _TAD_ID_RE.search(html)
        if tad_id_match is None:
            raise ValueError(f"tad_doc {pid}: no legalAct/lt/TAD link — cannot reach the text layer")
        tad_id = tad_id_match.group(1)

        kalba = _cell(html, "Kalba")
        if kalba is not None and kalba != "Lietuvių":
            return TaskResult(
                expected_empty=(
                    f"tad_doc {pid}: official translation record (Kalba: {kalba}) — "
                    "no publication reference of its own, outside the "
                    "Lithuanian-language corpus"
                )
            )

        published = _cell(html, "Paskelbta")
        if published is None:
            raise ValueError(
                f"tad_doc {pid}: no Paskelbta cell — a Lithuanian-language record "
                "carries its gazette/TAR publication reference"
            )
        published_match = _PUBLISHED_RE.match(published)
        if published_match is None:
            raise ValueError(f"tad_doc {pid}: unparseable Paskelbta value {published!r}")
        pub_iso = published_match.group("date")

        rusis = _cell(html, "Rūšis") or ""
        meta: dict[str, str] = {
            "pid": pid,
            "tad_id": tad_id,
            "tad_url": f"{PORTAL_BASE}/portal/legalAct/lt/TAD/{tad_id}",
        }
        if rusis:
            meta["native_type"] = rusis
        adoption = _cell(html, "Priėmimo data")
        if adoption:
            meta["priemimo_data"] = adoption
        number = _cell(html, "Dokumento Nr.")
        if number:
            meta["dokumento_nr"] = number
        adopted_by = _cell(html, "Priėmė")
        if adopted_by:
            meta["prieme"] = adopted_by
        registration = _cell(html, "Registravimo duomenys")
        if registration:
            meta["registravimo_duomenys"] = registration
        meta["paskelbta_leidinys"] = published_match.group("medium").strip()
        meta["paskelbta_nr"] = published_match.group("number")
        consolidation = _cell(html, "Galiojanti suvestinė redakcija")
        if consolidation and consolidation != "Nėra":
            meta["galiojanti_suvestine"] = _tidy(consolidation)
        eu_relation = _cell(html, "Ryšys su ES teisės aktais")
        if eu_relation and eu_relation != "Nėra":
            meta["es_rysys"] = eu_relation
        valid_from = _VALID_FROM_RE.search(html)
        if valid_from is not None:
            meta["isigalioja"] = valid_from.group(1)
        eurovoc = _cell(html, "Eurovoc terminai")
        if eurovoc:
            meta["eurovoc"] = eurovoc

        source_url = source_url_for(pid)
        document = DocumentRecord(
            title=title,
            source_url=source_url,
            publication_date=pub_iso,
            issuing_authority=adopted_by,
            doc_type=map_doc_type(rusis),
            language="lit",
            raw_metadata=meta,
        )
        return TaskResult(
            documents=[document],
            next_tasks=[
                TaskSeed(
                    type="tad_text",
                    params={"pid": pid, "tad_id": tad_id, "pub_date": pub_iso},
                )
            ],
        )
