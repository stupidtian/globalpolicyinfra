"""The boe source: task-type registry and seed generation.

Boletín Oficial del Estado, the Spanish state gazette, section I
("Disposiciones generales": leyes, reales decretos, órdenes — the finished
state-level norms). Collected from BOE's on-site open-data API (see
docs/countries/esp/boe-zh.md). Flat document path: zero domain tables,
``documents`` is the whole ledger.

Task types (each = one module with ``build_request`` + ``parse``):

===============  =====================================================
type             what one task does
===============  =====================================================
boe_sumario      one calendar day: GET the date-addressed daily-summary
                 XML; every section-I item (configurable via ``secciones``)
                 yields one boe_item. No-edition days answer 404 — declared
                 as data (``accept_not_found``), verified against the known
                 "no existe" error body, recorded as an explained empty and
                 the watermark still advances. Empty or not, a fully
                 consumed day moves the ``boe_last_date`` cursor.
boe_item         one gazette entry: GET the detail XML (metadata + ELI +
                 analysis + full text in one response); registers the
                 document and stores the response bytes verbatim as the
                 doc.xml primary file.
===============  =====================================================

Params (key=value on the CLI)::

    window=2026-08-28:2026-08-31   closed date range (required, or sync=1)
    sync=1                          from = day after the kv cursor
                                    boe_last_date, to = *yesterday* (the
                                    current day's summary is generated
                                    Madrid-morning; fetching before that
                                    answers the same 404 as a no-edition
                                    day, so sync never claims today)
    secciones=1                     gazette sections to keep, comma
                                    separated (default 1; e.g. 1,3)
    origen=estatal                  origin filter, estatal | all (default
                                    estatal). Section I occasionally carries
                                    *regional* norms published via BOE (e.g.
                                    Comunidad de Madrid leyes, probed
                                    2026-09-01: BOE-A-2026-18282/18283) —
                                    the detail's origen_legislativo field is
                                    authoritative; the filter runs there and
                                    travels in task params so widening the
                                    scope later re-fetches automatically.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "ACCEPT_XML",
    "API_BASE",
    "CURSOR_KEY",
    "build_source",
    "start_tasks",
]

API_BASE = "https://www.boe.es"
#: Every API endpoint answers 400 without an explicit Accept MIME type.
ACCEPT_XML = {"Accept": "application/xml"}

CURSOR_KEY = "boe_last_date"


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country esp --source boe window=2026-08-28:2026-08-31\n"
        "  python cli.py collect --country esp --source boe sync=1\n"
        "  python cli.py collect --country esp --source boe window=2026-08-28:2026-08-31 secciones=1,3\n"
        "  python cli.py collect --country esp --source boe window=2026-08-28:2026-08-31 origen=all\n"
        "  python cli.py status --country esp --source boe"
    )


def _parse_date(raw: str, label: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None


def _parse_secciones(raw: str) -> list[str]:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise _fail("secciones must be a comma-separated list of section codes (e.g. 1 or 1,3)")
    return parts


def _parse_origen(raw: str) -> str:
    value = raw.strip().lower()
    if value not in ("estatal", "all"):
        raise _fail(f"origen must be estatal or all (got {raw!r})")
    return value


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")
    secciones = ",".join(_parse_secciones(str(params.get("secciones", "1"))))
    origen = _parse_origen(str(params.get("origen", "estatal")))

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
        # Never claim *today*: its summary is generated Madrid-morning, and a
        # pre-publication fetch answers the same 404 as a no-edition day.
        to_date = datetime.now(UTC).date() - timedelta(days=1)
        if from_date > to_date:
            return []  # already in sync — nothing due
    else:
        raise _fail("give window=FROM:TO or sync=1")

    seeds: list[TaskSeed] = []
    day = from_date
    while day <= to_date:
        seeds.append(
            TaskSeed(
                type="boe_sumario",
                params={
                    "date": day.isoformat(),
                    "secciones": secciones,
                    "origen": origen,
                },
            )
        )
        day += timedelta(days=1)
    return seeds


def build_source() -> SourceDefinition:
    from adapters.esp.sources.boe.item import BoeItemHandler
    from adapters.esp.sources.boe.sumario import BoeSumarioHandler

    return SourceDefinition(
        name="boe",
        start_tasks=start_tasks,
        task_types={
            "boe_sumario": BoeSumarioHandler(),
            "boe_item": BoeItemHandler(),
        },
    )
