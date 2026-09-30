"""Task type ``chl_body``: one version's full text plus 31-field metadata.

``get_norma_json`` returns one JSON envelope per version (probed 2026-09-20,
identical shape for Texto Original / Intermedio / Última Versión / Única,
from an 1880 treaty to a 2024 decree)::

    {"metadatos": {"id_norma": "1209817", "titulo_norma": "…",
                   "tipos_numeros": "[{'tipo': '2', 'numero': '297 EXENTO',
                                      'abreviacion': 'DTO', …}]",
                   "organismos": "['MINISTERIO DE ENERGÍA']",
                   "fecha_promulgacion": "2024-12-30",       <- ISO
                   "fecha_publicacion": "2024-12-31",        <- ISO
                   "vigencia": "{'inicio_vigencia': '2024-12-31', 'fin_vigencia': ''}",
                   "fuente": "Diario Oficial", "numero_fuente": "44037", …},
     "estructura": [ {"n": "Encabezado", "i": …}, … ],
     "html": [ {"i": …, "t": "<div>…</div>"}, … ],            <- body text
     …}

Some fields hold Python-repr *strings* (single-quoted lists/dicts) —
``ast.literal_eval`` unpacks them. ``idVersion`` in the request accepts
the numeric version id or the version's vigencia date; the timeline only
exposes dates, so the canonical URL always uses the date form.

The raw artifact is the API envelope itself (json) — source shape kept,
stitching the html fragments is a cleaning-stage transform, not
collection. Historical versions (spawned by ``chl_versions``,
``from_versions=1``) never re-spawn the timeline: they were born inside
one.
"""

from __future__ import annotations

import ast
import re
from typing import Any

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.chl.sources.leychile import API_BASE, canonical_norma_url, map_doc_type
from core.document import DocumentRecord, compute_doc_id

__all__ = ["ChlBodyHandler", "norma_folder"]

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def norma_folder(id_norma: str, vigente_desde: str) -> str:
    """Raw-folder path below the country root, e.g.
    ``01_raw/leychile/29/29708/norma_29708_2009-11-07.json``'s folder."""
    return f"01_raw/leychile/{id_norma[:2]}/{id_norma}"


def _literal(value: Any) -> Any:
    """Unpack the Python-repr string fields (probed shape) or pass through."""
    if isinstance(value, str) and value[:1] in ("[", "{"):
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return value
    return value


class ChlBodyHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=f"{API_BASE}/Navegar/get_norma_json",
            params={
                "idNorma": str(task.params["id_norma"]),
                "idVersion": str(task.params["id_version"]),
                "idLey": "",
                "tipoVersion": str(task.params.get("tipo_version", "")),
                "cve": "",
                "agrupa_partes": "1",
                "r": "",
            },
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = dict(task.params)
        id_norma = str(params["id_norma"])
        if response.status_code != 200:
            raise ValueError(f"body of norma {id_norma} returned HTTP {response.status_code}")

        data: Any = response.json()
        if not isinstance(data, dict) or "metadatos" not in data or "html" not in data:
            raise ValueError(f"body of norma {id_norma} is not the probed envelope shape")
        meta_in: dict[str, Any] = data["metadatos"]
        if not data["html"]:
            raise ValueError(f"body of norma {id_norma} carries no html parts")

        if str(meta_in.get("id_norma", "")) != id_norma:
            raise ValueError(
                f"body of norma {id_norma} answers for id_norma={meta_in.get('id_norma')!r}"
            )

        publication_date = str(meta_in.get("fecha_publicacion", "")).strip()
        if not _DATE_RE.fullmatch(publication_date):
            raise ValueError(f"body of norma {id_norma} carries no ISO fecha_publicacion")

        vigencia = _literal(meta_in.get("vigencia", {}))
        vigente_desde = ""
        vigente_hasta = ""
        if isinstance(vigencia, dict):
            vigente_desde = str(vigencia.get("inicio_vigencia", "") or "")
            vigente_hasta = str(vigencia.get("fin_vigencia", "") or "")
        if not vigente_desde and _DATE_RE.fullmatch(str(params.get("id_version", ""))):
            vigente_desde = str(params["id_version"])
        if not vigente_desde:
            raise ValueError(f"body of norma {id_norma} carries no vigencia start date")

        tipos = _literal(meta_in.get("tipos_numeros", "[]"))
        first_type: dict[str, Any] = {}
        compuesto = ""
        if isinstance(tipos, list) and tipos and isinstance(tipos[0], dict):
            first_type = tipos[0]
            compuesto = str(first_type.get("compuesto", "") or "")
        abbr = str(first_type.get("abreviacion", "") or "")

        organismos = _literal(meta_in.get("organismos", "[]"))
        authority = ""
        if isinstance(organismos, list) and organismos:
            authority = str(organismos[0])

        title = str(meta_in.get("titulo_norma", "") or "").strip() or compuesto or f"Norma {id_norma}"

        raw_metadata: dict[str, str] = {
            "id_norma": id_norma,
            "id_version": str(params["id_version"]),
            "vigente_desde": vigente_desde,
            "tipo_version_s": str(meta_in.get("tipo_version_s", "") or ""),
            "fecha_promulgacion": str(meta_in.get("fecha_promulgacion", "") or ""),
            "numero_fuente": str(meta_in.get("numero_fuente", "") or ""),
            "fuente": str(meta_in.get("fuente", "") or ""),
            "derogado": str(meta_in.get("derogado", "") or ""),
            "fecha_version": str(meta_in.get("fecha_version", "") or ""),
        }
        if vigente_hasta:
            raw_metadata["vigente_hasta"] = vigente_hasta
        if authority:
            raw_metadata["organismos"] = str(meta_in.get("organismos", "") or "")
        if abbr:
            raw_metadata["type_abbr"] = abbr
        if params.get("from_versions"):
            raw_metadata["from_versions"] = "1"

        source_url = canonical_norma_url(id_norma, vigente_desde)
        record = DocumentRecord(
            title=title,
            source_url=source_url,
            publication_date=publication_date,
            issuing_authority=authority or None,
            doc_type=map_doc_type(abbr),
            entity_ref=f"normas:{id_norma}",
            language="spa",
            raw_metadata=raw_metadata,
        )
        doc_id = compute_doc_id("CHL", source_url, publication_date)

        # An anchor of an amended norma spawns the timeline (once per
        # norma); 'Única' rows (tipo_version '3') never do — their
        # timeline is exactly the fetched version (probed). Unknown
        # tipo_version values spawn defensively (one extra request, no
        # correctness risk). Historical bodies were born inside a
        # timeline and never re-spawn it.
        next_tasks: list[TaskSeed] = []
        if not params.get("from_versions") and str(params.get("tipo_version", "")) != "3":
            next_tasks.append(TaskSeed(type="chl_versions", params={"id_norma": id_norma}))

        return TaskResult(
            documents=[record],
            files=[
                FileOut(
                    path=f"{norma_folder(id_norma, vigente_desde)}/norma_{id_norma}_{vigente_desde}.json",
                    content=response.content,
                    doc_id=doc_id,
                )
            ],
            next_tasks=next_tasks,
        )
