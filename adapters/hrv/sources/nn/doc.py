"""Task type ``nn_doc``: one gazette item's HTML page, one request.

``GET /eli/sluzbeni/{Y}/{issue}/{ordinal}`` (301 -> the canonical item
page ``/clanci/sluzbeni/{Y_MM}_{issue}_{ordinal}.html``; the transport
follows the redirect). The page has two load-bearing blocks (probed
2026-11-01, samples in the task folder):

- ``detailsTable`` — key/value metadata rows: Dio NN (part), Vrsta
  dokumenta (type), Izdanje (issue, links the whole-issue PDF), Broj
  dokumenta u izdanju (the global ordinal), Stranica tiskanog izdanja
  (printed page — newer eras only), Donositelj (issuer), Datum tiskanog
  izdanja (the official publication date — the ONLY structured date the
  item metadata carries; CSV rows have no date column), ELI.
- ``html-content-frame`` — the body region. 1990-2022 the full text is
  inline (``<p>`` paragraphs; older years carry the platform's own OCR
  layer). 2023+ a not-yet-entered text renders as a ``pdf-view`` div
  whose iframe src is the per-item PDF address — the task then hands
  over to ``nn_pdf`` (which registers the document with the PDF as
  primary) instead of registering a metadata-only stub, so the
  "primary file = full-text carrier" invariant holds from birth
  (DNK main-pointer repair precedent). The HTML page bytes still land
  as a sibling file recorded in the document's meta.files.

Identity checks are loud: the answering page must carry the requested
ELI path and global ordinal, and its issuer must match the inventory
seed when the seed carries a real issuer (rows with a ``-`` issuer skip
the check).
"""

from __future__ import annotations

import re
from html import unescape
from typing import Any

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.hrv.sources.nn import article_pdf_url_for, site_url_for
from core.document import DocumentRecord, compute_doc_id

__all__ = [
    "REQUIRED_META_KEYS",
    "DocHandler",
    "map_doc_type",
    "meta_out",
    "parse_publication_date",
]

_REQUIRED_META_KEYS = ("Izdanje", "Datum tiskanog izdanja", "ELI")
REQUIRED_META_KEYS = _REQUIRED_META_KEYS
# Donositelj is deliberately NOT required: the platform omits the issuer
# block on issuer-less items (probed 2026-11-01 — e.g. 1990/2/16, whose
# inventory row also carries "-"); those register with a NULL authority.

#: Native type word (Vrsta dokumenta) -> controlled doc_type. The native
#: word is always kept in meta; cross-country typology is analysis-side.
#: The source's wide vocabulary (odluka, rješenje, presuda, statut, ...)
#: covers too many meanings to guess at — it all falls through to OTHER
#: (section 5.3 labelling rules; mapping is add-only).
_NATIVE_TO_TYPE: dict[str, str] = {
    "zakon": "STATUTE",
    "ustav": "STATUTE",
    "uredba": "REGULATION",
    "pravilnik": "REGULATION",
    "naredba": "REGULATION",
}

# The detailsTable mixes quote styles — Dio NN/Vrsta/Izdanje rows use
# class='key' while Donositelj uses class="key" (probed 2026-11-01) —
# so the attribute must match both.
_KEY_VALUE_RE = re.compile(r"<span class=[\"']key[\"']>([^<]+):</span>(.*?)</td>", re.DOTALL)
_STICKY_TITLE_RE = re.compile(r'<div id="sticky" class="title">\s*<h2>(.*?)</h2>', re.DOTALL)
_PUB_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})\.?")
_IFRAME_SRC_RE = re.compile(r'<iframe[^>]*src="([^"]+)"')
_TAG_RE = re.compile(r"<[^>]+>")


def map_doc_type(native_type: str) -> str:
    return _NATIVE_TO_TYPE.get(native_type.strip().casefold(), "OTHER")


def _clean(raw: str) -> str:
    return " ".join(unescape(_TAG_RE.sub(" ", raw)).split())


