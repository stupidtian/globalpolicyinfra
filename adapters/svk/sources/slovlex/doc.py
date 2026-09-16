"""Task type ``svk_doc``: one instrument's HTML page — the document itself.

One request yields the whole document (page shape probed 2026-09-08,
byte-true samples in the task folder's probe archive): a warning banner,
the metadata table ``<table id="InfoTable">`` (label/value rows), the
relation panel "Vzťahy predpisu" (per-relation tables of referenced
instruments), then the full text. The response carries no charset header
— the bytes are UTF-8 and are decoded explicitly (the 2026-07 legacy
crawl lost every Slovak diacritic by trusting HTTP-client guessing).

The listing row rides in task params and is cross-checked against the
page (number, type): a mismatch there means the page template or the
listing shape changed — escalated loudly, never silently absorbed. The
publication DATE is page-authoritative: for dead instruments the listing
regenerates its row with the end date in every field (probed 2026-09-15,
201/2022 Z. z. — that row is the instrument's only index entry), so a
date mismatch records the listing value in meta and trusts the page.
Template drift observed between 2026-07 and 2026-09 (a "čiastka" row
appeared) is why the parser reads the table generically: known labels map
to meta keys, unknown labels are ignored, absent optional labels are
omitted — nothing guessed, nothing faked.
"""

from __future__ import annotations

import html as html_mod
import re

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.svk.sources.slovlex import (
    ALIAS_VER,
    canonical_html_url,
    canonical_pdf_url,
    iri_parts,
    map_doc_type,
    number_segment,
    sk_date_to_iso,
)
from adapters.svk.sources.slovlex.pdf import pdf_path
from core.document import DocumentRecord, compute_doc_id

__all__ = [
    "SvkDocHandler",
    "html_path",
    "parse_historia",
    "parse_info_table",
    "parse_relations",
]

_INFO_TABLE_RE = re.compile(r'<table id="InfoTable">(.*?)</table>', re.DOTALL)
_ROW_RE = re.compile(
    r'<tr>\s*<td class="title[a-z_]*">(.*?)</td>\s*'
    r'<td class="value[a-z_]*">(.*?)</td>\s*</tr>',
    re.DOTALL,
)
_RELATION_RE = re.compile(
    r'<button class="accordion_relations"[^>]*>(.*?)</button>\s*'
    r'<div class="panel_relations">(.*?)</div>',
    re.DOTALL,
)
_RELATION_REF_RE = re.compile(
    r'<td class="infoTable-nadpis">(.*?)</td>', re.DOTALL
)

#: The embedded "História" table (probed 2026-09-15, present on every page
#: of an instrument, including the as-declared alias): one row per version
#: with its stable iri, whether it is the declared text, its validity
#: window and the amending law's cell — the complete version list of an
#: instrument, zero extra requests.
_HIST_ROW_RE = re.compile(
    r'<tr class="effectivenessHistoryItem"(.*?)</tr>', re.DOTALL
)
_HIST_ATTR_RE = re.compile(r'data-(iri|vyhlasene|ucinnostod|ucinnostdo)="([^"]*)"')


def _cell_text(fragment: str) -> str:
    """Tag-free cell text: list items joined with '; ', entities resolved,
    whitespace (incl. &nbsp;) collapsed."""
    prepared = fragment.replace("</li>", "\x00")
    text = html_mod.unescape(re.sub(r"<[^>]+>", "", prepared))
    items = [re.sub(r"[\s\u00a0]+", " ", part).strip() for part in text.split("\x00")]
    return "; ".join(part for part in items if part)


def parse_info_table(page: str) -> dict[str, str]:
    """InfoTable rows as a {label-without-colon: cell-text} dict."""
    table = _INFO_TABLE_RE.search(page)
    if table is None:
        raise ValueError("page carries no InfoTable metadata table")
    out: dict[str, str] = {}
    for label_html, value_html in _ROW_RE.findall(table.group(1)):
        label = _cell_text(label_html).rstrip(":").strip()
        if label:
            out[label] = _cell_text(value_html)
    return out


def parse_relations(page: str) -> str:
    """Relation panel as one meta string: 'Predpis mení:523/2004 Z. z.;…'.

    Relation types and their counts vary per instrument (probed: amending
    laws list what they amend, base laws list what amends them, repealed
    laws list their repealer); the label is captured verbatim in Slovak.
    """
    sections: list[str] = []
    for label_html, panel_html in _RELATION_RE.findall(page):
        refs = [_cell_text(ref) for ref in _RELATION_REF_RE.findall(panel_html)]
        refs = [ref for ref in refs if ref]
        if refs:
            label = _cell_text(label_html)
            sections.append(f"{label}:{';'.join(refs)}")
    return " | ".join(sections)


def parse_historia(page: str) -> list[dict[str, str]]:
    """The embedded version history: one dict per "História" row.

    Keys: iri (full /SK/ZZ/… form), vyhlasene ("1" on the declared-text
    row), ucinnostod/ucinnostdo (ISO dates or empty), novela (the
    amending-law cell, tag-free). Row order is the source's own.
    """
    rows: list[dict[str, str]] = []
    for row_html in _HIST_ROW_RE.findall(page):
        attrs = dict(_HIST_ATTR_RE.findall(row_html))
        if "iri" not in attrs:
            continue
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.DOTALL)
        novela = _cell_text(cells[-1]) if len(cells) >= 3 else ""
        rows.append({
            "iri": attrs["iri"],
            "vyhlasene": attrs.get("vyhlasene", ""),
            "ucinnostod": attrs.get("ucinnostod", ""),
            "ucinnostdo": attrs.get("ucinnostdo", ""),
            "novela": novela,
        })
    return rows


