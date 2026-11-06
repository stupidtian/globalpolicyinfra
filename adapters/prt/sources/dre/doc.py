"""Task type ``dre_doc``: one targeted diploma, one request, one document.

POST the detail service with ``Tipo`` (lowercase portal type word, e.g.
``lei``) and ``Key`` (``{numero}-{ano}-{dbId}``) — a single response
carrying the full record: title, official number, the four native dates
(publication / distribution / made-available / signature, sentinel
1900-01-01 when absent), issuing body, série, suplemento, processo,
*current* validity (Vigencia), the plain-text full text (Texto), the
HTML rendering (TextoFormatado), the direct PDF link, ELI and notes.
The response bytes are stored verbatim as the primary file ``doc.json``;
every research field goes to the document record and its ``meta``
(probed shapes 2026-09-17: Despacho n.º 1348/2026, Lei n.º 62/2026).

The same service answers issue-level records for ``Tipo=
diario-republica`` — supported here as well (doc_type OTHER, level=issue
in meta), useful for targeted issue metadata.

Seeded only from the ``doc=tipo/key,...`` CLI parameter (the per-day
single-diploma listing channel is browser-session-gated at the source —
see docs §1.4). A bad key answers an empty DetalheConteudo: that is a
caller error and dies loud, it is not an explained empty.
"""

from __future__ import annotations

import unicodedata

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.prt.sources.dre import DETAIL_ACTION, SERVICE_HEADERS, view_name
from core.document import DocumentRecord, compute_doc_id

__all__ = ["DreDocHandler", "map_doc_type"]

#: Native TipoDiploma word -> controlled doc_type. The native word always
#: travels in meta; cross-country typology is analysis-side.
_TIPO_TO_TYPE: dict[str, str] = {
    "lei": "STATUTE",
    "lei organica": "STATUTE",
    "decreto-lei": "DECREE",
    "decreto": "DECREE",
    "decreto regulamentar": "DECREE",
    "portaria": "SECONDARY_LEGISLATION",
    "despacho regulamentar": "SECONDARY_LEGISLATION",
}

_SENTINEL = "1900-01-01"