def parse_publication_date(raw: str, label: str) -> str:
    """``30.10.2026.`` -> ``2026-10-30`` (dd.mm.yyyy with an optional
    trailing dot — the platform's only date format)."""
    match = _PUB_DATE_RE.search(raw)
    if match is None:
        raise ValueError(
            f"{label}: unparseable publication date {raw!r} "
            "(expected dd.mm.yyyy[.])"
        )
    day, month, year = (int(part) for part in match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


def _body_region(html: str, label: str) -> str:
    """The region between the html-content-frame opener and the sticky
    metadata panel — where the text lives when present and where the
    pdf-view iframe appears when not."""
    start = html.find("html-content-frame")
    if start < 0:
        raise ValueError(f"{label}: no html-content-frame region — page shape changed")
    end = html.find("article-details-scroll", start)
    if end < 0:
        raise ValueError(
            f"{label}: no article-details-scroll after the body region — "
            "page shape changed"
        )
    return html[start:end]


def meta_out(
    *,
    year: int,
    issue: int,
    ordinal: int,
    native_type: str,
    subtype: str,
    relation: str,
    csv_title: str,
    nn_part: str,
    eli: str,
    printed_page: str,
    body_carrier: str,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    out: dict[str, str] = {
        "issue": f"NN {issue}/{year}",
        "issue_no": str(issue),
        "year": str(year),
        "global_ordinal": str(ordinal),
        "eli": eli,
        "body_carrier": body_carrier,
    }
    if nn_part:
        out["nn_part"] = nn_part
    if native_type and native_type != "-":
        out["native_type"] = native_type
    if subtype and subtype != "-":
        out["subtype"] = subtype
    if relation and relation != "-":
        out["relation"] = relation
    if printed_page:
        out["printed_page"] = printed_page
    if csv_title:
        out["csv_title"] = csv_title
    if extra:
        out.update(extra)
    return out


class DocHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=site_url_for(
                int(task.params["year"]),
                int(task.params["issue"]),
                int(task.params["art"]),
            )
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        year, issue, ordinal = (
            int(task.params["year"]),
            int(task.params["issue"]),
            int(task.params["art"]),
        )
        label = f"nn_doc {year}/{issue}/{ordinal}"
        try:
            html = response.content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{label}: item page is not UTF-8: {exc}") from exc

        meta: dict[str, str] = {}
        for match in _KEY_VALUE_RE.finditer(html):
            meta[_clean(match.group(1))] = _clean(match.group(2))
        missing = [key for key in _REQUIRED_META_KEYS if not meta.get(key)]
        if missing:
            raise ValueError(
                f"{label}: detailsTable keys {missing} missing or empty "
                f"(got {sorted(meta)}) — item page shape may have changed"
            )

        eli_expected = f"/eli/sluzbeni/{year}/{issue}/{ordinal}"
        if meta["ELI"] != eli_expected:
            raise ValueError(
                f"{label}: page ELI {meta['ELI']!r} != requested {eli_expected!r} — "
                "item identity drift"
            )
        page_ordinal_raw = meta.get("Broj dokumenta u izdanju", "")
        if page_ordinal_raw:
            page_ordinal = int(page_ordinal_raw)
            if page_ordinal != ordinal:
                raise ValueError(
                    f"{label}: page ordinal {page_ordinal} != requested {ordinal} — "
                    "item identity drift"
                )
        seed_issuer = str(task.params.get("issuer", "")).strip()
        page_issuer = meta.get("Donositelj", "").strip()
        if (
            seed_issuer
            and seed_issuer != "-"
            and page_issuer.casefold() != seed_issuer.casefold()
        ):
            raise ValueError(
                f"{label}: inventory says issuer {seed_issuer!r} but the page "
                f"answers {page_issuer!r} — item identity drift"
            )

        pub_date = parse_publication_date(meta["Datum tiskanog izdanja"], label)

        title = ""
        sticky = _STICKY_TITLE_RE.search(html)
        if sticky is not None:
            title = _clean(sticky.group(1))
        if not title:
            title = str(task.params.get("title", "")).strip()
        if not title:
            raise ValueError(f"{label}: no title on the page nor in the inventory seed")

        body_region = _body_region(html, label)
        iframe = _IFRAME_SRC_RE.search(body_region)
        pdf_src = iframe.group(1) if iframe is not None else ""
        if "pdf-view" in body_region or pdf_src:
            expected_pdf = article_pdf_url_for(year, issue, ordinal)
            if pdf_src != expected_pdf:
                raise ValueError(
                    f"{label}: pdf-view iframe {pdf_src!r} != expected "
                    f"{expected_pdf!r} — per-item PDF address drift"
                )
            stub_path = f"01_raw/nn/{year}/{issue}_{ordinal}.html"
            pdf_params: dict[str, Any] = {
                "year": year,
                "issue": issue,
                "art": ordinal,
                "title": title,
                "pub_date": pub_date,
                "native_type": str(task.params.get("native_type", "")),
                "subtype": str(task.params.get("subtype", "")),
                "relation": str(task.params.get("relation", "")),
                "issuer": page_issuer,
                "printed_page": meta.get("Stranica tiskanog izdanja", ""),
                "nn_part": meta.get("Dio NN", ""),
            }
            return TaskResult(
                files=[FileOut(path=stub_path, content=response.content)],
                next_tasks=[TaskSeed(type="nn_pdf", params=pdf_params)],
            )

        native_type = str(task.params.get("native_type", "")).strip()
        fields = meta_out(
            year=year,
            issue=issue,
            ordinal=ordinal,
            native_type=native_type,
            subtype=str(task.params.get("subtype", "")).strip(),
            relation=str(task.params.get("relation", "")).strip(),
            csv_title=str(task.params.get("title", "")).strip(),
            nn_part=meta.get("Dio NN", ""),
            eli=meta["ELI"],
            printed_page=meta.get("Stranica tiskanog izdanja", ""),
            body_carrier="html",
        )
        source_url = site_url_for(year, issue, ordinal)
        doc_id = compute_doc_id("HRV", source_url, pub_date)
        record = DocumentRecord(
            title=title,
            source_url=source_url,
            publication_date=pub_date,
            issuing_authority=page_issuer if page_issuer and page_issuer != "-" else None,
            doc_type=map_doc_type(native_type),
            language="hr",
            raw_metadata=fields,
        )
        return TaskResult(
            documents=[record],
            files=[
                FileOut(
                    path=f"01_raw/nn/{year}/{issue}_{ordinal}.html",
                    content=response.content,
                    doc_id=doc_id,
                )
            ],
        )