def _historia_meta(rows: list[dict[str, str]]) -> str:
    """'ver|od|do|novela' per version, ';'-joined — the timeline in meta."""
    parts = []
    for row in rows:
        _, _number, ver = iri_parts(row["iri"])
        label = ALIAS_VER if row["vyhlasene"] == "1" else ver
        parts.append(f"{label}|{row['ucinnostod']}|{row['ucinnostdo']}|{row['novela']}")
    return ";".join(parts)


def html_path(iri: str) -> str:
    """Raw-folder path of the HTML main file below the country root."""
    rocnik, number, ver = iri_parts(iri)
    seg = number_segment(number)
    return f"01_raw/slovlex/{rocnik}/{seg}/{rocnik}_{seg}_{ver}.html"


def _require(info: dict[str, str], label: str, iri: str) -> str:
    value = info.get(label, "").strip()
    if not value:
        raise ValueError(f"page of {iri} carries no {label!r} row")
    return value


class SvkDocHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=canonical_html_url(str(task.params["iri"])))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = dict(task.params)
        iri = str(params["iri"])
        if response.status_code != 200:
            raise ValueError(f"page of {iri} returned HTTP {response.status_code}")
        page = response.content.decode("utf-8", errors="replace")

        info = parse_info_table(page)

        # Listing × page cross-checks — a mismatch is a shape change.
        page_cislo = _require(info, "Číslo predpisu", iri)
        if page_cislo != str(params["cislo"]):
            raise ValueError(
                f"page of {iri} numbers itself {page_cislo!r}, listing said "
                f"{params['cislo']!r}"
            )
        page_declared = sk_date_to_iso(_require(info, "Dátum vyhlásenia", iri))
        if page_declared is None:
            raise ValueError(f"page of {iri} has an unparsable Dátum vyhlásenia")
        if page_declared != str(params["vyhlaseny"]):
            # Probed in production (2026-09-15, 201/2022 Z. z.): the listing
            # regenerates dead instruments' rows with their END date in every
            # date field — the row is the instrument's only index entry, so
            # dropping it would lose the law. The page is the native truth:
            # its declaration date wins, the listing value is kept in meta.
            listing_date = str(params["vyhlaseny"])
        else:
            listing_date = ""
        page_typ = _require(info, "Typ", iri)
        if page_typ != str(params["typ_predp_value"]):
            raise ValueError(
                f"page of {iri} types itself {page_typ!r}, listing said "
                f"{params['typ_predp_value']!r}"
            )
        title = _require(info, "Názov", iri)

        rocnik, _number, ver = iri_parts(iri)
        publication_date = page_declared
        machine_type = params.get("typ_predp")
        meta: dict[str, str] = {
            "typ_predp_value": str(params["typ_predp_value"]),
            "cislo": str(params["cislo"]),
            "rocnik": rocnik,
            "verzia": ver,
            "datum_vyhlasenia": page_declared,
            "pdf_url": canonical_pdf_url(iri),
        }
        if machine_type is not None:
            meta["typ_predp"] = str(machine_type)
        if listing_date:
            meta["vyhlaseny_listing"] = listing_date  # regenerated row, see above
        for param_key in ("ucinny_od", "ucinny_do"):
            value = params.get(param_key)
            if value is not None:
                meta[param_key] = str(value)
        for label, meta_key in (("Dátum schválenia", "datum_schvalenia"),
                                ("Dátum účinnosti od", "datum_ucinnosti_od"),
                                ("Dátum účinnosti do", "datum_ucinnosti_do")):
            raw = info.get(label, "").strip()
            if raw:
                iso = sk_date_to_iso(raw)
                if iso is None:
                    raise ValueError(f"page of {iri} has an unparsable {label}")
                meta[meta_key] = iso
        for label, meta_key in (("Nachádza sa v čiastke", "ciastka"),
                                ("Právna oblasť", "pravna_oblast"),
                                ("Legislatívny proces", "legislativny_proces")):
            value = info.get(label, "").strip()
            if value:
                meta[meta_key] = value
        autor = info.get("Autor", "").strip()
        relations = parse_relations(page)
        if relations:
            meta["vztahy"] = relations
        historia = parse_historia(page)
        if historia:
            meta["historia"] = _historia_meta(historia)
        if int(params.get("pdf_ok", 0)):
            # Written by the svk_pdf task that spawned this one.
            meta["files"] = pdf_path(iri)

        # Version channel (versions=1 sweeps): fetch every dated version
        # the História table offers. The declared text is this very page —
        # not re-spawned; spawned tasks drop the versions flag (their own
        # História is redundant), so the spawn graph cannot recurse.
        next_tasks: list[TaskSeed] = []
        if params.get("versions"):
            for row in historia:
                if row["vyhlasene"] == "1":
                    continue
                spawn_params = {
                    key: value for key, value in params.items() if key != "versions"
                }
                spawn_params["iri"] = row["iri"]
                spawn_params["pdf_ok"] = 0
                next_tasks.append(TaskSeed(type="svk_doc", params=spawn_params))

        record = DocumentRecord(
            title=title,
            source_url=canonical_html_url(iri),
            publication_date=publication_date,
            issuing_authority=autor or None,
            doc_type=map_doc_type(
                str(machine_type) if machine_type is not None else None,
                str(params["typ_predp_value"]),
            ),
            language="slk",
            raw_metadata=meta,
        )
        doc_id = compute_doc_id("SVK", record.source_url, publication_date)
        return TaskResult(
            documents=[record],
            files=[FileOut(path=html_path(iri), content=response.content, doc_id=doc_id)],
            next_tasks=next_tasks,
        )
