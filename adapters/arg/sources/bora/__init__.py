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

import hashlib
import re
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

#: ``rubros`` scope presets (base rubro names, upper-cased, "- ANTERIOR"
#: republication suffixes stripped by normalize_rubro). "normas" is the
#: declared research scope (user ruling 2026-10-08): every normative
#: instrument — statutes, decrees (incl. DNU), agency resolutions and
#: dispositions, instructions, judicial acordadas, treaties. "all" keeps
#: every listing row (adds official notices, collective bargaining
#: agreements, job competitions, auctions, union registrations …).
NORMAS_RUBROS: frozenset[str] = frozenset({
    "LEYES", "LEGISLACION",
    "DECRETOS", "DECRETOS DESCLASIFICADOS", "DECISIONES ADMINISTRATIVAS",
    "RESOLUCIONES", "RESOLUCIONES CONJUNTAS", "RESOLUCIONES GENERALES",
    "RESOLUCIONES SINTETIZADAS",
    "DISPOSICIONES", "DISPOSICIONES CONJUNTAS", "DISPOSICIONES SINTETIZADAS",
    "INSTRUCCIONES PRESIDENCIALES", "INTRUCCIONES GENERALES",  # source spelling
    "ACORDADAS", "TRATADOS Y CONVENIOS INTERNACIONALES",
})
_RUBRO_PRESETS = {"normas": NORMAS_RUBROS, "all": None}


def normalize_rubro(raw: str) -> str:
    """Listing header → canonical base name ('RESOLUCIONES  - ANTERIOR' →
    'RESOLUCIONES'). Case/spaces folded; the '- ANTERIOR' suffix marks items
    republicated from an earlier day (doc_id dedup already handles those)."""
    base = re.sub(r"\s+", " ", raw or "").strip().upper()
    return re.sub(r"\s*-\s*ANTERIOR\s*$", "", base).strip()


def resolve_rubros(raw: Any) -> str:
    """CLI ``rubros`` value → canonical scope string.

    Accepts a preset alias (``normas`` | ``all``) or an explicit comma list
    of base names. Returns ``"all"`` (no filter) or a sorted comma string —
    presets expand to their name list, so the *contents* of a scope, not its
    alias, are what travels in task params: a scope change means new task
    identities (widening re-enumerates and re-fetches automatically, and a
    preset edited later cannot silently drift under old task ids).
    """
    value = str(raw if raw is not None else "normas").strip().lower()
    if value == "all":
        return "all"
    preset = _RUBRO_PRESETS.get(value)
    if preset is not None:
        return ",".join(sorted(preset))
    names = {normalize_rubro(part) for part in value.split(",") if part.strip()}
    if not names:
        raise _fail(f"rubros must be normas | all | a comma list (got {raw!r})")
    return ",".join(sorted(names))


def cursor_key(rubros_param: str) -> str:
    """Watermark key per scope: each scope keeps its own cursor, so widening
    starts a fresh chain while the narrower scope's watermark stands (the
    identity layer dedups the overlap — 多入口一漏斗). The unfiltered scope
    keeps the plain historical key."""
    if rubros_param == "all":
        return CURSOR_KEY
    if rubros_param == ",".join(sorted(NORMAS_RUBROS)):
        return f"{CURSOR_KEY}[normas]"
    digest = hashlib.md5(rubros_param.encode()).hexdigest()[:6]
    return f"{CURSOR_KEY}[{digest}]"


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country arg --source bora window=2026-08-28:2026-08-31\n"
        "  python cli.py collect --country arg --source bora sync=1\n"
        "  python cli.py collect --country arg --source bora window=2026-01-01:2026-12-31 rubros=all\n"
        "  python cli.py status --country arg --source bora"
    )


def _parse_date(raw: str, label: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")
    rubros = resolve_rubros(params.get("rubros", "normas"))
    key = cursor_key(rubros)

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
        cursor = kv.get(key)
        if not cursor:
            raise _fail(
                "sync=1 needs a previous sweep for this rubros scope; "
                "run an initial window=… first"
            )
        from_date = date.fromisoformat(cursor) + timedelta(days=1)
        # Never claim *today*: its edition is generated Buenos Aires-morning
        # and a pre-generation fetch answers like a no-edition day.
        to_date = datetime.now(UTC).date() - timedelta(days=1)
        if from_date > to_date:
            return []  # already in sync — nothing due
    else:
        raise _fail("give window=FROM:TO or sync=1")

    kv = params.get("_kv", {})
    cursor = kv.get(key)
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
            params={
                "date": from_date.isoformat(),
                "to": to_date.isoformat(),
                "run": run,
                "rubros": rubros,
            },
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
