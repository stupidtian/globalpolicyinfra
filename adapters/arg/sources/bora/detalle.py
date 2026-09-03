"""Task type ``bora_detalle``: one gazette entry, one request, one document.

GET the URL-addressed detail page ``/detalleAviso/{seccion}/{id}/{YYYYMMDD}``
— session-free (the date rides in the path; probed 2026-09-02 with foreign
and absent sessions). Two page shapes, both probed verbatim:

- **Text form** (modern era): ``#tituloDetalleAviso`` carries h1 (authority,
  e.g. PODER EJECUTIVO), h2 (norm reference, e.g. "Decreto 817/2026") and
  h6 (norma id + description, e.g. "DECTO-2026-817-APN-PTE - Dispónese…");
  ``#cuerpoDetalleAviso.detalle-cuerpo`` holds the full text inline. Stored
  verbatim as ``detalle.html`` (the response bytes are the document).
  **Notice sub-shape** (first seen in the 2026-09-03 real run, 19 archived
  failures): AVISOS OFICIALES entries carry only the h1 authority — no h2,
  no h6; the title becomes "{h1} - {listing kind}".
- **Scan shell** (early era, 1940s–1990s probed): no title/body blocks, but
  the publication date line survives and the page script embeds the whole
  scanned PDF as base64 (``convertBase64InUrlBlob("JVBERi0…")``) — extracted
  in-response to ``aviso.pdf``; the per-aviso PDF endpoint answers 500 in
  this era. Titles and authorities come from the listing row the day task
  passed along.

The plain URL already contains everything the ``?anexos=1`` variant shows
(probed 2026-08-28 on aviso 346526): ``#anexosDiv`` lists attachment PDFs
via ``descargarPDFAnexo("{seccion}","{nro}","{idAnexo}","{fecha}", …)``
calls — each becomes a bora_anexo seed and its target filename is
pre-declared in meta.files (the ledger's documents table is insert-only,
so the anexo task cannot patch the parent row afterwards; a permanently
failed attachment therefore shows up as a declared-but-missing file).

doc_type maps two native sources (2026-09-01 five rules: native first,
mapping is code, vocabulary is pack-controlled): the listing rubro plus
the norma-id prefix, which is finer than the rubro — DNUs sit under the
DECRETOS rubro but their ids start ``DNU-`` (e.g. DNU-2023-70-APN-PTE).
"""

from __future__ import annotations

import base64
import binascii
import html as html_mod
import re

from adapters.arg.sources.bora import BASE_URL
from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskSeed, TaskView
from core.document import DocumentRecord, compute_doc_id

__all__ = ["BoraDetalleHandler", "map_doc_type", "split_norma_id"]

_PUB_DATE_RE = re.compile(r"Fecha de publicaci[oó]n\s*(\d{2})/(\d{2})/(\d{4})")
_TITULO_RE = re.compile(r'id="tituloDetalleAviso"[^>]*>(.*?)id="cuerpoDetalleAviso"', re.DOTALL)
_H_RE: dict[str, re.Pattern[str]] = {
    tag: re.compile(rf"<{tag}[^>]*>\s*(.*?)\s*</{tag}>", re.DOTALL) for tag in ("h1", "h2", "h6")
}
_CUERPO_END_RE = re.compile(r'id="cuerpoDetalleAviso".*?(?=<div class="row")', re.DOTALL)
_PAGINAS_RE = re.compile(
    r'mostrarPdfSeccionPorPaginas\("[^"]+",\s*"\d{8}",\s*"(\d+)"\s*,\s*"(\d+)"'
)
_AVISO_PDF_RE = re.compile(r'renderPDFAviso\("(/pdf/aviso/[^"]+)"\)')
_ANEXO_RE = re.compile(r'descargarPDFAnexo\("([a-z]+)",\s*"(\d+)",\s*"(\d+)",\s*"(\d{8})"')
_SCAN_PDF_RE = re.compile(r'convertBase64InUrlBlob\("([A-Za-z0-9+/=]+)"\)')
_NRO_RE = re.compile(r"(\d{1,5}/\d{4})\s*$")

