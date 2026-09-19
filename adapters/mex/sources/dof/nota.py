"""Task type ``dof_nota``: one gazette entry, one request, one document.

GET the canonical note page ``nota_detalle.php?codigo=…&fecha=…`` and
register it. Probed shapes (2026-09-14, samples in the task folder — a
live-shaped 2020 page recovered via the CommonCrawl corpus, and the
listing view probed live):

- The page carries a ``DOF: DD/MM/YYYY`` header line and the full text
  inside ``<div id='DivDetalleNota'>`` — quote style varies (single and
  double both occur); the text block itself is a *nested* HTML document
  whose own ``<title>`` holds the norm title again (kept in meta as
  ``titulo_interno``).
- The header date is the note's canonical publication date. It normally
  equals the listing's ``fecha``; when it sits up to 10 days *earlier*
  the note is a republication carried by a later edition's listing
  (Friday-evening notes re-hung on Monday's index, probed 2026-09-17:
  codigos 5519526/5526743/5763626) — accepted with the page date as
  ``publication_date`` and the listing date kept in ``meta.fecha_listado``
  (+ ``meta.relist``). Any other mismatch refuses: the listing pointed at
  a different day's content.
- Charsets on this site are inconsistent (edition pages declare
  ISO-8859-1; at least one probed nota page travelled with a UTF-8
  HTTP header while its markup declared ISO-8859-1) — the declared
  meta charset wins, latin-1 as fallback; anchors are ASCII either way.
- The note page does NOT repeat the issuing department; the department
  (and section/organism context) travel in the task params from the
  index page — the gazette's listing view is the authority for those.
- The response bytes are stored verbatim as the primary file
  (``nota.html``); a 404 here is *not* declared as data: the codigo
  came from an edition page fetched moments ago, so not-found means
  something truly broke and must fail loud.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.mex.sources.dof import BASE_URL
from core.document import DocumentRecord, compute_doc_id

__all__ = ["DofNotaHandler", "map_doc_type"]

_DOF_DATE_RE = re.compile(r"DOF:\s*(\d{1,2})/(\d{1,2})/(\d{4})")
_CHARSET_RE = re.compile(rb"charset=[\"']?([\w-]+)", re.IGNORECASE)
_BODY_MARK = "DivDetalleNota"
_NESTED_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_WS_RE = re.compile(r"\s+")

#: How far behind the listing date a note's own "DOF:" line may sit and
#: still count as a republication carried by a later listing (see parse).
_RELIST_DAYS = timedelta(days=10)

#: First title word (accent-stripped) → controlled doc_type. The native
#: word always travels in meta ``tipo``; cross-country typology is
#: analysis-side, not collection-side.
_TYPE_BY_WORD: dict[str, str] = {
    "LEY": "STATUTE",
    "DECRETO": "DECREE",
    "ACUERDO": "RESOLUTION",
    "RESOLUCION": "RESOLUTION",
    "REGLAMENTO": "REGULATION",
    "NOM": "REGULATION",  # Norma Oficial Mexicana
    "CIRCULAR": "CIRCULAR",
    "ORDEN": "ORDER",
    "AVISO": "NOTICE",
    "CONVENIO": "AGREEMENT",
}


def map_doc_type(title: str) -> str:
    first = _first_word(title)
    return _TYPE_BY_WORD.get(first, "OTHER")


_LEADING_WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")


def _first_word(title: str) -> str:
    """Leading alphabetic run of the title: "NOM-028-STPS-2011…" → "NOM"."""
    word = title.strip().split(" ", 1)[0] if title.strip() else ""
    m = _LEADING_WORD_RE.match(word)
    if not m:
        return ""
    decomposed = unicodedata.normalize("NFD", m.group(0).upper())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _decode(raw: bytes) -> str:
    """Declared meta charset wins; latin-1 is the site's historic default."""
    m = _CHARSET_RE.search(raw[:2048])
    if m and m.group(1).decode().lower() == "utf-8":
        return raw.decode("utf-8", errors="replace")
    return raw.decode("iso-8859-1", errors="replace")


class DofNotaHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        date_iso = str(task.params["fecha"])
        y, m, d = date_iso.split("-")
        return RequestSpec(
            url=f"{BASE_URL}/nota_detalle.php",
            params={"codigo": str(task.params["codigo"]), "fecha": f"{d}/{m}/{y}"},
            headers={"Accept": "text/html"},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        codigo = str(task.params["codigo"])
        date_iso = str(task.params["fecha"])
        y, m, d = date_iso.split("-")
        dmy = f"{d}/{m}/{y}"
        title = str(task.params.get("title", ""))

        raw = response.content
        html = _decode(raw)

        header = _DOF_DATE_RE.search(html)
        if header is None:
            raise ValueError(
                f"nota {codigo}: no 'DOF: DD/MM/YYYY' header line — unknown shape"
            )
        echoed = f"{header.group(3)}-{int(header.group(2)):02d}-{int(header.group(1)):02d}"

        # Publication-date basis: the page's own "DOF:" line is the gazette's
        # canonical claim. It normally equals the listing's fecha; when it is
        # up to _RELIST_DAYS earlier the note is a republication carried by a
        # later edition's listing (Friday vespertina notes re-hung on Monday's
        # matutina index, probed: 5519526/5526743/5763626) — accept with the
        # page date as publication_date and the listing date in meta. Anything
        # else refuses: the listing pointed at content for a different day.
        publication_date = date_iso
        if echoed != date_iso:
            page_day: date | None = None
            listing_day: date | None = None
            try:
                page_day = date.fromisoformat(echoed)
                listing_day = date.fromisoformat(date_iso)
            except ValueError:
                pass
            if page_day is None or listing_day is None or not (
                timedelta(0) < listing_day - page_day <= _RELIST_DAYS
            ):
                raise ValueError(
                    f"nota {codigo}: page echoes DOF {echoed} but the listing said "
                    f"{date_iso} — refusing to collect"
                )
            meta_listing = date_iso
        else:
            meta_listing = ""

        if _BODY_MARK not in html:
            raise ValueError(f"nota {codigo}: no {_BODY_MARK!r} block — unknown shape")

        inner = html[html.index(_BODY_MARK) :]
        nested = _NESTED_TITLE_RE.search(inner[:20000])
        titulo_interno = _WS_RE.sub(" ", nested.group(1)).strip() if nested else ""

        meta: dict[str, str] = {
            "codigo": codigo,
            "edicion": str(task.params.get("edicion", "")),
            "tipo": _first_word(title),
            "files": "nota.html",
        }
        if meta_listing:
            meta["fecha_listado"] = meta_listing
            meta["relist"] = "1"
        publication_date = echoed
        for key in ("seccion", "organismo", "departamento"):
            value = str(task.params.get(key, ""))
            if value:
                meta[key] = value
        if titulo_interno:
            meta["titulo_interno"] = titulo_interno

        document = DocumentRecord(
            title=title or titulo_interno or f"DOF {codigo}",
            source_url=f"{BASE_URL}/nota_detalle.php?codigo={codigo}&fecha={dmy}",
            publication_date=publication_date,
            issuing_authority=str(task.params.get("departamento", "")) or None,
            doc_type=map_doc_type(title),
            language="spa",
            raw_metadata=meta,
        )
        doc_id = compute_doc_id("MEX", document.source_url, publication_date)

        py_, pm_, pd_ = publication_date.split("-")
        path = f"01_raw/dof/{py_}/D{py_}{pm_}{pd_}/{task.params.get('edicion', 'MAT')}/N{codigo}/nota.html"
        return TaskResult(
            documents=[document],
            files=[FileOut(path=path, content=raw, doc_id=doc_id)],
        )
