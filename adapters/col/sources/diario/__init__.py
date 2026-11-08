"""The diario source: task-type registry and seed generation.

Diario Oficial de Colombia, the Colombian state gazette (founded
1864-04-30, ISSN 0122-2112), published by the Imprenta Nacional de
Colombia. Collected from the Imprenta's own gazette searcher at
``svrpubindc.imprenta.gov.co/diario/`` — a PrimeFaces/JSF application
with **no static per-issue URLs**: every issue is reached through a
session chain (probed 2026-10-19, samples in the task folder).

Session semantics (section 6.3, DEU BGBl pattern): one ``diario_session`
task per collect run establishes the cookie session and extracts the
JSF view state — which this application keeps **stable for the whole
session** (verified: three consecutive searches reusing the same value).
The view state and the per-issue download token travel in task params;
cookies stay inside the transport. The session task carries a per-run
nonce so every run re-establishes its own session (done tasks from
earlier runs must never be replayed against a fresh cookie jar).

Collection unit = one gazette issue (the whole-issue PDF, as published).
Flat document path: zero domain tables. Digital-PDF availability starts
at 2001-01; issues before that carry searcher rows but no PDF file —
the viewer answers with the publication-request form, recorded as an
explained empty (never OCR'd, per the task boundary).

Task types (each = one module with ``build_request`` + ``parse``):

===============  =====================================================
type             what one task does
===============  =====================================================
diario_session   one per run: GET the searcher home; parse the view
                 state; chain the FIRST day's diario_day — the chain
                 then walks day by day (search → row clicks → PDF →
                 next day's search), because the searcher's shared
                 server-side table model only stays valid while no
                 other search intervenes (trial-run lesson).
diario_day       one calendar day: POST the search (from=to=day);
                 every result row yields a diario_issue; a clean empty
                 table ("Registro 0 a 0 de 0") is an explained empty.
                 Either way the day moves the ``diario_last_date``
                 cursor — a finished search is a fully consumed day.
diario_issue     one issue: POST the row's "Ver Diario" button; parse
                 the viewer page into the dynamic-content download URL
                 plus the echoed issue metadata (the echo is the shape
                 guard against a stale table model). No download
                 object + the request-form shape = no PDF archived
                 (explained empty; the pre-2001 era signature). The
                 day's last issue chains the next day's search behind
                 its own PDF fetch.
diario_pdf       one issue's file: GET the dynamic-content URL (same
                 session); verify the %PDF- magic; register the
                 document and store the bytes as diario.pdf.
===============  =====================================================

Params (key=value on the CLI)::

    window=2026-10-14:2026-10-16   closed date range (required, or sync=1)
    sync=1                          from = day after the kv cursor
                                   diario_last_date, to = *yesterday*
                                   (issues are published through the
                                   day; sync never claims today)
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "CURSOR_KEY",
    "SEARCHER_URL",
    "build_source",
    "start_tasks",
]

SEARCHER_URL = "https://svrpubindc.imprenta.gov.co/diario/"
#: Canonical, rebuildable per-issue address for the ledger (the searcher
#: itself has no static issue URL; the issue number in a query parameter
#: keeps every doc_id hash distinct).
ISSUE_URL_TEMPLATE = "https://svrpubindc.imprenta.gov.co/diario/?numero={numero}"

CURSOR_KEY = "diario_last_date"


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country col --source diario window=2026-10-14:2026-10-16\n"
        "  python cli.py collect --country col --source diario sync=1\n"
        "  python cli.py status --country col --source diario"
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
        # Never claim *today*: the issue may not be published/scanned yet,
        # and a pre-publication search answers exactly like an empty day.
        to_date = datetime.now(UTC).date() - timedelta(days=1)
        if from_date > to_date:
            return []  # already in sync — nothing due
    else:
        raise _fail("give window=FROM:TO or sync=1")

    # The nonce gives every run its own session task identity: the view
    # state it extracts is session-bound, so a stale done row must never
    # satisfy a fresh run (DEU BGBl session-seed precedent).
    return [
        TaskSeed(
            type="diario_session",
            params={"from": from_date.isoformat(), "to": to_date.isoformat(), "nonce": _nonce()},
        )
    ]


def _nonce() -> str:
    import uuid

    return uuid.uuid4().hex


def build_source() -> SourceDefinition:
    from adapters.col.sources.diario.day import DiarioDayHandler
    from adapters.col.sources.diario.issue import DiarioIssueHandler
    from adapters.col.sources.diario.pdf import DiarioPdfHandler
    from adapters.col.sources.diario.session import DiarioSessionHandler

    return SourceDefinition(
        name="diario",
        start_tasks=start_tasks,
        task_types={
            "diario_session": DiarioSessionHandler(),
            "diario_day": DiarioDayHandler(),
            "diario_issue": DiarioIssueHandler(),
            "diario_pdf": DiarioPdfHandler(),
        },
        # Session-bound chain (cookies + view state + download tokens):
        # any task on any worker would break the chain, so concurrency
        # stays capped at one worker (framework-concurrency ruling 1.4).
        parallel_safe=False,
    )
