"""The tad source: task-type registry and seed generation.

Teisės aktų duomenų bazė (TAD), the legal-acts database of the Seimas
document system. Lithuania's official publication medium is the TAR
register since 2014 (before that the gazette Valstybės žinios); the TAD
records each act's publication reference either way, so one source spans
both eras. Collected over three stateless GET layers (probed shapes
2026-09-15, samples in the task folder; see docs/countries/ltu/tad-zh.md):

===============  =====================================================
type             what one task does
===============  =====================================================
tad_list         one (day × scope-slice × page): GET the legacy search
                 on www.lrs.lt (``dokpaieska.rezult_l``); every result
                 row yields one tad_doc seed. The response is
                 windows-1257 HTML; the row count lives in
                 ``Iš viso - <b>N</b>`` and pages hold 30 rows, with
                 stateless ``p_no`` pagination (no session key —
                 probed 2026-09-15). Zero rows is a clean, fully
                 consumed slice: expected_empty and the day cursor
                 still advances.
tad_doc          one document: GET ``showdoc_l?p_id=…``; the transport
                 follows the 302 onto the e-seimas.lrs.lt document
                 page (UTF-8 JSF) whose labelled cells carry the
                 research metadata. Registers the document and seeds
                 tad_text with the TAD id extracted from the page's
                 own links. Official translations (Kalba other than
                 Lietuvių) are explained-away skips — they are
                 separate records without a publication reference.
tad_text         one document's original (as-adopted) text: GET
                 ``/rs/legalact/TAD/{tadId}/``; the response bytes are
                 stored verbatim as the text.html primary file.
===============  =====================================================

Params (key=value on the CLI)::

    window=2024-06-01:2024-06-03   closed date range (required, or sync=1)
    sync=1                          from = day after the kv cursor
                                    tad_last_date, to = *yesterday* (acts
                                    reach the register days after adoption:
                                    the 2024 sample took adoption 06-05 ->
                                    registration 06-14 — so "not yet
                                    enrolled" and "nothing that day" answer
                                    identically; sync never claims today)
    scope=laws,decrees,resolutions,orders
                                    which issuer slices to enumerate,
                                    comma separated (default: all four)

The date window matches the *adoption* date (the legacy search has no
other axis); the ledger's publication_date stays the gazette/TAR
publication day. Fetch-time axis and research-time axis are different by
design (section 6.5).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "API_BASE",
    "CURSOR_KEY",
    "PAGE_SIZE",
    "PORTAL_BASE",
    "SCOPE_PRESETS",
    "build_source",
    "decode_response",
    "source_url_for",
    "start_tasks",
]

API_BASE = "https://www.lrs.lt/pls/inter3"
PORTAL_BASE = "https://e-seimas.lrs.lt"
#: Rows per result page of the legacy search (probed 2026-09-15).
PAGE_SIZE = 30

CURSOR_KEY = "tad_last_date"

#: Scope slice -> the (p_org, p_drus) enumeration slices it expands to.
#: The legacy search takes a single p_drus per request (repeated values
#: are silently narrowed to one — probed 2026-09-15, sample 17), so one
#: seed per type code. p_org "" means "any issuer".
SCOPE_PRESETS: dict[str, tuple[tuple[str, str], ...]] = {
    "laws": (("", "1"), ("", "10"), ("", "8"), ("", "173"), ("", "250")),
    "decrees": (("3", "29"),),
    "resolutions": (("2", "31"),),
    # Ministerial orders, single type code, any issuer (the ministries
    # dominate; probed 2026-09-15: 474 in June 2024 across issuers, page
    # rows uniformly Įsakymas — the filter is clean; earlier "0 hits"
    # was an artifact of a three-day window over one ministry).
    "orders": (("", "37"),),
}


def decode_response(content: bytes) -> str:
    """Decode a response body: the legacy layer answers windows-1257,
    the portal and /rs/ layers UTF-8 — try UTF-8 first, fall back."""
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("windows-1257")


def source_url_for(pid: str) -> str:
    """The canonical, rebuildable document URL (the legacy detail entry;
    it serves both the derivable TAIS-era ids and the newer hash ids)."""
    return f"{API_BASE}/dokpaieska.showdoc_l?p_id={pid}"


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country ltu --source tad window=2024-06-01:2024-06-03\n"
        "  python cli.py collect --country ltu --source tad sync=1\n"
        "  python cli.py collect --country ltu --source tad window=2024-06-01:2024-06-03 scope=laws\n"
        "  python cli.py status --country ltu --source tad"
    )


def _parse_date(raw: str, label: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None


def _parse_scope(raw: str) -> list[tuple[str, str, str]]:
    """Expand ``scope=laws,decrees`` into [(scope_name, org, drus), …]."""
    names = [p.strip() for p in raw.split(",") if p.strip()]
    if not names:
        raise _fail("scope must be a comma-separated list of " + ", ".join(sorted(SCOPE_PRESETS)))
    slices: list[tuple[str, str, str]] = []
    for name in names:
        preset = SCOPE_PRESETS.get(name)
        if preset is None:
            raise _fail(f"unknown scope {name!r} (known: {', '.join(sorted(SCOPE_PRESETS))})")
        for org, drus in preset:
            slices.append((name, org, drus))
    return slices


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")
    slices = _parse_scope(str(params.get("scope", ",".join(SCOPE_PRESETS))))

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
        # Never claim *today*: acts reach the register days after adoption
        # (2024 sample: adopted 06-05, enrolled 06-14), so a pre-enrolment
        # fetch answers the same clean zero as an empty day.
        to_date = datetime.now(UTC).date() - timedelta(days=1)
        if from_date > to_date:
            return []  # already in sync — nothing due
    else:
        raise _fail("give window=FROM:TO or sync=1")

    seeds: list[TaskSeed] = []
    day = from_date
    while day <= to_date:
        for scope_name, org, drus in slices:
            seeds.append(
                TaskSeed(
                    type="tad_list",
                    params={
                        "date": day.isoformat(),
                        "org": org,
                        "drus": drus,
                        "page": "1",
                        "scope": scope_name,
                    },
                )
            )
        day += timedelta(days=1)
    return seeds


def build_source() -> SourceDefinition:
    from adapters.ltu.sources.tad.doc import TadDocHandler
    from adapters.ltu.sources.tad.list import TadListHandler
    from adapters.ltu.sources.tad.text import TadTextHandler

    return SourceDefinition(
        name="tad",
        start_tasks=start_tasks,
        task_types={
            "tad_list": TadListHandler(),
            "tad_doc": TadDocHandler(),
            "tad_text": TadTextHandler(),
        },
    )