#: rubro (case-folded) → base type; the DNU refinement keys off norma_tipo.
_RUBRO_TO_TYPE = {
    "leyes": "STATUTE",
    "legislacion": "STATUTE",
    "decretos": "DECREE",
}


def split_norma_id(text: str) -> tuple[str, str]:
    """Split "DECTO-2026-817-APN-PTE - Dispónese…" into (norma_id, rest).

    The id token never contains spaces; when no " - " separator occurs the
    whole string is the id if it is space-free, otherwise it is all rest.
    """
    text = text.strip()
    if " - " in text:
        left, right = text.split(" - ", 1)
        if left and " " not in left:
            return left, right.strip()
        return "", text
    if text and " " not in text:
        return text, ""
    return "", text


def map_doc_type(rubro: str, norma_tipo: str) -> str:
    base = _RUBRO_TO_TYPE.get(rubro.strip().casefold())
    if base is None:
        return "OTHER"
    if base == "DECREE" and norma_tipo.strip().upper() == "DNU":
        return "EMERGENCY_DECREE"
    return base


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html_mod.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def _pub_ymd(publication_date: str) -> str:
    return publication_date.replace("-", "")


class BoraDetalleHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=(
                f"{BASE_URL}/detalleAviso/{task.params['seccion']}/"
                f"{task.params['aviso_id']}/{task.params['fecha']}"
            ),
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Referer": f"{BASE_URL}/busquedaAvanzada/all",
            },
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        seccion = str(task.params["seccion"])
        aviso_id = str(task.params["aviso_id"])
        fecha = str(task.params["fecha"])
        rubro = str(task.params.get("rubro", ""))
        lista_autoridad = str(task.params.get("lista_autoridad", ""))
        lista_nro = str(task.params.get("lista_nro", ""))
        lista_desc = str(task.params.get("lista_desc", ""))

        page = response.content.decode("utf-8", errors="replace")
        pub_m = _PUB_DATE_RE.search(page)
        if pub_m:
            dd, mm, yyyy = pub_m.groups()
            publication_date = f"{yyyy}-{mm}-{dd}"
            fecha_raw = f"{dd}/{mm}/{yyyy}"
        else:
            publication_date = f"{fecha[:4]}-{fecha[4:6]}-{fecha[6:]}"
            fecha_raw = ""

        anexo_calls = _ANEXO_RE.findall(page)
        anexo_files = [f"anexo_{nro}.pdf" for _, nro, _, _ in anexo_calls]
        pub_ymd = _pub_ymd(publication_date)
        anexo_seeds = [
            TaskSeed(
                type="bora_anexo",
                params={
                    "seccion": sec,
                    "nro": nro,
                    "id_anexo": aid,
                    "fecha": fpub,
                    "aviso_id": aviso_id,
                    "pub": pub_ymd,
                },
            )
            for sec, nro, aid, fpub in anexo_calls
        ]

        meta: dict[str, str] = {"aviso_id": aviso_id, "seccion": seccion}
        if rubro:
            meta["rubro"] = rubro
        for key, value in (
            ("lista_autoridad", lista_autoridad),
            ("lista_nro", lista_nro),
            ("lista_desc", lista_desc),
        ):
            if value:
                meta[key] = value
        if fecha_raw:
            meta["fecha_publicacion_raw"] = fecha_raw
        if anexo_calls:
            meta["anexos"] = ";".join(f"{nro}:{aid}" for _, nro, aid, _ in anexo_calls)

        titulo_m = _TITULO_RE.search(page)
        if titulo_m:
            titulo_html = titulo_m.group(1)
            h1_m = _H_RE["h1"].search(titulo_html)
            h2_m = _H_RE["h2"].search(titulo_html)
            h6_m = _H_RE["h6"].search(titulo_html)
            h1 = _clean(h1_m.group(1)) if h1_m else ""
            h2 = _clean(h2_m.group(1)) if h2_m else ""
            h6 = _clean(h6_m.group(1)) if h6_m else ""
            if not (h1 or h2 or h6):
                raise ValueError(f"aviso {aviso_id}: titulo block carries no h1/h2/h6")

            norma_id, descripcion = split_norma_id(h6 or lista_desc)
            cuerpo_m = _CUERPO_END_RE.search(page)
            n_bloques = page.count("<p", cuerpo_m.start(), cuerpo_m.end()) if cuerpo_m else 0
            paginas_m = _PAGINAS_RE.search(page)
            aviso_pdf_m = _AVISO_PDF_RE.search(page)

            issuing = lista_autoridad or h1
            if h1:
                meta["detalle_h1"] = h1
            if h2:
                # norm shape: "Decreto 817/2026 - Dispónese Intervención."
                title = " - ".join(part for part in (h2, descripcion) if part)
            elif h1:
                # notice shape (probed 2026-09-03, run failures archived):
                # AVISOS OFICIALES entries carry only the authority in h1 —
                # no norm reference, no norma id; the listing's kind is the
                # closest thing to a title field.
                title = f"{h1} - {lista_nro}" if lista_nro else h1
            else:
                title = lista_nro or h6 or aviso_id

            if norma_id:
                meta["norma_id"] = norma_id
                meta["norma_tipo"] = norma_id.split("-", 1)[0]
            nro_m = _NRO_RE.search(h2 or lista_nro)
            if nro_m:
                meta["nro_norma"] = nro_m.group(1)
            meta["forma"] = "texto"
            meta["n_bloques"] = str(n_bloques)
            if paginas_m:
                meta["pagina_desde"], meta["pagina_hasta"] = paginas_m.groups()
            if aviso_pdf_m:
                meta["url_pdf"] = f"{BASE_URL}{aviso_pdf_m.group(1)}"

            main_name = "detalle.html"
            main_content = response.content
        else:
            scan_m = _SCAN_PDF_RE.search(page)
            if not scan_m:
                raise ValueError(
                    f"aviso {aviso_id}: neither the text form (tituloDetalleAviso) "
                    "nor the scan shell (convertBase64InUrlBlob) — unknown shape"
                )
            try:
                main_content = base64.b64decode(scan_m.group(1), validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError(
                    f"aviso {aviso_id}: embedded scan PDF is not base64: {exc}"
                ) from exc
            if not main_content.startswith(b"%PDF"):
                raise ValueError(f"aviso {aviso_id}: embedded scan does not start with %PDF")

            norma_id, descripcion = split_norma_id(lista_desc)
            issuing = lista_autoridad
            title = " - ".join(part for part in (lista_nro, descripcion) if part) or aviso_id
            if norma_id:
                meta["norma_id"] = norma_id
                meta["norma_tipo"] = norma_id.split("-", 1)[0]
            nro_m = _NRO_RE.search(lista_nro)
            if nro_m:
                meta["nro_norma"] = nro_m.group(1)
            meta["forma"] = "scan"

            main_name = "aviso.pdf"

        meta["files"] = ";".join([main_name, *anexo_files])
        # Canonical identity keys off the *page's own* publication date, not
        # the listing day it was discovered through: the same aviso can sit in
        # several days' listings (observed 2026-09-03: avisos 346758/346760 in
        # both 2026-08-28's and 2026-08-31's), and the date it reports itself
        # is the one the servable canonical URL uses (probed: …/{pub_ymd}
        # answers 200). One aviso → one source_url → one doc_id; re-entries
        # from other listing days INSERT-OR-IGNORE into the same row and
        # rewrite the same file path with identical bytes.
        source_url = f"{BASE_URL}/detalleAviso/{seccion}/{aviso_id}/{pub_ymd}"
        folder = f"01_raw/bora/{pub_ymd[:4]}/D{pub_ymd}/{aviso_id}"
        document = DocumentRecord(
            title=title,
            source_url=source_url,
            publication_date=publication_date,
            issuing_authority=issuing or None,
            doc_type=map_doc_type(rubro, meta.get("norma_tipo", "")),
            language="spa",
            raw_metadata=meta,
        )
        doc_id = compute_doc_id("ARG", source_url, publication_date)
        files = [FileOut(path=f"{folder}/{main_name}", content=main_content, doc_id=doc_id)]
        return TaskResult(documents=[document], files=files, next_tasks=anexo_seeds)
