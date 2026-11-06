"""The suin source: task-type registry and seed generation.

SUIN-Juriscol (Sistema Único de Información Normativa), Colombia's
official normative information system, operated by the Ministerio de
Justicia y del Derecho. The 2026 redesign moved the search front end to
lexis.minjusticia.gov.co, whose backend is a plain, key-free,
session-free HTTP pair (probed 2026-10-19, samples in the task folder):

- metadata search: a public Elasticsearch ``_search`` endpoint over the
  ``documents_pdn`` index (~103k documents, deep history to 1882);
- full text: ``GET /suin-search/api/documentos/{id}`` whose JSON
  ``data.textoHtml`` is the whole current consolidated text as HTML.

Collection unit = one norm's *current* registry state (a live-view
snapshot: ``vigencia``/``estado`` are as-fetched, not as-published — the
as-published carrier is the diario source). Flat document path: zero
domain tables.

Task types (each = one module with ``build_request`` + ``parse``):

===============  =====================================================
type             what one task does
===============  =====================================================
suin_window      one sanction-date calendar day: POST the ES query
                 (fecha day-range + tipo whitelist, sorted by id) for
                 page 0; every hit yields a suin_doc seed, a full page
                 chains a suin_page successor. An empty or exhausted
                 day moves the ``suin_last_date`` cursor.
suin_page        one search_after continuation page inside a day; same
                 outputs; the last (short) page closes the day.
suin_doc         one norm: GET the document API; registers the document
                 and stores ``textoHtml`` verbatim as doc.html. HTTP
                 204 = metadata indexed but text not yet loaded — an
                 explained empty (refresh re-fetches later).
===============  =====================================================

Params (key=value on the CLI)::

    window=2026-10-01:2026-10-19   closed fecha-date range (required,
                                   or sync=1)
    sync=1                          from = day after the kv cursor
                                   suin_last_date, to = *yesterday*
                                   (sanction dates may be indexed with
                                   a lag; sync never claims today)
    tipos=LEY,DECRETO               normative tipo whitelist, comma
                                   separated (default DEFAULT_TIPOS;
                                   scope travels in task params so
                                   widening re-fetches automatically)
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "API_BASE",
    "CURSOR_KEY",
    "DEFAULT_TIPOS",
    "DOC_API_URL",
    "ES_SEARCH_URL",
    "PAGE_SIZE",
    "build_source",
    "parse_tipos",
    "start_tasks",
]

API_BASE = "https://lexis.minjusticia.gov.co"
ES_SEARCH_URL = f"{API_BASE}/elasticsearch/documents_pdn/_search"
DOC_API_URL = f"{API_BASE}/suin-search/api/documentos"

CURSOR_KEY = "suin_last_date"

#: Page size of the ES window/page queries (one task = one request).
PAGE_SIZE = 100

#: Default normative tipo whitelist — mirrors the searcher's own "Normas"
#: section, expressed in the index's actual ``tipo`` values. Judicial
#: material (CC-SENTENCIA / SENTENCIA / CC-AUTOS) and the junk-filled
#: AUTO bucket (probed rows are form leftovers with no entity/date) are
#: excluded by design. ``tipos=`` widens or replaces this scope; the
#: scope rides in task params so widening re-fetches automatically.
DEFAULT_TIPOS: tuple[str, ...] = (
    "CONSTITUCION POLITICA",
    "ACTO LEGISLATIVO",
    "LEY",
    "CODIGO",
    "DECRETO",
    "RESOLUCION",
    "RESOLUCION EXTERNA",
    "CIRCULAR",
    "CIRCULAR EXTERNA",
    "CIRCULAR CONJUNTA",
    "ACUERDO",
    "DIRECTIVA PRESIDENCIAL",
    "DIRECTIVA VICEPRESIDENCIAL",
    "DIRECTIVA MINISTERIAL",
    "INSTRUCCION",
    "INSTRUCCION ADMINISTRATIVA CONJUNTA",
)


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country col --source suin window=2026-10-01:2026-10-19\n"
        "  python cli.py collect --country col --source suin sync=1\n"
        "  python cli.py collect --country col --source suin window=2026-10-01:2026-10-19 tipos=LEY,DECRETO\n"
        "  python cli.py status --country col --source suin"
    )


def parse_tipos(raw: str | None) -> list[str]:
    """Comma-separated tipo whitelist -> ordered list (default when absent)."""
    if raw is None or not raw.strip():
        return list(DEFAULT_TIPOS)
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise _fail("tipos must be a comma-separated list of tipo values (e.g. LEY,DECRETO)")
    return parts


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")
    tipos = parse_tipos(str(params.get("tipos", "")) if params.get("tipos") else None)

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
        # Never claim *today*: sanction-date indexing lags the calendar day,
        # and a pre-indexing day answers exactly like an empty day.
        to_date = datetime.now(UTC).date() - timedelta(days=1)
        if from_date > to_date:
            return []  # already in sync — nothing due
    else:
        raise _fail("give window=FROM:TO or sync=1")

    scope = ",".join(tipos) if tipos != list(DEFAULT_TIPOS) else ""
    seeds: list[TaskSeed] = []
    day = from_date
    while day <= to_date:
        task_params: dict[str, str] = {"date": day.isoformat()}
        if scope:
            task_params["tipos"] = scope
        seeds.append(TaskSeed(type="suin_window", params=task_params))
        day += timedelta(days=1)
    return seeds


def _parse_date(raw: str, label: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None


def build_source() -> SourceDefinition:
    from adapters.col.sources.suin.doc import SuinDocHandler
    from adapters.col.sources.suin.window import SuinPageHandler, SuinWindowHandler

    return SourceDefinition(
        name="suin",
        start_tasks=start_tasks,
        task_types={
            "suin_window": SuinWindowHandler(),
            "suin_page": SuinPageHandler(),
            "suin_doc": SuinDocHandler(),
        },
        # Stateless key-free HTTP pair: any task on any worker with any
        # session (framework-concurrency ruling 1.4).
        parallel_safe=True,
    )
