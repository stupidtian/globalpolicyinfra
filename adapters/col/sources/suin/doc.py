"""Task type ``suin_doc``: one norm, one request, one document.

GET the document API (``/suin-search/api/documentos/{id}``) — a single
key-free response whose ``data.textoHtml`` is the whole current
consolidated text as HTML (the Código Civil runs to megabytes; ordinary
decrees land at tens to hundreds of kilobytes). The response's HTML goes
to disk verbatim as the primary file; bibliographic fields come from two
probed places (2026-10-19):

- the enumeration hit, carried in task params (fecha / titulo / tipo /
  numero / anio / entidad / estado / DO issue and page / documentofuente
  …) — the API response itself does *not* echo these;
- the API response (``data``: textoHtml, vigencia, entidadEmisora,
  epigrafe, legacy url, updateTimestamp, …), which also re-identifies
  the norm (``data.id`` must match the request id).

Production shapes (both probed live):

- **HTTP 204 with an empty body**: the metadata is already indexed but
  the text is not loaded yet (fresh norms answer this for days). The
  transport contract hands only 200 (plus declared 404/410) to parse,
  so 203-style leniency is not expressible here — the transport raises
  ``PermanentError("HTTP 204 …")`` and the task lands as
  ``failed_permanent`` with that exact message. That is the recorded
  story (plan §9 Q5 deviation): a later refresh re-walk re-emits the
  same task tuple and ``requeue --type suin_doc`` picks it up once the
  text is loaded. The shape is reported as a framework-gap candidate
  ("legitimate empty 204" → accept_not_found-family extension).
- The API's ``success`` flag and ``data`` object: anything else under a
  200 is an unknown shape and fails loud.
"""

from __future__ import annotations

from typing import Any

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.col.sources.suin import DOC_API_URL
from core.document import DocumentRecord, compute_doc_id

__all__ = ["SuinDocHandler"]


def _meta_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    return str(value) if value is not None and str(value).strip() else ""


class SuinDocHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=f"{DOC_API_URL}/{task.params['id']}")

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        norm_id = str(task.params["id"])
        found_on = str(task.params["found_on"])

        if response.status_code != 200:
            # The transport already classified non-200 as transient or
            # permanent (a 204 lands in failed_permanent before this
            # runs); anything reaching parse under another code is an
            # unknown shape and fails loud.
            raise ValueError(f"norm {norm_id}: document API answered HTTP {response.status_code}")

        payload = response.json()
        data = payload.get("data")
        if payload.get("success") is not True or not isinstance(data, dict):
            raise ValueError(
                f"norm {norm_id}: unexpected document API shape "
                f"(success={payload.get('success')!r}, data type={type(data).__name__})"
            )
        if str(data.get("id", "")).strip() != norm_id:
            raise ValueError(
                f"norm {norm_id}: response describes {data.get('id')!r} instead"
            )
        texto = data.get("textoHtml")
        if not isinstance(texto, str) or not texto.strip():
            raise ValueError(f"norm {norm_id}: 200 response carries no textoHtml")

        meta: dict[str, str] = {"suin_id": norm_id}
        for key in (
            "fecha",
            "titulo",
            "tipo",
            "subtipo",
            "numero",
            "anio",
            "entidad",
            "estado",
            "numero_diario",
            "pagina_diario",
            "documentofuente",
            "materia",
            "sector",
            "noart",
        ):
            value = _meta_str(task.params, key)
            if value:
                meta[key] = value
        for key, source_key in (
            ("vigencia", "vigencia"),
            ("entidad_emisora", "entidadEmisora"),
            ("epigrafe", "epigrafe"),
            ("nombre_comun", "nombreComun"),
            ("sector_api", "sector"),
            ("materia_api", "materia"),
            ("subtipo_api", "subtipo"),
            ("legacy_url", "url"),
            ("collection_id", "collectionId"),
        ):
            raw_value = data.get(source_key)
            if raw_value is not None and str(raw_value).strip():
                meta[key] = str(raw_value)
        update_ts = data.get("updateTimestamp")
        if update_ts is not None:
            meta["update_timestamp"] = str(update_ts)
        meta["viewer_url"] = f"https://lexis.minjusticia.gov.co/minjusticia/viewDocument/{norm_id}"

        fecha = meta.get("fecha", "")
        publication_date = fecha[:10] if fecha else None
        if publication_date is not None and len(publication_date) != 10:
            publication_date = None  # keep the raw string in meta, no guessing

        source_url = f"{DOC_API_URL}/{norm_id}"
        title = meta.get("titulo") or meta.get("epigrafe") or f"SUIN {norm_id}"

        meta["files"] = "doc.html"
        document = DocumentRecord(
            title=title,
            source_url=source_url,
            publication_date=publication_date,
            issuing_authority=meta.get("entidad") or meta.get("entidad_emisora") or None,
            doc_type=map_doc_type(meta.get("tipo", "")),
            language="spa",
            raw_metadata=meta,
        )
        doc_id = compute_doc_id("COL", source_url, publication_date)

        path = f"01_raw/suin/{found_on[:4]}/D{found_on.replace('-', '')}/{norm_id}/doc.html"
        return TaskResult(
            documents=[document],
            files=[FileOut(path=path, content=texto.encode("utf-8"), doc_id=doc_id)],
        )


_DOC_TYPE_MAP: dict[str, str] = {
    "CONSTITUCION POLITICA": "CONSTITUTION",
    "ACTO LEGISLATIVO": "STATUTE",
    "LEY": "STATUTE",
    "CODIGO": "STATUTE",
    "DECRETO": "DECREE",
    "RESOLUCION": "RESOLUTION",
    "RESOLUCION EXTERNA": "RESOLUTION",
    "CIRCULAR": "CIRCULAR",
    "CIRCULAR EXTERNA": "CIRCULAR",
    "CIRCULAR CONJUNTA": "CIRCULAR",
    "ACUERDO": "AGREEMENT",
    "DIRECTIVA PRESIDENCIAL": "ORDER",
    "DIRECTIVA VICEPRESIDENCIAL": "ORDER",
    "DIRECTIVA MINISTERIAL": "ORDER",
    "INSTRUCCION": "ORDER",
    "INSTRUCCION ADMINISTRATIVA CONJUNTA": "ORDER",
}


def map_doc_type(tipo: str) -> str:
    """Native tipo -> controlled vocabulary (native word always kept in
    meta; unmapped shapes answer OTHER, never a guess)."""
    return _DOC_TYPE_MAP.get(tipo.strip().upper(), "OTHER")
