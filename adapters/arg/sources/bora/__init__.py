"""The bora source: task-type registry and seed generation.

Boletín Oficial de la República Argentina, primera sección ("Legislación
y Avisos Oficiales": leyes, decretos — including DNU emergency decrees —
resoluciones, disposiciones and the rest of the gazette's 25 official
rubros). Flat document path: zero domain tables, ``documents`` is the whole
ledger (see docs/countries/arg/bora-zh.md).

Four task types (each = one module with ``build_request`` + ``parse``):

===============  =====================================================
type             what one task does
===============  =====================================================
bora_fecha       point the server-side session at one day (GET
                 ``/edicion/actualizar/{DD-MM-YYYY}``, XHR — the site's own
                 edition selector). Seeds carry a per-run ``run`` stamp so a
                 crashed-and-rerun window re-executes the side effect the
                 done-skip would swallow; enqueued only by the seed or by
                 the previous day's last listing page (one active day per
                 run — the session holds exactly one date).
bora_seccion     one listing page of the day's primera: page 1 via
                 ``/seccion/primera`` (HTML), continuations via
                 ``/seccion/actualizar/primera?pag=N&ult_rubro=…`` (the
                 infinite-scroll JSON fragment). Every row becomes a
                 bora_detalle seed; page 1 verifies the session date against
                 the page's own ``fechaSeleccionadaYMD`` (mismatch = stale
                 chain, transient); a no-edition day redirects to the
                 homepage — a verified shape recorded as an explained empty
                 that still advances the cursor. The fragment answering
                 ``hay_mas_datos=false`` completes the day (advances
                 ``bora_last_date``) and chains the next day's bora_fecha.
                 **This channel, not the site search**: the search index
                 missed 8 of 121 avisos in the 2026-08-28..31 verification
                 window (probed 2026-09-03, module docstring has the ids).
bora_detalle     one gazette entry: GET the URL-addressed detail page
                 (session-free, the date is in the path). Modern pages
                 carry the full text inline (stored verbatim as
                 detalle.html); scan-era shells embed the whole scanned
                 PDF as base64 in the page (extracted to aviso.pdf). The
                 page's own anexosDiv lists attachment PDFs — each becomes
                 a bora_anexo seed and its target filename is pre-declared
                 in the document's meta.files. Identity keys off the
                 page-reported publication date (one aviso can sit in
                 several days' listings; one date → one source_url → one
                 doc_id).
bora_anexo       one attachment PDF: GET /pdf/download_anexo with all
                 selectors in the URL (GET and POST are byte-identical,
                 probed 2026-09-02). The file lands next to its parent
                 entry; attachments are integral parts of the norm (the
                 print edition does not carry them).
===============  =====================================================

Params (key=value on the CLI)::

    window=2026-08-28:2026-08-31   closed date range (required, or sync=1)
    sync=1                          from = day after the kv cursor
                                    bora_last_date, to = *yesterday*

Seeding rule (chain discipline): only the first not-yet-consumed day is
seeded — ``fecha(max(window_from, cursor+1), to, run=<stamp>)`` — and each
day's last listing page enqueues the next. A window entirely at or behind
the cursor produces no seeds (the watermark is "confirmed consumed"; redoing
an old window is repair-channel territory, not a re-sweep).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "BASE_URL",
    "CURSOR_KEY",
    "SECCION",
    "build_source",
    "start_tasks",
]

BASE_URL = "https://www.boletinoficial.gob.ar"
SECCION = "primera"  # the norms section; 2=personnel (robots-disallowed),
# 3=procurement, 4=.ar domain notices (probed 2026-09-02)

#: Headers the site's own XHR endpoints expect (probed 2026-09-02/03).
XHR_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json",
    "Referer": f"{BASE_URL}/busquedaAvanzada/all",
}

CURSOR_KEY = "bora_last_date"


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country arg --source bora window=2026-08-28:2026-08-31\n"
        "  python cli.py collect --country arg --source bora sync=1\n"
        "  python cli.py status --country arg --source bora"
    )


def _parse_date(raw: str, label: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")

    if params.get("window"):
        window = str(params["window"])
        from_str, sep, to_str = window.partition(":")
        if not sep or not from_str or not to_str:
            raise _fail(f"window must look like FROM:TO (got {window!r})")
        from_date = _parse_date(from_str.strip(), "window FROM")
        to_date = _parse_date(to_str.strip(), "window TO")
        if from_date > to_date:
            raise _fail(f"window start {from_date} is after its end {to_date}")
    elif is_sync:
        kv = params.get("_kv", {})
        cursor = kv.get(CURSOR_KEY)
        if not cursor:
            raise _fail("sync=1 needs a previous sweep; run an initial window=… first")
        from_date = date.fromisoformat(cursor) + timedelta(days=1)
        # Never claim *today*: its edition is generated Buenos Aires-morning
        # and a pre-generation fetch answers like a no-edition day.
        to_date = datetime.now(UTC).date() - timedelta(days=1)
        if from_date > to_date:
            return []  # already in sync — nothing due
    else:
        raise _fail("give window=FROM:TO or sync=1")

    kv = params.get("_kv", {})
    cursor = kv.get(CURSOR_KEY)
    if cursor:
        consumed = date.fromisoformat(cursor)
        if from_date <= consumed:
            from_date = consumed + timedelta(days=1)  # chain rule: seed the
            # first not-yet-consumed day only (see module docstring)
    if from_date > to_date:
        return []
    run = datetime.now(UTC).isoformat(timespec="seconds")
    return [
        TaskSeed(
            type="bora_fecha",
            params={"date": from_date.isoformat(), "to": to_date.isoformat(), "run": run},
        )
    ]


def build_source() -> SourceDefinition:
    from adapters.arg.sources.bora.anexo import BoraAnexoHandler
    from adapters.arg.sources.bora.detalle import BoraDetalleHandler
    from adapters.arg.sources.bora.fecha import BoraFechaHandler
    from adapters.arg.sources.bora.seccion import BoraSeccionHandler

    return SourceDefinition(
        name="bora",
        start_tasks=start_tasks,
        task_types={
            "bora_fecha": BoraFechaHandler(),
            "bora_seccion": BoraSeccionHandler(),
            "bora_detalle": BoraDetalleHandler(),
            "bora_anexo": BoraAnexoHandler(),
        },
    )
