"""Task type ``dre_day``: one calendar day × one série of the gazette.

POST the date-window search (single day, single série, first page size
100) — the portal answers with **issue-level** hits: one gazette issue
per row (a day normally has one issue per série; suplementos appear as
extra issues). Probed shapes (2026-09-17, samples in the task folder):

- a normal day answers ``data.Resultado`` with an embedded elastic
  result; each hit carries dbId, fileId, numero, serie,
  dataPublicacao, dataDisponibilizacao, numPaginas, page range and the
  PDF size;
- a no-edition day (Sundays, holidays) answers the same envelope with
  ``hits.total.value == 0`` — a confirmed "nothing published", recorded
  as an explained empty; the watermark still advances;
- a stale/broken request answers ``HasErrorPesquisa: true`` — never
  treated as data.

Identity: the issue document's canonical portal URL is constructed from
the portal's own key formula ``{numero}-{ano}-{dbId}`` (verified against
the portal's LinkSitemap for issue 180/2026). The whole-issue PDF is the
document's primary file, so every issue gets a ``dre_pdf`` seed.

Pagination guard: the page size is 100, far above any observed day, but
if ``total`` ever exceeds the fetched slice a continuation task is
seeded and the watermark does **not** advance until the last page.
"""

from __future__ import annotations

import json
from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.prt.sources.dre import SEARCH_ACTION, SERVICE_HEADERS, view_name

__all__ = ["DreDayHandler", "build_search_payload"]

_PAGE_SIZE = 100
_CURSOR_PREFIX = "dre_last_date_"


def build_search_payload(
    date_from: str, date_to: str, series: list[str], start: int
) -> dict[str, Any]:
    """The portal search request body, as captured working on 2026-09-17.

    Kept close to the portal's own screen model: unknown extra keys are
    what the portal's UI serialises; removing them made the service
    answer ``HasErrorPesquisa: true``.
    """
    def empty_list() -> dict[str, Any]:
        return {"List": [], "EmptyListItem": ""}

    def empty_hit() -> dict[str, Any]:
        return {
            "index": "", "type": "", "id": "", "score": "0",
            "source": {
                "NumeroInt": "0", "DataPublicacaoAJ": "1900-01-01", "DocType": "",
                "Visibility": "", "Conteudo": False, "Vigencia": "",
                "Title_bst_10k": "", "TextoEntradaVigor": "", "Type": "",
                "TipoAssociacao": {"List": [], "EmptyListItem": ""},
                "NumeroFonte": "", "Descritor": {"List": [], "EmptyListItem": ""},
                "Emissor": "", "Ano": "", "Paginas": "",
            },
        }

    filtros = {
        "tipoConteudo": {"List": ["DiarioRepublica"]},
        "serie": {"List": series},
        "numero": "", "ano": "0", "suplemento": "0",
        "dataPublicacao": "",
        "dataPublicacaoDe": date_from, "dataPublicacaoAte": date_to,
        "parte": "", "apendice": "", "fasciculo": "",
        "tipo": empty_list(), "emissor": empty_list(),
        "entidadeProponente": empty_list(), "entidadePrincipal": empty_list(),
        "entidadeEmitente": empty_list(), "DescritorList": empty_list(),
        "texto": "", "sumario": "", "numeroDR": "", "paginaInicial": "0",
        "paginaFinal": "0", "dataAssinatura": "", "dataDistribuicao": "",
        "pesquisa": "", "anuncio": "", "numeroDoc": "", "empresa": "",
    }
    return {
        "versionInfo": {"moduleVersion": "0", "apiVersion": None},
        "viewName": view_name("pesquisa"),
        "screenData": {
            "variables": {
                "FiltrosDePesquisa": filtros,
                "StartIndex": start,
                "ResultadosPorPaginaId": 2,
                "NumeroDeResultadosPorPagina": _PAGE_SIZE,
                "OcultarRevogados": False,
                "DestaqueExcertos": False,
                "TipoOrdenacaoId": 8,
                "Pesquisa": empty_list(),
                "Texto": "",
                "ResultadosElastic": {
                    "Took": "0", "Timed_out": False,
                    "shards": {"Total": "0", "Successful": "0", "Skipped": "0", "Failed": "0"},
                    "Hits": {
                        "Total": {"Value": "0", "Relation": "", "Max_score": "0"},
                        "Hits": {"List": [], "EmptyListItem": empty_hit()},
                    },
                },
            }
        },
    }


class DreDayHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        day = str(task.params["date"])
        serie = str(task.params["serie"])
        start = int(task.params.get("start", 0))
        tok = dict(task.params.get("tok") or {})
        token = tok.get("DataActionGetPesquisas")
        if not token:
            raise ValueError(
                f"dre_day {day}/{serie}: no DataActionGetPesquisas token in task "
                "params — re-run so the dre_version bootstrap refreshes tokens"
            )
        payload = build_search_payload(day, day, [serie], start)
        payload["versionInfo"]["apiVersion"] = token
        return RequestSpec(
            url=f"{SERVICE_HEADERS['Origin']}{_service_path(SEARCH_ACTION)}",
            method="POST",
            headers=dict(SERVICE_HEADERS),
            json_body=payload,
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        day = str(task.params["date"])
        serie = str(task.params["serie"])
        start = int(task.params.get("start", 0))
        cursor_key = f"{_CURSOR_PREFIX}{serie}"

        try:
            envelope = response.json()
        except ValueError as exc:
            raise ValueError(f"dre_day {day}/{serie}: body is not JSON: {exc}") from exc
        data = envelope.get("data")
        if not isinstance(data, dict):
            raise TypeError(f"dre_day {day}/{serie}: unexpected envelope shape")

        if data.get("HasErrorPesquisa"):
            raise ValueError(
                f"dre_day {day}/{serie}: the search service reported an error "
                "(HasErrorPesquisa) — the request shape or its tokens are stale"
            )
        resultado = data.get("Resultado") or ""
        if not resultado:
            raise ValueError(
                f"dre_day {day}/{serie}: empty Resultado without the error flag — "
                "unknown response shape, failing loud"
            )
        elastic = json.loads(resultado)
        hits = elastic.get("hits", {}).get("hits", [])
        total = int(elastic.get("hits", {}).get("total", {}).get("value", 0))

        seeds: list[TaskSeed] = []
        documents: list[Any] = []
        from core.document import DocumentRecord, compute_doc_id

        for hit in hits:
            source = hit.get("_source") or {}
            db_id = str(source.get("dbId") or "").strip()
            file_id = str(source.get("fileId") or "").strip()
            numero = str(source.get("numero") or "").strip()
            pub = str(source.get("dataPublicacao") or "").strip()
            hit_serie = str(source.get("serie") or "").strip()
            title = str(source.get("title") or "").strip()
            if not (db_id and file_id and numero and pub and hit_serie and title):
                raise ValueError(
                    f"dre_day {day}/{serie}: a hit is missing required fields "
                    f"(dbId={db_id!r} fileId={file_id!r} numero={numero!r} "
                    f"dataPublicacao={pub!r} serie={hit_serie!r})"
                )
            year = pub[:4]
            key = f"{numero}-{year}-{db_id}"
            source_url = (
                "https://diariodarepublica.pt/dr/detalhe/diario-republica/" + key
            )
            meta: dict[str, str] = {
                "level": "issue",
                "key": key,
                "db_id": db_id,
                "file_id": file_id,
                "numero_dr": numero,
                "serie": hit_serie,
                "doc_type_native": str(source.get("tipoConteudo") or ""),
                "url_pdf": f"https://dre.pt/application/file/{file_id}",
                "files": "issue.pdf",
            }
            for src_key, meta_key in (
                ("suplemento", "suplemento"),
                ("numPaginas", "num_paginas"),
                ("paginaInicial", "pagina_inicial"),
                ("paginaFinal", "pagina_final"),
                ("tamanhoFicheiro", "tamanho_ficheiro"),
                ("dataDisponibilizacao", "data_disponibilizacao"),
                ("serieNR", "serie_nr"),
            ):
                value = str(source.get(src_key) or "").strip()
                if value:
                    meta[meta_key] = value
            document = DocumentRecord(
                title=title,
                source_url=source_url,
                publication_date=pub,
                issuing_authority="INCM",
                doc_type="OTHER",
                language="por",
                raw_metadata=meta,
            )
            doc_id = compute_doc_id("PRT", source_url, pub)
            documents.append(document)
            path = f"01_raw/dre/{year}/D{pub.replace('-', '')}/{db_id}_s{hit_serie}/issue.pdf"
            seeds.append(
                TaskSeed(
                    type="dre_pdf",
                    params={
                        "file_id": file_id,
                        "path": path,
                        "doc_id": doc_id,
                        "date": day,
                    },
                )
            )

        if total > start + len(hits):
            seeds.append(
                TaskSeed(
                    type="dre_day",
                    params={
                        "date": day,
                        "serie": serie,
                        "start": start + len(hits),
                        "tok": dict(task.params.get("tok") or {}),
                    },
                )
            )
            return TaskResult(
                documents=documents,
                next_tasks=seeds,
                expected_empty=(
                    f"{day}/{serie}: page of {len(hits)} of {total} issues — "
                    "continuation seeded, watermark not advanced yet"
                ),
            )

        explained = (
            f"DRE has no {serie}ª-série issue on {day} "
            f"(search answers total=0)" if not hits else None
        )
        result = TaskResult(documents=documents, next_tasks=seeds)
        if explained:
            result.expected_empty = explained
        result.cursor_updates = {cursor_key: day}
        return result


def _service_path(action: str) -> str:
    return f"/dr/screenservices/{action}"
