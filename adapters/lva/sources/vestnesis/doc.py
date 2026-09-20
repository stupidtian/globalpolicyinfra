"""Task type ``vestnesis_doc``: one document's gazette page, one request.

GET ``https://www.vestnesis.lv/ta/id/{docId}`` — the transport follows
the server redirect with which newer documents answer onto their
canonical ``/op/{year}/{issue}.{ordinal}`` page — and produce **both**
outputs from the same response (one request per document; the page
embeds the as-published text, so no separate text task exists):

- a DocumentRecord whose bibliographic fields come from the page's
  "PAR DOKUMENTU" block (issuer / type / adoption date / OP number) and
  the citation-tool values (the verbatim publication reference naming
  the gazette issue and date — e.g. ``Publicēts oficiālajā izdevumā
  "Latvijas Vēstnesis", 4.06.2024., Nr. 107``; legacy pages cite as
  ``oficiālajā laikrakstā`` and may carry a second medium, the Saeima
  and Cabinet reporter *Ziņotājs*);
- a FileOut storing the response bytes **gzip-compressed** as the primary
  ``doc.html.gz`` file, doc_id-carried. The gazette page carries ~260 KB
  of site chrome around a ~28 KB body (probed across 1995-2024 eras), so
  verbatim-but-compressed storage keeps the as-published guarantee
  (gunzip reproduces the page byte-for-byte) at ~15% of the raw size;
  the file hash is the checksum of the stored (compressed) bytes, per
  the ledger's semantics.

Row fields the page lacks (entry-into-force date, document number,
status, loss-of-force date, the untruncated title) arrive through the
seed params from the listing row and are merged into meta unchanged.
The canonical /op/ address is constructed from the page's OP number and
cross-checked against the citation link value when present. Probed
2026-09-16, samples in the task folder; see
docs/countries/lva/vestnesis-zh.md.
"""

from __future__ import annotations

import gzip
import html as html_module
import re

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.lva.sources.vestnesis import DOC_BASE, is_municipal_issuer, source_url_for
from core.document import DocumentRecord, compute_doc_id

__all__ = ["VestnesisDocHandler", "map_doc_type"]

#: Veids (native type word) -> controlled doc_type. The native word is
#: always kept in meta; cross-country typology is analysis-side.
_VEIDS_TO_TYPE: dict[str, str] = {
    "likums": "STATUTE",
    "noteikumi": "REGULATION",
    "rīkojums": "ORDER",
    "lēmums": "DECREE",
    "ziņojums": "OTHER",
}

_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.DOTALL)
_CITATION_VALUE_RE = re.compile(r"name=\"atsauce\"[^>]*value='([^']*)'")
_PUB_CITATION_RE = re.compile(
    r"Publicēts oficiālajā (?:laikrakstā|izdevumā)\s*"
    r"(?:&#34;|&quot;|\")\s*Latvijas Vēstnesis(?:&#34;|&quot;|\")\s*,"
    r"\s*(\d{1,2})\.(\d{2})\.(\d{4})\.,\s*Nr\.\s*([0-9/]+)"
)

#: The labelled cells of the page's bibliographic block (verbatim shapes
#: of both eras; searched within a window after the block's heading).
_INFO_ANCHOR = "PAR DOKUMENTU"
_INFO_WINDOW = 700
_ISSUER_RE = re.compile(r"Izdevējs: <span>([^<]*)</span>")
_VEIDS_RE = re.compile(r"Veids: <span>([^<]*)</span>")
_ADOPTION_RE = re.compile(r"Pieņemts: <span>([^<]*)</span>")
_OP_NR_RE = re.compile(r"OP numurs: <span>([^<]*)</span>")


def map_doc_type(veids: str) -> str:
    return _VEIDS_TO_TYPE.get(veids.strip().lower(), "OTHER")


def _lv_to_iso(day: str, month: str, year: str) -> str:
    return f"{year}-{month}-{int(day):02d}"


def _clean(raw: str) -> str:
    return html_module.unescape(re.sub(r"\s+", " ", raw)).strip()


def _clean_title(raw: str) -> str:
    text = _clean(raw)
    suffix = " - Latvijas Vēstnesis"
    if text.endswith(suffix):
        text = text[: -len(suffix)].rstrip()
    return text


class VestnesisDocHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=source_url_for(str(task.params["doc_id_src"])))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        doc_id_src = str(task.params["doc_id_src"])
        try:
            page = response.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"vestnesis_doc {doc_id_src}: document page is not UTF-8 ({exc})"
            ) from exc

        # Both eras carry the cross-site likumi link for this very id —
        # the cheapest proof the answer is this document's page.
        if f"likumi.lv/ta/id/{doc_id_src}" not in page:
            raise ValueError(
                f"vestnesis_doc {doc_id_src}: no likumi.lv cross-link for this id "
                "in the page — wrong or reshaped document page"
            )

        anchor = page.find(_INFO_ANCHOR)
        if anchor < 0:
            raise ValueError(
                f"vestnesis_doc {doc_id_src}: no 'PAR DOKUMENTU' block — "
                "document page shape may have changed"
            )
        window = page[anchor : anchor + _INFO_WINDOW]
        issuer_match = _ISSUER_RE.search(window)
        veids_match = _VEIDS_RE.search(window)
        adoption_match = _ADOPTION_RE.search(window)
        if not (issuer_match and veids_match):
            raise ValueError(
                f"vestnesis_doc {doc_id_src}: incomplete PAR DOKUMENTU block "
                f"(issuer={bool(issuer_match)}, veids={bool(veids_match)}) — "
                "page shape may have changed"
            )
        issuer = _clean(issuer_match.group(1))
        veids = _clean(veids_match.group(1))
        # Scope settles at the page: issuer-less listing rows (correction
        # announcements — probed 2000-01-14) can only be classified here, and
        # a fair number of them turn out to be municipal acts (probed 2026:
        # Mārupes novada dome corrections). Explained skip, not an error.
        scope = str(task.params.get("scope_slice", "state"))
        if scope == "state" and is_municipal_issuer(issuer):
            return TaskResult(
                expected_empty=(
                    f"vestnesis_doc {doc_id_src}: municipal act per the page "
                    f"({issuer}), outside scope=state"
                )
            )
        adoption_raw = _clean(adoption_match.group(1)) if adoption_match else ""
        day_match = re.match(r"(\d{1,2})\.(\d{2})\.(\d{4})", adoption_raw)
        if not (issuer and veids and (day_match or not adoption_raw)):
            raise ValueError(
                f"vestnesis_doc {doc_id_src}: unparseable bibliographic block "
                f"(issuer={issuer!r}, veids={veids!r}, adoption={adoption_raw!r})"
            )
        # Municipal regulation pages (and a few others) carry no Pieņemts
        # cell at all — the adoption date is simply absent from the source;
        # omission is recorded, not guessed.
        pienemts = (
            _lv_to_iso(day_match.group(1), day_match.group(2), day_match.group(3))
            if day_match
            else ""
        )

        citations = _CITATION_VALUE_RE.findall(page)
        pub_citation = next((c for c in citations if c.startswith("Publicēts")), None)
        if pub_citation is None:
            raise ValueError(
                f"vestnesis_doc {doc_id_src}: no 'Publicēts oficiālajā …' citation "
                "value — a published act carries its gazette reference"
            )
        citation_match = _PUB_CITATION_RE.search(pub_citation)
        if citation_match is None:
            raise ValueError(
                f"vestnesis_doc {doc_id_src}: unparseable publication citation "
                f"{pub_citation!r}"
            )
        citation_iso = _lv_to_iso(
            citation_match.group(1), citation_match.group(2), citation_match.group(3)
        )
        pub_nr = citation_match.group(4)

        # The listing row's publication reference is the as-published event
        # date and anchors doc_id; the page citation is a live view that
        # later corrections can re-date (probed drift cases 2000-2001 moved
        # the page ahead of the listing by 2-54 days). Record, don't fail.
        param_pub = str(task.params.get("pub_date", ""))
        pub_iso = param_pub or citation_iso

        op_number = ""
        op_nr_match = _OP_NR_RE.search(window)
        if op_nr_match:
            op_number = _clean(op_nr_match.group(1))
        # Canonical /op/ address: constructed from the OP number, calibrated
        # by the citation link value when the page carries one.
        op_url = ""
        if op_number:
            op_url = f"{DOC_BASE}/op/{op_number}"
        citation_link = next((c for c in citations if "vestnesis.lv/op/" in c), None)
        if citation_link:
            citation_link = html_module.unescape(citation_link).strip()
            if op_url and citation_link != op_url:
                raise ValueError(
                    f"vestnesis_doc {doc_id_src}: OP number says {op_url} but the "
                    f"citation links {citation_link} — canonical address drift, loud"
                )
            op_url = citation_link

        row_title = str(task.params.get("row_title", "")).strip()
        if not row_title:
            title_match = _TITLE_RE.search(page)
            row_title = _clean_title(title_match.group(1)) if title_match else ""
        if not row_title:
            raise ValueError(f"vestnesis_doc {doc_id_src}: no title from row or page")

        meta: dict[str, str] = {
            "doc_id_src": doc_id_src,
            "likumi_url": f"https://www.likumi.lv/ta/id/{doc_id_src}",
            "native_type": veids,
            "publicets_raw": pub_citation.replace("&#34;", '"').replace("&quot;", '"'),
            "publicets_nr": pub_nr,
            "scope_slice": str(task.params.get("scope_slice", "")),
            "list_row_title": row_title,
        }
        if op_url:
            meta["op_url"] = op_url
        if op_number:
            meta["op_numurs"] = op_number
        if param_pub and citation_iso != pub_iso:
            meta["citation_date"] = citation_iso
        if pienemts:
            meta["pienemts"] = pienemts
        number = str(task.params.get("numurs", ""))
        if number:
            meta["dokumenta_nr"] = number
        in_force = str(task.params.get("in_force", ""))
        if in_force:
            meta["stajas_speka"] = in_force
        zaude = str(task.params.get("zaude", ""))
        if zaude:
            meta["zaude_speku"] = zaude
        statuss = str(task.params.get("statuss", ""))
        if statuss:
            meta["statuss"] = statuss

        source_url = source_url_for(doc_id_src)
        document = DocumentRecord(
            title=row_title,
            source_url=source_url,
            publication_date=pub_iso,
            issuing_authority=issuer,
            doc_type=map_doc_type(veids),
            language="lav",
            raw_metadata=meta,
        )
        pub_day = pub_iso.replace("-", "")
        path = f"01_raw/vestnesis/{pub_iso[:4]}/D{pub_day}/{doc_id_src}/doc.html.gz"
        return TaskResult(
            documents=[document],
            files=[
                FileOut(
                    path=path,
                    content=gzip.compress(response.content, 9),
                    doc_id=compute_doc_id("LVA", source_url, pub_iso),
                )
            ],
        )
