"""Task type ``dof_index``: one (calendar day, edición) pair of the gazette.

GET the date-addressed edition page ``index.php?year&month&day&edicion``
(the site's own edition-switcher link shape, probed 2026-09-14) and turn
every canonical listing row into a ``dof_nota`` seed. Probed shapes that
shape this handler:

- The page always answers HTTP 200. Its own header line
  ``Fecha: DD/MM/YYYY - Edición Matutina|Vespertina`` is the anchor:
  when it is absent the (day, edición) pair has no edition (weekends,
  holidays, editions the day never got — probed shapes in the task
  folder); when it disagrees with the request the site fell back to
  some other content and the parse refuses to collect — 宁可信其无.
- Listing rows are ``<a href="/nota_detalle.php?codigo=…&fecha=…"
  class="enlaces">`` anchors; every row's ``fecha`` must equal the
  header date or the shape is refused. The page also carries visit-
  tracking ``enlaces_leido`` twins whose ``fecha`` year is bogus
  (1926 on a 2026 page, probed) — excluded by the exact class token,
  never treated as rows.
- Row context (document order): section banner ``txt_blanco`` (e.g.
  ``UNICA SECCION`` / ``SECCION PRIMERA``), organism banner
  ``txt_blanco2`` (e.g. ``PODER EJECUTIVO``), department
  ``subtitle_azul`` (e.g. ``PRESIDENCIA DE LA REPUBLICA``). The bytes
  are ISO-8859-1; decoded before parsing.
- Scope (``tipos`` in the task params, resolved by ``start_tasks``):
  the gazette's own native type word — the first title token, checked
  past ordinals ("Segundo Convenio…" is a CONVENIO) and accent-free
  ("Resolución…" matches RESOLUCION). Rows outside the set are not
  seeded; a day whose rows are all out of scope is an explained empty
  that still advances the watermark. No ``tipos`` = everything.
"""

from __future__ import annotations

import html as html_mod
import re
import unicodedata

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.mex.sources.dof import BASE_URL, cursor_key

__all__ = ["DofIndexHandler", "parse_edition_page", "type_token"]

_EDICION_WORD = {"MAT": "matutina", "VES": "vespertina"}

#: The edition word travels as an HTML entity on the real pages
#: ("Edici&oacute;n Matutina"); accept both the entity and the literal
#: accented form.
_FECHA_RE = re.compile(
    r"Fecha:\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*-\s*Edici(?:&oacute;|[oó])n\s*([A-Za-z]+)",
    re.IGNORECASE,
)
_ANCHOR_RE = re.compile(
    r"<a\s(?=[^>]*href=\"(/nota_detalle\.php\?codigo=(?P<codigo>\d+)"
    r"&amp;fecha=(?P<d>\d{1,2})/(?P<m>\d{1,2})/(?P<y>\d{4}))\")"
    r"(?=[^>]*class=\"enlaces\")(?P<attrs>[^>]*)>(?P<title>.*?)</a>",
    re.DOTALL,
)
#: The "no edition" answer keeps the page chrome but its section banner
#: reads "No hay datos para la fecha seleccionada" (probed on Sunday
#: 2026-07-19/MAT, sample in the task folder) — no Fecha header, no rows.
_NO_DATA_RE = re.compile(r"No hay datos para la fecha seleccionada")
_BANNER_RES: dict[str, re.Pattern[str]] = {
    "seccion": re.compile(r"class=\"txt_blanco\"[^>]*>([^<]*)<"),
    "organismo": re.compile(r"class=\"txt_blanco2\"[^>]*>([^<]*)<"),
    "departamento": re.compile(r"class=\"subtitle_azul\"[^>]*>(.*?)</td>", re.DOTALL),
}
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean(fragment: str) -> str:
    text = _TAG_RE.sub(" ", _COMMENT_RE.sub(" ", fragment))
    return _WS_RE.sub(" ", html_mod.unescape(text)).strip()


#: Titles like "Segundo Convenio Modificatorio…" lead with an ordinal;
#: the native type word is the token after it.
_ORDINALS = {
    "PRIMER", "PRIMERA", "SEGUNDO", "SEGUNDA", "TERCER", "TERCERA",
    "CUARTO", "CUARTA", "QUINTO", "QUINTA", "SEXTO", "SEXTA",
    "SEPTIMO", "SEPTIMA", "OCTAVO", "OCTAVA", "NOVENO", "NOVENA",
}


def _strip_accents(word: str) -> str:
    decomposed = unicodedata.normalize("NFD", word.upper())
    return "".join(c for c in decomposed if not unicodedata.combining(c)).strip(".,;:()")


def type_token(title: str) -> str:
    """The gazette's native type word: first title token, accent-free;
    the token after a leading ordinal ("Segundo Convenio…" → CONVENIO)."""
    words = title.strip().split()
    if not words:
        return ""
    first = _strip_accents(words[0])
    if first in _ORDINALS and len(words) > 1:
        return _strip_accents(words[1])
    return first


