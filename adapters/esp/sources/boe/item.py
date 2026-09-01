"""Task type ``boe_item``: one gazette entry, one request, one document.

GET the detail XML (``diario_boe/xml.php?id=…``) — a single response
carrying ``metadatos`` (33 fields), ``metadata-eli`` (ELI RDF),
``analisis`` (materias / notas / referencias / alertas) and ``texto``
(the full text as XHTML-ish markup). The response bytes are stored
verbatim as the primary file; every research field goes to the document
record and its ``meta`` (native values kept losslessly, probed shapes
2026-09-01):

- three dates: fecha_disposicion (adoption) / fecha_publicacion
  (gazette date — the timeline date) / fecha_vigencia (entry into force);
- rango (native type word + code) mapped to the pack's controlled
  doc_type vocabulary, native always preserved;
- referencias carry the raw modification-relation fields
  (``{BOE-A-…}:{MODIFICA|…}``) — graph building is analysis-side work;
- status fields (derogation, consolidation) are the source's *live*
  view; collection semantics = snapshot at fetch time.

Old scan-era entries (e.g. BOE-A-1964-417) carry an empty ``texto`` —
they still register, with ``n_texto_blocks=0`` and the PDF link in meta.
A 404 here is *not* declared as data: the id came from a summary fetched
moments ago, so not-found means something truly broke and must fail loud.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.esp.sources.boe import ACCEPT_XML, API_BASE
from core.document import DocumentRecord, compute_doc_id

__all__ = ["BoeItemHandler", "map_doc_type"]

_DOC_URL = f"{API_BASE}/buscar/doc.php?id="

#: rango codigo -> controlled doc_type (native word always kept in meta;
#: cross-country typology is analysis-side, not collection-side).
_RANGO_TO_TYPE: dict[str, str] = {
    "1070": "CONSTITUTION",
    "1290": "STATUTE",  # Ley Orgánica
    "1300": "STATUTE",  # Ley
    "1320": "DECREE",  # Real Decreto-ley
    "1310": "DECREE",  # Real Decreto Legislativo
    "1340": "DECREE",  # Real Decreto
    "1500": "DECREE",  # Decreto-ley
    "1470": "DECREE",  # Decreto Legislativo
    "1510": "DECREE",  # Decreto
    "1350": "ORDER",  # Orden
    "1540": "ORDER",  # Orden Foral
}


def map_doc_type(rango_codigo: str) -> str:
    return _RANGO_TO_TYPE.get(rango_codigo.strip(), "OTHER")


def _iso(ymd: str) -> str | None:
    """BOE's YYYYMMDD -> ISO, or None for empty/odd values (kept raw in meta)."""
    raw = ymd.strip()
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return None


def _text(element: ET.Element | None) -> str:
    return (element.text or "").strip() if element is not None else ""


class BoeItemHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=f"{API_BASE}/diario_boe/xml.php",
            params={"id": str(task.params["id"])},
            headers=dict(ACCEPT_XML),
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        identificador = str(task.params["id"])
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise ValueError(f"item {identificador}: body is not XML: {exc}") from exc
        if root.tag != "documento":
            raise ValueError(
                f"item {identificador}: unexpected root element {root.tag!r}"
            )

        meta_n = root.find("metadatos")
        if meta_n is None:
            raise ValueError(f"item {identificador}: no metadatos block")

        def get(tag: str) -> str:
            return _text(meta_n.find(tag))  # probed flat shape

        resp_id = get("identificador")
        if resp_id != identificador:
            raise ValueError(
                f"item {identificador}: response describes {resp_id!r} instead"
            )

        fecha_publicacion = get("fecha_publicacion")
        pub_iso = _iso(fecha_publicacion)
        if pub_iso is None:
            raise ValueError(
                f"item {identificador}: no usable fecha_publicacion "
                f"({fecha_publicacion!r})"
            )

        meta: dict[str, str] = {"identificador": resp_id}
        rango_n = meta_n.find("rango")
        rango_codigo = (rango_n.get("codigo") or "").strip() if rango_n is not None else ""
        if rango_n is not None:
            meta["rango"] = _text(rango_n)
        if rango_codigo:
            meta["rango_codigo"] = rango_codigo
        if str(task.params.get("control", "")):
            meta["control"] = str(task.params["control"])

        for key, tag in (
            ("numero_oficial", "numero_oficial"),
            ("fecha_disposicion", "fecha_disposicion"),
            ("fecha_vigencia", "fecha_vigencia"),
            ("diario_numero", "diario_numero"),
            ("seccion", "seccion"),
            ("pagina_inicial", "pagina_inicial"),
            ("pagina_final", "pagina_final"),
            ("url_eli", "url_eli"),
            ("fecha_derogacion", "fecha_derogacion"),
            ("letra_imagen", "letra_imagen"),
        ):
            value = get(tag)
            if value:
                meta[key] = value
        for key in ("fecha_disposicion", "fecha_vigencia"):
            iso = _iso(meta[key]) if key in meta else None
            if iso:
                meta[key] = iso

        origen_n = meta_n.find("origen_legislativo")
        if origen_n is not None and _text(origen_n):
            meta["origen_legislativo"] = _text(origen_n)
        # Origin filter (default estatal): section I occasionally carries
        # regional norms published via BOE (e.g. Comunidad de Madrid leyes —
        # origen_legislativo codigo="2" Autonómico, probed 2026-09-01). The
        # detail is fetched to learn the origin, then kept or explained-away.
        origen_codigo = (origen_n.get("codigo") or "").strip() if origen_n is not None else ""
        scope = str(task.params.get("origen", "estatal"))
        if scope == "estatal" and origen_codigo not in ("", "1"):
            return TaskResult(
                expected_empty=(
                    f"item {identificador}: origin {meta.get('origen_legislativo', '?')} "
                    f"(codigo {origen_codigo}) — regional level, outside the default "
                    "estatal scope (origen=all keeps it)"
                )
            )

        estatus_derogacion = get("estatus_derogacion")
        if estatus_derogacion:
            meta["estatus_derogacion"] = estatus_derogacion
        if get("judicialmente_anulada"):
            meta["judicialmente_anulada"] = get("judicialmente_anulada")
        consolidation_n = meta_n.find("estado_consolidacion")
        if consolidation_n is not None and (consolidation_n.get("codigo") or "").strip():
            meta["estado_consolidacion"] = consolidation_n.get("codigo", "").strip()

        pdf_n = meta_n.find("url_pdf")
        if pdf_n is not None and _text(pdf_n):
            meta["url_pdf"] = _text(pdf_n)
            pdf_bytes = (pdf_n.get("szBytes") or "").strip()
            if pdf_bytes:
                meta["pdf_bytes"] = pdf_bytes
        epub = _text(meta_n.find("url_epub/url_epub")) or _text(meta_n.find("url_epub"))
        if epub:
            meta["url_epub"] = epub

        updated = (root.get("fecha_actualizacion") or "").strip()
        if updated:
            meta["fecha_actualizacion"] = updated

        analisis = root.find("analisis")
        if analisis is not None:
            materias = [(_text(m) or "") for m in analisis.findall("materias/materia")]
            if any(materias):
                meta["materias"] = ";".join(m for m in materias if m)
            alertas = [(_text(a) or "") for a in analisis.findall("alertas/alerta")]
            if any(alertas):
                meta["alertas"] = ";".join(a for a in alertas if a)
            refs: list[str] = []
            for side in ("anteriores/anterior", "posteriores/posterior"):
                for ref_n in analisis.findall(f"referencias/{side}"):
                    ref = (ref_n.get("referencia") or "").strip()
                    palabra = _text(ref_n.find("palabra"))
                    if ref and palabra:
                        refs.append(f"{ref}:{palabra}")
            if refs:
                meta["referencias"] = ";".join(refs)

        texto = root.find("texto")
        meta["n_texto_blocks"] = str(len(list(texto)) if texto is not None else 0)

        ymd = fecha_publicacion  # YYYYMMDD, validated by _iso above
        path = f"01_raw/boe/{ymd[:4]}/D{ymd}/{resp_id}/doc.xml"
        meta["files"] = "doc.xml"

        source_url = f"{_DOC_URL}{resp_id}"
        title = get("titulo") or resp_id
        departamento = get("departamento")

        document = DocumentRecord(
            title=title,
            source_url=source_url,
            publication_date=pub_iso,
            issuing_authority=departamento or None,
            doc_type=map_doc_type(rango_codigo),
            language="spa",
            raw_metadata=meta,
        )
        doc_id = compute_doc_id("ESP", source_url, pub_iso)

        return TaskResult(
            documents=[document],
            files=[FileOut(path=path, content=response.content, doc_id=doc_id)],
        )