def _norm(tipo: str) -> str:
    """Lowercase and strip accents ('Lei Orgânica' -> 'lei organica')."""
    decomposed = unicodedata.normalize("NFD", tipo.strip().lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def map_doc_type(tipo_diploma: str) -> str:
    return _TIPO_TO_TYPE.get(_norm(tipo_diploma), "OTHER")


class DreDocHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        tipo = str(task.params["tipo"])
        key = str(task.params["key"])
        tok = dict(task.params.get("tok") or {})
        token = tok.get("DataActionGetAllConteudoDetalheData")
        if not token:
            raise ValueError(
                f"dre_doc {tipo}/{key}: no DataActionGetAllConteudoDetalheData "
                "token in task params — re-run so the bootstrap refreshes tokens"
            )
        payload = {
            "versionInfo": {"moduleVersion": "0", "apiVersion": token},
            "viewName": view_name("detalhe"),
            "screenData": {"variables": {"Tipo": tipo, "Key": key}},
        }
        return RequestSpec(
            url=f"{SERVICE_HEADERS['Origin']}/dr/screenservices/{DETAIL_ACTION}",
            method="POST",
            headers=dict(SERVICE_HEADERS),
            json_body=payload,
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        tipo = str(task.params["tipo"])
        key = str(task.params["key"])
        try:
            envelope = response.json()
        except ValueError as exc:
            raise ValueError(f"dre_doc {tipo}/{key}: body is not JSON: {exc}") from exc
        data = envelope.get("data")
        if not isinstance(data, dict):
            raise TypeError(f"dre_doc {tipo}/{key}: unexpected envelope shape")
        detail = data.get("DetalheConteudo")
        if not isinstance(detail, dict) or not str(detail.get("Titulo") or "").strip():
            raise ValueError(
                f"dre_doc {tipo}/{key}: the portal answers an empty record — "
                "key not found (tipo/key are the two segments of the portal's "
                "own /dr/detalhe/{tipo}/{key} URL)"
            )

        def field(name: str) -> str:
            return str(detail.get(name) or "").strip()

        pub = field("DataPublicacao")
        pub_iso = pub if pub and pub != _SENTINEL else None
        db_id = field("Id") or str(data.get("KeyConteudoId") or "").strip()

        meta: dict[str, str] = {
            "key": key,
            "tipo_url": tipo,
            "db_id": db_id,
            "tipo_conteudo": field("TipoConteudo"),
            "files": "doc.json",
        }
        if data.get("ElementType"):
            meta["element_type"] = str(data["ElementType"])
        for src_key, meta_key in (
            ("TipoDiploma", "tipo_diploma"),
            ("TipoDiplomaAcronimo", "tipo_diploma_acronimo"),
            ("Numero", "numero_oficial"),
            ("DataAssinatura", "data_assinatura"),
            ("DataDistribuicao", "data_distribuicao"),
            ("DataDisponibilizacao", "data_disponibilizacao"),
            ("EmissorAcronimo", "emissor_acronimo"),
            ("Serie", "serie"),
            ("Suplemento", "suplemento"),
            ("Parte", "parte"),
            ("Processo", "processo"),
            ("Vigencia", "vigencia"),
            ("URL_PDF", "url_pdf"),
            ("ELI", "elis"),
            ("Notas", "notas"),
            ("Pagina", "pagina"),
            ("LinkSitemap", "link_sitemap"),
        ):
            value = field(src_key)
            if value and value != _SENTINEL:
                meta[meta_key] = value
        if field("DataAssinatura") == _SENTINEL:
            meta["data_assinatura"] = _SENTINEL
        if field("DataDistribuicao") == _SENTINEL:
            meta["data_distribuicao"] = _SENTINEL
        if field("DataDisponibilizacao") == _SENTINEL:
            meta["data_disponibilizacao"] = _SENTINEL
        meta["texto_len"] = str(len(field("Texto")))
        meta["texto_formatado_len"] = str(len(field("TextoFormatado")))
        is_issue = meta.get("tipo_conteudo", "") == "DiarioRepublica"
        meta["level"] = "issue" if is_issue else "diploma"
        if detail.get("DiarioRepublica"):
            dr = detail["DiarioRepublica"]
            if isinstance(dr, dict):
                for src_key, meta_key in (
                    ("NumPaginas_PDF", "num_paginas"),
                    ("Tamanho_PDF", "tamanho_pdf"),
                ):
                    value = str(dr.get(src_key) or "").strip()
                    if value:
                        meta[meta_key] = value

        if is_issue:
            doc_type = "OTHER"
        else:
            doc_type = map_doc_type(meta.get("tipo_diploma", ""))
            if doc_type == "OTHER" and not meta.get("tipo_diploma"):
                raise ValueError(
                    f"dre_doc {tipo}/{key}: no native TipoDiploma — refusing to "
                    "guess a doc_type (native word missing)"
                )

        # Directory partition: publication date, or "nodate" when the
        # portal carries only the sentinel.
        if pub_iso:
            ymd = pub_iso.replace("-", "")
            dir_prefix = f"{ymd[:4]}/D{ymd}"
        else:
            dir_prefix = "nodate"
        path = f"01_raw/dre/{dir_prefix}/{db_id}_{tipo}/doc.json"

        document = DocumentRecord(
            title=field("Titulo"),
            source_url=f"https://diariodarepublica.pt/dr/detalhe/{tipo}/{key}",
            publication_date=pub_iso,
            issuing_authority=field("Emissor") or None,
            doc_type=doc_type,
            language="por",
            raw_metadata=meta,
        )
        doc_id = compute_doc_id("PRT", document.source_url, pub_iso)

        return TaskResult(
            documents=[document],
            files=[FileOut(path=path, content=response.content, doc_id=doc_id)],
        )
