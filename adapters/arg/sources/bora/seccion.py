"""Task type ``bora_seccion``: one listing page of the day's primera sección.

Page 1: GET ``/seccion/primera`` — server-rendered HTML for the session
date. Continuation pages: GET ``/seccion/actualizar/primera?pag=N&ult_rubro=…``
— the JSON fragment the site's infinite scroll fetches (``{html,
hay_mas_datos, sig_pag, ult_rubro}``). Both shapes were probed verbatim
(2026-09-02/03, samples in the task folder).

Why this channel and not the site's search endpoint: the search index has
holes. In the 2026-08-28..31 verification window it missed 8 avisos the
gazette's own section pages list (346550/346551/346552 on 08-28,
346572/346623/346630/346631/346632 on 08-31 — agency notices; none of them
appear under any neighbouring day or even a 10-day-wide search window,
445 results, probed 2026-09-03). Count-only reconciliation had masked this
(the missing items coincided with future-dated extras) — the multiset
lesson, applied to sets this time. The section pages are the gazette's own
edition view and are complete.

Page-1 guards, in order:

1. ``avisosSeccionDiv`` present → a real section page. The embedded
   ``fechaSeleccionadaYMD`` must equal the task's day — a mismatch means
   the session date and the chain disagree (stale chain after a crash, or
   an ordering bug); that is transient (a later fecha task re-establishes
   the day, backoff retries then succeed).
2. ``avisosSeccionDiv`` absent while the home calendar markers are there
   → the "no edition" answer: the site redirects ``/seccion/primera`` to
   the homepage for a day with no edition (Saturdays/holidays; the followed
   body is the homepage, which also carries the *requested* date in its
   calendar script — the date alone cannot discriminate, probed 2026-09-03).
   Recorded as an explained empty; the watermark still advances.
3. Anything else → loud failure.

Pagination completes when a fragment answers ``hay_mas_datos=false``
(one probe request past the last row-bearing page — the price of having
no total count on this channel). That page advances ``bora_last_date``
and enqueues the next day's ``bora_fecha`` when the window continues.
Every listing row's own date is validated against the task's day — a row
from another day means the session moved underneath us and the parse
refuses to collect.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from adapters.arg.sources.bora import BASE_URL, CURSOR_KEY, SECCION
from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView

__all__ = ["BoraSeccionHandler", "parse_listing"]

_ROW_RE = re.compile(
    r'<a href="/detalleAviso/(?P<seccion>[a-z]+)/(?P<aid>\d+)/(?P<fecha>\d{8})'
    r'(?P<query>[^"]*)"[^>]*>\s*<div class="linea-aviso">(?P<body>.*?)</div>',
    re.DOTALL,
)
_HEADER_RE = re.compile(r'<h5 class="seccion-rubro[^"]*">\s*(?P<rubro>[^<]+?)\s*</h5>')
_AUTHORITY_RE = re.compile(r'<p class="item">\s*([^<]*?)\s*</p>')
_SMALL_RE = re.compile(r"<small>\s*(.*?)\s*</small>", re.DOTALL)
_PUB_SMALL_RE = re.compile(r"^Fecha de Publicaci[oó]n:\s*(\d{2}/\d{2}/\d{4})$")
_FECHA_SEL_RE = re.compile(r"fechaSeleccionadaYMD\s*=\s*'(\d{8})'")
_ULT_RUBRO_RE = re.compile(r"ultimoRubro = '([^']*)'")

_SECTION_MARKER = "avisosSeccionDiv"
_HOME_MARKER = "diasHabilitadosPortadaSuplemento"


def parse_listing(html: str, expected_date: str) -> list[dict[str, str]]:
    """Walk the listing rows in document order, tracking the current rubro.

    Works for both the full page-1 HTML and the pagination fragments (same
    row markup, probed). ``expected_date`` is YYYY-MM-DD; every row must
    point at that same day or the shape is refused (a row from another day
    would corrupt the document's date basis).
    """
    headers = [(m.start(), m.group("rubro")) for m in _HEADER_RE.finditer(html)]
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    rubro = ""
    header_idx = -1
    for m in _ROW_RE.finditer(html):
        # both iterators walk in document order: advance the header pointer
        # to the last rubro header opened before this row
        while header_idx + 1 < len(headers) and headers[header_idx + 1][0] < m.start():
            header_idx += 1
            rubro = headers[header_idx][1]
        if "?anexos=" in m.group("query"):
            continue  # attachment-view variant of an already-listed aviso
        aid = m.group("aid")
        if aid in seen:
            continue
        seen.add(aid)
        fecha = m.group("fecha")
        if f"{fecha[:4]}-{fecha[4:6]}-{fecha[6:]}" != expected_date:
            raise ValueError(
                f"listing row {aid} points at {fecha} but the day being "
                f"collected is {expected_date} — the session moved underneath "
                "us; refusing to collect"
            )

        body = m.group("body")
        authority_m = _AUTHORITY_RE.search(body)
        smalls = [re.sub(r"\s+", " ", s).strip() for s in _SMALL_RE.findall(body)]
        nro, desc, row_pub = "", "", ""
        fields: list[str] = []
        for small in smalls:
            if small.lower() in ("desplegar menú", "primera sección"):
                continue
            pub_m = _PUB_SMALL_RE.match(small)
            if pub_m:
                row_pub = pub_m.group(1)
                continue
            fields.append(small)
        if fields:
            nro = fields[0]
        if len(fields) > 1:
            desc = fields[-1]
        if not (nro or desc or authority_m):
            raise ValueError(f"listing row {aid} carries no readable fields")
        items.append(
            {
                "aviso_id": aid,
                "seccion": m.group("seccion"),
                "fecha": fecha,
                "rubro": rubro,
                "autoridad": authority_m.group(1).strip() if authority_m else "",
                "nro": nro,
                "desc": desc,
                "fecha_pub": row_pub,
            }
        )
    return items


def _detalle_params(item: dict[str, str]) -> dict[str, str]:
    params = {
        "seccion": item["seccion"],
        "aviso_id": item["aviso_id"],
        "fecha": item["fecha"],
    }
    if item["rubro"]:
        params["rubro"] = item["rubro"]
    for key in ("autoridad", "nro", "desc"):
        if item[key]:
            params[f"lista_{key}"] = item[key]
    return params


def _next_day_params(task: TaskView) -> TaskSeed | None:
    from datetime import date, timedelta

    day = date.fromisoformat(str(task.params["date"]))
    to = date.fromisoformat(str(task.params["to"]))
    if day >= to:
        return None
    return TaskSeed(
        type="bora_fecha",
        params={
            "date": (day + timedelta(days=1)).isoformat(),
            "to": str(task.params["to"]),
            "run": str(task.params["run"]),
        },
    )


class BoraSeccionHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        pag = int(task.params.get("pag", 1))
        if pag == 1:
            return RequestSpec(
                url=f"{BASE_URL}/seccion/{SECCION}",
                headers={"Accept": "text/html", "Referer": f"{BASE_URL}/"},
            )
        ult_rubro = str(task.params.get("ult_rubro", ""))
        return RequestSpec(
            url=f"{BASE_URL}/seccion/actualizar/{SECCION}",
            params={"pag": pag, "ult_rubro": quote(ult_rubro)},
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json",
                "Referer": f"{BASE_URL}/seccion/{SECCION}",
            },
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        from runtime.errors import TransientError

        date_iso = str(task.params["date"])
        pag = int(task.params.get("pag", 1))
        next_day = _next_day_params(task)

        if pag == 1:
            page = response.content.decode("utf-8", errors="replace")
            if _SECTION_MARKER not in page:
                if _HOME_MARKER in page:
                    # The "no edition" answer: /seccion/primera redirected to
                    # the homepage (followed by the transport). Probed shape.
                    return TaskResult(
                        expected_empty=(
                            f"BORA has no edition on {date_iso} (the section "
                            "page redirects to the homepage)"
                        ),
                        cursor_updates={CURSOR_KEY: date_iso},
                        next_tasks=[next_day] if next_day else [],
                    )
                raise ValueError(
                    f"seccion {date_iso}: neither a section page "
                    f"({_SECTION_MARKER!r}) nor the no-edition homepage shape"
                )
            selected = _FECHA_SEL_RE.findall(page)
            if selected and selected[0] != date_iso.replace("-", ""):
                raise TransientError(
                    f"seccion {date_iso}: session serves {selected[0]} — the "
                    "date-selection task for this day has not run (stale "
                    "chain or ordering); retrying after it re-establishes"
                )
            html = page
            ult_rubro_m = _ULT_RUBRO_RE.findall(page)
            ult_rubro = ult_rubro_m[-1] if ult_rubro_m else ""
            more = True  # page 1 always probes page 2 for the completion bit
        else:
            payload = response.json()
            html = str(payload.get("html") or "")
            more = bool(payload.get("hay_mas_datos"))
            ult_rubro = str(payload.get("ult_rubro") or "")

        items = parse_listing(html, date_iso)
        seeds = [
            TaskSeed(type="bora_detalle", params=_detalle_params(item)) for item in items
        ]
        if more:
            params: dict[str, str] = {
                "date": date_iso,
                "to": str(task.params["to"]),
                "run": str(task.params["run"]),
                "pag": str(pag + 1),
            }
            if ult_rubro:
                params["ult_rubro"] = ult_rubro
            seeds.append(TaskSeed(type="bora_seccion", params=params))
            return TaskResult(next_tasks=seeds)

        # Last page: the day is fully consumed — advance and chain the next.
        if next_day:
            seeds.append(next_day)
        if not seeds:
            return TaskResult(
                expected_empty=(
                    f"page {pag} of {date_iso} carries no rows — the day is "
                    "complete (earlier pages hold the avisos)"
                ),
                cursor_updates={CURSOR_KEY: date_iso},
            )
        return TaskResult(next_tasks=seeds, cursor_updates={CURSOR_KEY: date_iso})
