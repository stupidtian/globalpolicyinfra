"""Task type ``dou_artigo``: one gazette entry, one request, one document.

GET the detail page ``/web/dou/-/{urlTitle}`` — server-rendered HTML
(UTF-8, 125–404 KB probed) whose ``<article id="materia">`` container
carries the entry's bibliographic set and the full as-published text in
``p.dou-paragraph`` blocks (116 paragraphs on a 2026 portaria; 1,556 on
Lei 14.133/2021). The response bytes are stored gzip-compressed as the
primary ``doc.html.gz`` (the LVA/vestnesis pattern — the page is ~60%
repeated portal chrome and HTML gzips ~6-8x; ``local_doc`` decompresses
automatically when cleaning arrives; the checksum is over the stored
compressed bytes, and gunzip reproduces the source page byte for byte).
Every research field goes to the document record and its ``meta``
(native values kept losslessly, probed shapes 2026-10-02):

- ``publicado-dou-data`` (DD/MM/YYYY) is the gazette date — it must
  equal the enumeration row's ``pub_date`` (the seed came from that
  day's page minutes earlier, so a mismatch means a shape change or a
  mid-migration source and dies loud);
- ``edicao-dou-data`` is the edition number (regular ``187``, extra
  ``61-F``); ``orgao-dou-data`` repeats the issuing-agency hierarchy;
- ``p.identifica`` is the formal title — it wins over the enumeration
  row's ``title`` whenever both exist, and a differing row title is
  preserved in ``meta.list_title`` rather than hidden;
- the visualiza link's query (jornal/pagina/data) is the *layout-PDF*
  fetch recipe; it is recorded in meta so the typeset page can be
  fetched later without re-enumeration (the layout PDF itself is not
  collected — the HTML carries the full text).

A 404 here is *not* declared as data: the urlTitle came from a reading
page fetched minutes ago, so not-found means something truly broke and
must fail loud.
"""

from __future__ import annotations

import gzip
import re

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.bra.sources.dou import BASE_URL
from adapters.bra.sources.dou.leitura import norm_art_type
from core.document import DocumentRecord, compute_doc_id

__all__ = ["DouArtigoHandler", "map_doc_type"]

_ARTICLE_MARK = '<article id="materia"'
_VISUALIZA_RE = re.compile(
    r'href="(https?://pesquisa\.in\.gov\.br/imprensa/jsp/visualiza/index\.jsp\?[^"]+)"'
)
_VISUALIZA_QUERY_RE = re.compile(
    r"data=(?P<data>\d{2}/\d{2}/\d{4})&(?:amp;)?jornal=(?P<jornal>\d+)&(?:amp;)?pagina=(?P<pagina>\d+)"
)
_DMY_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
_WS_RE = re.compile(r"\s+")


def map_doc_type(art_type: str) -> str:
    """Native artType word -> controlled doc_type (add-only mapping).

    The native word always travels in meta ``art_type``; cross-country
    typology is analysis-side, not collection-side. Unknown words fall
    to OTHER and keep their evidence in meta.
    """
    norm = norm_art_type(art_type)
    if not norm:
        return "OTHER"
    if norm.startswith(("lei", "medida provisor", "emenda constitucional")):
        return "STATUTE"
    if norm.startswith("decreto"):
        return "DECREE"
    if norm.startswith(
        ("portaria", "resolucao", "instrucao normativa", "ato normativo", "circular", "ordem de servico")
    ):
        return "ORDER"
    if norm.startswith(("retificacao", "retificacoes")):
        return "RETIFICATION"
    return "OTHER"


def _span(container: str, cls: str) -> str:
    m = re.search(rf'<span class="[^"]*\b{cls}\b[^"]*"[^>]*>(.*?)</span>', container, re.DOTALL)
    return _strip(m.group(1)) if m else ""


def _paras(container: str, cls: str) -> list[str]:
    return [
        _strip(m.group(1))
        for m in re.finditer(rf'<p class="[^"]*\b{cls}\b[^"]*"[^>]*>(.*?)</p>', container, re.DOTALL)
    ]


def _strip(fragment: str) -> str:
    return _WS_RE.sub(" ", re.sub(r"<[^>]+>", " ", fragment)).strip()


def _dmy_to_iso(raw: str) -> str | None:
    m = _DMY_RE.fullmatch(raw.strip())
    if not m:
        return None
    d, mo, y = m.group(1), m.group(2), m.group(3)
    return f"{y}-{mo}-{d}"


class DouArtigoHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        url_title = str(task.params["url_title"])
        return RequestSpec(url=f"{BASE_URL}/web/dou/-/{url_title}")

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        url_title = str(task.params["url_title"])
        html = response.content.decode("utf-8", errors="replace")

        start = html.find(_ARTICLE_MARK)
        if start < 0:
            raise ValueError(
                f"artigo {url_title}: no <article id=\"materia\"> container "
                f"(HTTP {response.status_code}, {len(response.content)} bytes) — shape changed"
            )
        end = html.find("</article>", start)
        if end < 0:
            raise ValueError(f"artigo {url_title}: article container never closes")
        body = html[start:end]

        published_raw = _span(body, "publicado-dou-data")
        pub_iso = _dmy_to_iso(published_raw)
        if pub_iso is None:
            raise ValueError(
                f"artigo {url_title}: no usable publicado-dou-data ({published_raw!r})"
            )
        seed_date = str(task.params.get("pub_date", ""))
        if _dmy_to_iso(seed_date) != pub_iso:
            raise ValueError(
                f"artigo {url_title}: detail page dated {published_raw!r} but the "
                f"enumeration row said {seed_date!r} — stale row or shape change"
            )

        title = _paras(body, "identifica")
        title_text = title[0] if title else str(task.params.get("title") or "") or url_title

        meta: dict[str, str] = {"url_title": url_title}
        pub_name = str(task.params.get("pub_name", ""))
        if pub_name:
            meta["pub_name"] = pub_name
        if published_raw:
            meta["pub_date_raw"] = published_raw
        edicao = _span(body, "edicao-dou-data") or str(task.params.get("edition_number", ""))
        if edicao:
            meta["edicao"] = edicao
        art_type = str(task.params.get("art_type", ""))
        if art_type:
            meta["art_type"] = art_type
        number_page = _span(body, "secao-dou-data") or str(task.params.get("number_page", ""))
        if number_page:
            meta["number_page"] = number_page
        for key in ("hierarchy_str", "hierarchy_level_size", "pub_order", "sub_titulo"):
            value = str(task.params.get(key, ""))
            if value:
                meta[key] = value
        orgao = _span(body, "orgao-dou-data")
        if orgao:
            meta["orgao"] = orgao
        ementas = _paras(body, "ementa")
        if ementas:
            meta["ementa"] = "\n".join(ementas)
        assinaturas = _paras(body, "assina")
        if assinaturas:
            meta["assinou"] = "; ".join(assinaturas)
        cargos = _paras(body, "cargo")
        if cargos:
            meta["cargo"] = "; ".join(cargos)
        meta["n_paragraphs"] = str(len(_paras(body, "dou-paragraph")))

        list_title = str(task.params.get("title", ""))
        if title and list_title and list_title != title[0]:
            meta["list_title"] = list_title

        # The visualiza link lives in the page toolbar, *outside* the
        # <article> container — search the whole page for it.
        visualiza = _VISUALIZA_RE.search(html)
        if visualiza:
            query = _VISUALIZA_QUERY_RE.search(visualiza.group(1))
            if query:
                meta["visualiza_data"] = query.group("data")
                meta["jornal"] = query.group("jornal")
                meta["pagina"] = query.group("pagina")

        issuing_authority = str(task.params.get("hierarchy_str", "")) or orgao or None
        source_url = f"{BASE_URL}/web/dou/-/{url_title}"
        document = DocumentRecord(
            title=title_text,
            source_url=source_url,
            publication_date=pub_iso,
            issuing_authority=issuing_authority,
            doc_type=map_doc_type(art_type),
            language="por",
            raw_metadata=meta,
        )
        doc_id = compute_doc_id("BRA", source_url, pub_iso)

        pub_name_safe = re.sub(r"[^A-Za-z0-9_]", "_", pub_name) or "x"
        tail = re.sub(r"[^A-Za-z0-9]", "", url_title.rsplit("-", 1)[-1]) or "x"
        path = f"01_raw/dou/{pub_iso[:4]}/D{pub_iso.replace('-', '')}/{pub_name_safe}/{tail}/doc.html.gz"

        return TaskResult(
            documents=[document],
            files=[FileOut(path=path, content=gzip.compress(response.content, 9), doc_id=doc_id)],
        )