def _context_at(banners: dict[str, list[tuple[int, str]]], pos: int) -> dict[str, str]:
    """Latest banner of each kind opened before ``pos`` (document order)."""
    out: dict[str, str] = {}
    for kind, hits in banners.items():
        best = ""
        for at, value in hits:
            if at < pos:
                best = value
            else:
                break
        out[kind] = best
    return out


def parse_edition_page(html: str, date_iso: str, edicion: str) -> list[dict[str, str]]:
    """Canonical rows of one edition page, in document order.

    Raises when the page contradicts the request (echoed date/edición or
    a row fecha) — such a page must never be collected as data.
    """
    header = _FECHA_RE.search(html)
    if header is None:
        if _NO_DATA_RE.search(html):
            raise LookupError(f"no edition for {date_iso}/{edicion} (No hay datos banner)")
        raise ValueError(
            f"index {date_iso}/{edicion}: no Fecha header and no known "
            "no-edition banner — unknown shape, refusing to guess"
        )
    d, m, y, word = header.groups()
    echoed = f"{y}-{int(m):02d}-{int(d):02d}"
    if echoed != date_iso:
        raise ValueError(
            f"index {date_iso}/{edicion}: page echoes {echoed} — not the requested day; "
            "refusing to collect"
        )
    expected_word = _EDICION_WORD.get(edicion.upper())
    if expected_word is not None and word.lower() != expected_word:
        raise ValueError(
            f"index {date_iso}/{edicion}: page echoes edición {word!r} — "
            "not the requested edition; refusing to collect"
        )

    banners = {
        kind: [(mm.start(), _clean(mm.group(1))) for mm in rex.finditer(html)]
        for kind, rex in _BANNER_RES.items()
    }

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for mm in _ANCHOR_RE.finditer(html):
        row_fecha = f"{mm.group('y')}-{int(mm.group('m')):02d}-{int(mm.group('d')):02d}"
        if row_fecha != date_iso:
            raise ValueError(
                f"index {date_iso}/{edicion}: row {mm.group('codigo')} points at "
                f"{row_fecha} but the edition being collected is {date_iso} — "
                "refusing to collect"
            )
        codigo = mm.group("codigo")
        if codigo in seen:
            continue
        seen.add(codigo)
        ctx = _context_at(banners, mm.start())
        title = _clean(mm.group("title"))
        if not title:
            raise ValueError(f"index {date_iso}/{edicion}: row {codigo} carries no title")
        rows.append(
            {
                "codigo": codigo,
                "title": title,
                "seccion": ctx["seccion"],
                "organismo": ctx["organismo"],
                "departamento": ctx["departamento"],
            }
        )
    return rows


class DofIndexHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        date_iso = str(task.params["date"])
        edicion = str(task.params["edicion"]).upper()
        y, m, d = date_iso.split("-")
        return RequestSpec(
            url=f"{BASE_URL}/index.php",
            params={"year": y, "month": str(int(m)), "day": str(int(d)), "edicion": edicion},
            headers={"Accept": "text/html"},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        date_iso = str(task.params["date"])
        edicion = str(task.params["edicion"]).upper()
        tipos_raw = str(task.params.get("tipos", "")).strip()
        tipos = (
            {t.strip().upper() for t in tipos_raw.split(",") if t.strip()}
            if tipos_raw
            else None
        )
        html = response.content.decode("iso-8859-1", errors="replace")

        try:
            rows = parse_edition_page(html, date_iso, edicion)
        except LookupError:
            # Verified no-edition shape ("No hay datos…" banner): a fully
            # consumed non-edition still moves the watermark.
            return TaskResult(
                expected_empty=(
                    f"DOF has no {edicion} edition on {date_iso} "
                    "(source answers: No hay datos para la fecha seleccionada)"
                ),
                cursor_updates={cursor_key(edicion): date_iso},
            )

        if tipos is not None:
            kept = [row for row in rows if type_token(row["title"]) in tipos]
        else:
            kept = rows
        excluded = len(rows) - len(kept)

        seeds = [
            TaskSeed(
                type="dof_nota",
                params={
                    "codigo": row["codigo"],
                    "fecha": date_iso,
                    "edicion": edicion,
                    "title": row["title"],
                    "seccion": row["seccion"],
                    "organismo": row["organismo"],
                    "departamento": row["departamento"],
                },
            )
            for row in kept
        ]
        if not seeds:
            detail = (
                f"all {excluded} rows out of scope (tipos={tipos_raw})"
                if excluded
                else "Fecha header present, zero listing rows"
            )
            return TaskResult(
                expected_empty=(
                    f"DOF {edicion} edition of {date_iso} carries no in-scope "
                    f"notes ({detail})"
                ),
                cursor_updates={cursor_key(edicion): date_iso},
            )
        return TaskResult(
            next_tasks=seeds,
            cursor_updates={cursor_key(edicion): date_iso},
        )
