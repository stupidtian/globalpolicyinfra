"""The frl source: task-type registry, seed generation, shared helpers.

Federal Register of Legislation (https://www.legislation.gov.au, operated
by the Australian Government Attorney-General's Department) — the official
register of Commonwealth legislation. Collected through the register's
undocumented-but-public OData v4 API at api.prod.legislation.gov.au (the
same backend the redesigned website itself calls; probed 2026-08-31: no
key, no session, no browser, ``$top`` capped at 100).

Entity model (three layers): ``Titles`` (a persistent title = one Act or
instrument, stable id like ``C2004A00485``) → ``Versions`` (point-in-time
text states with validity windows; ``compilationNumber`` '0' = as-made,
N = a registered compilation, null = an uncompiled amendment marker with
no document of its own) → ``Documents`` (per-format files, unique on
title + start + rectification + volume + type-slot + format). Files are
downloaded via the ``documents/find(...)`` function endpoint, which wraps
the bytes in a JSON envelope (``bytes`` field, base64; decoded sizes
matched ``sizeInBytes`` on every probe).

Version policy (two layers, both captured): the as-made document is the
publication event itself ("what was made on date X") and is always
fetched, plus the instrument's Explanatory Statement; the latest compiled
version is the in-force anchor ("what is in force now") and is fetched by
default — ``comp=all`` extends to every historical compilation.

Task types (each = one module with ``build_request`` + ``parse``):

===============  =====================================================
type             what one task does
===============  =====================================================
frl_day          seed: one registration day — Versions whose
                 registeredAt falls on that date; spawns one frl_title
                 per distinct title (signal = newest registeredAt); a
                 day with zero events (weekend) is a legal empty and
                 still advances the date cursor; a full page of 100
                 chains to the next $skip
frl_made         seed: one page of the making-date enumeration
                 (made=FROM:TO) — Titles made in the range, $top=100
                 per page, chained by $skip; spawns frl_title per id;
                 never touches the registration cursor (independent
                 axis — see docs/countries/aus/frl-zh.md §7)
frl_title        one title with its full version lineage
                 (Titles('{id}')?$expand=versions); upserts the titles
                 row, rewrites title_versions, archives the raw
                 response as title.json; spawns frl_docs per version
                 selected by the capture policy
frl_docs         one version's file inventory (Documents filtered by
                 titleId + start — a handful of rows, no pagination);
                 picks formats (EPUB volume 0 first, PDF fallback) and
                 spawns one frl_doc per file
frl_doc          one file via documents/find(asat=version start);
                 decodes the payload (JSON envelope or raw stream —
                 the server chooses per title), verifies the ZIP/PDF
                 magic, writes the file and one documents row hanging
                 off the title entity
===============  =====================================================

Params (key=value on the CLI)::

    window=2026-08-27:2026-08-28   closed registration-date range
                                    (or sync=1, or made=FROM:TO)
    sync=1                          from = day after the kv cursor
                                    frl_last_date, to = today
    made=2010-01-01:2010-12-31      backfill entry: every title *made*
                                    in the closed range (making-date
                                    axis — registration dates of old
                                    titles are 2005–2013 back-import
                                    stamps and cannot answer
                                    making-year questions)
    max_titles=5                    cap on frl_title spawns per
                                    enumeration task (test guard)
    layer=full|asmade               capture layer: full = as-made +
                                    latest compiled anchor (default);
                                    asmade = publication-time texts
                                    only, no compilations, no ES
                                    (time-series corpus)
    comp=anchor|all                 compilation layer under layer=full:
                                    latest anchor (default) or every
                                    compilation
    gazette=0|1                     download Gazette texts too (default
                                    0: Gazette titles stay ledger-only)
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote

from adapters.base import CleanDefinition, SourceDefinition, TaskSeed

__all__ = [
    "API_BASE",
    "COMP_ALL",
    "COMP_ANCHOR",
    "CURSOR_KEY",
    "LAYER_ASMADE",
    "LAYER_FULL",
    "PAGE_SIZE",
    "SITE_BASE",
    "build_source",
    "canonical_source_url",
    "collection_doc_type",
    "odata_url",
    "start_tasks",
]

API_BASE = "https://api.prod.legislation.gov.au/v1"
SITE_BASE = "https://www.legislation.gov.au"
CURSOR_KEY = "frl_last_date"
PAGE_SIZE = 100  # server-enforced $top cap (probed: >100 → HTTP 400)

COMP_ANCHOR = "anchor"
COMP_ALL = "all"
LAYER_FULL = "full"
LAYER_ASMADE = "asmade"

#: FRL collection → cross-country doc_type (soft mapping; the FRL word is
#: always kept in meta.collection). Probed vocabulary, 2026-08-31.
_DOC_TYPES = {
    "Act": "STATUTE",
    "LegislativeInstrument": "SECONDARY_LEGISLATION",
    "NotifiableInstrument": "SECONDARY_LEGISLATION",
    "Constitution": "CONSTITUTION",
    "AdministrativeArrangementsOrder": "EXECUTIVE_ORDER",
    "PrerogativeInstrument": "EXECUTIVE_ORDER",
    "ContinuedLaw": "STATUTE",
    "Gazette": "OTHER",
}


def collection_doc_type(collection: str | None) -> str:
    return _DOC_TYPES.get(collection or "", "OTHER")


def odata_url(path: str, filter_expr: str | None = None, expand: str | None = None,
              skip: int = 0, top: int | None = PAGE_SIZE,
              select: str | None = None) -> str:
    """Build an API URL with a properly encoded OData query.

    Spaces are %20-encoded; apostrophes and time colons stay literal —
    the exact shape every probe used (``$`` left unescaped as the server
    expects it). ``top=None`` omits ``$top``: the singleton read behind
    ``$expand`` rejects any ``$top`` (probed: with it HTTP 400, without
    it 200 — the server's fifth quirk).
    """
    parts: list[str] = []
    if filter_expr:
        parts.append("$filter=" + quote(filter_expr, safe="':"))
    if expand:
        parts.append("$expand=" + expand)
    if select:
        parts.append("$select=" + select)
    if top is not None:
        parts.append(f"$top={top}")
    if skip:
        parts.append(f"$skip={skip}")
    return f"{API_BASE}{path}?" + "&".join(parts)


def canonical_source_url(title_id: str, start: str, kind: str, fmt: str,
                         as_made: bool) -> str:
    """Rebuildable website URL of one file (doc_id hashes this).

    Grammar taken from the site's own links (probed 2026-08-31):
    ``/{id}/asmade/{start}/text/original/pdf`` and the Explanatory
    Statement sibling ``/{id}/asmade/{start}/es/original/pdf``; compiled
    versions live under the ``latest`` anchor with the version start
    pinning the point in time.
    """
    anchor = "asmade" if as_made else "latest"
    section = "text" if kind == "Primary" else "es"
    ext = fmt.lower()
    return f"{SITE_BASE}/{title_id}/{anchor}/{start}/{section}/original/{ext}"


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country aus --source frl window=2026-08-27:2026-08-28\n"
        "  python cli.py collect --country aus --source frl sync=1\n"
        "  python cli.py collect --country aus --source frl made=2010-01-01:2010-12-31 layer=asmade\n"
        "  python cli.py status --country aus --source frl"
    )


def _parse_date(raw: str, label: str) -> str:
    try:
        date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None
    return raw


def _mode(params: dict[str, Any]) -> dict[str, str]:
    """Shared sweep options flowing down the task chain (seed → title →
    docs): they are part of the sweep's identity, so they belong in task
    params (task_id) rather than ambient state."""
    comp = str(params.get("comp", COMP_ANCHOR)).strip()
    if comp not in (COMP_ANCHOR, COMP_ALL):
        raise _fail(f"comp must be anchor or all (got {comp!r})")
    gazette = str(params.get("gazette", "0")).strip() in ("1", "true", "yes")
    layer = str(params.get("layer", LAYER_FULL)).strip()
    if layer not in (LAYER_FULL, LAYER_ASMADE):
        raise _fail(f"layer must be full or asmade (got {layer!r})")
    return {"comp": comp, "gazette": "1" if gazette else "0", "layer": layer}


def _max_titles(params: dict[str, Any]) -> str:
    raw = str(params.get("max_titles", "")).strip()
    if raw and not raw.isdigit():
        raise _fail(f"max_titles must be a positive integer (got {raw!r})")
    return raw


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")
    mode = _mode(params)
    max_titles = _max_titles(params)

    if params.get("made"):
        if params.get("window"):
            raise _fail("give only one of made= and window=")
        made_range = str(params["made"])
        from_str, sep, to_str = made_range.partition(":")
        if not sep or not from_str or not to_str:
            raise _fail(f"made must look like FROM:TO (got {made_range!r})")
        from_str = _parse_date(from_str.strip(), "made FROM")
        to_str = _parse_date(to_str.strip(), "made TO")
        if from_str > to_str:
            raise _fail(f"made start {from_str} is after its end {to_str}")
        made_params: dict[str, Any] = {**mode, "from": from_str, "to": to_str}
        if max_titles:
            made_params["max_titles"] = max_titles
        return [TaskSeed(type="frl_made", params=made_params)]

    if params.get("window"):
        window = str(params["window"])
        from_str, sep, to_str = window.partition(":")
        if not sep or not from_str or not to_str:
            raise _fail(f"window must look like FROM:TO (got {window!r})")
        from_str = _parse_date(from_str.strip(), "window FROM")
        to_str = _parse_date(to_str.strip(), "window TO")
    elif is_sync:
        kv = params.get("_kv", {})
        cursor = kv.get(CURSOR_KEY)
        if not cursor:
            raise _fail("sync=1 needs a previous sweep; run an initial window=… first")
        from_str = (date.fromisoformat(cursor) + timedelta(days=1)).isoformat()
        to_str = datetime.now(UTC).date().isoformat()
    else:
        raise _fail("give window=FROM:TO, made=FROM:TO, or sync=1")

    if from_str > to_str:
        raise _fail(f"window start {from_str} is after its end {to_str}")

    seeds: list[TaskSeed] = []
    day = date.fromisoformat(from_str)
    end = date.fromisoformat(to_str)
    while day <= end:
        day_params: dict[str, Any] = {**mode, "date": day.isoformat()}
        if max_titles:
            day_params["max_titles"] = max_titles
        seeds.append(TaskSeed(type="frl_day", params=day_params))
        day += timedelta(days=1)
    return seeds


#: The register's persistent entity (per ARCHITECTURE.md section 6.4 a
#: register-shaped corpus has real cross-document entities): one row per
#: title, one row per version. Marker versions (amendment in force, not
#: yet compiled) carry no document anywhere in the source, so the lineage
#: table is primary data, not derivable from documents.
DOMAIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS titles (
    title_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    collection TEXT,
    sub_collection TEXT,
    status TEXT,
    making_date TEXT,
    is_principal INTEGER,
    is_in_force INTEGER,
    year INTEGER,
    number INTEGER,
    series_type TEXT,
    latest_version_start TEXT,
    latest_documented_start TEXT,
    status_history TEXT,
    raw_path TEXT
);
CREATE TABLE IF NOT EXISTS title_versions (
    title_id TEXT NOT NULL,
    start TEXT NOT NULL,
    end TEXT,
    compilation_number TEXT,
    registered_at TEXT,
    is_current INTEGER,
    is_latest INTEGER,
    reasons TEXT,
    PRIMARY KEY (title_id, start)
);
"""

def build_source() -> SourceDefinition:
    from adapters.aus.sources.frl.clean import CLEAN_VERSION, FrlCleanHandler
    from adapters.aus.sources.frl.day import FrlDayHandler
    from adapters.aus.sources.frl.doc import FrlDocHandler
    from adapters.aus.sources.frl.docs import FrlDocsHandler
    from adapters.aus.sources.frl.made import FrlMadeHandler
    from adapters.aus.sources.frl.title import FrlTitleHandler

    return SourceDefinition(
        name="frl",
        start_tasks=start_tasks,
        task_types={
            "frl_day": FrlDayHandler(),
            "frl_made": FrlMadeHandler(),
            "frl_title": FrlTitleHandler(),
            "frl_docs": FrlDocsHandler(),
            "frl_doc": FrlDocHandler(),
            "frl_clean": FrlCleanHandler(),
        },
        domain_schema=DOMAIN_SCHEMA,
        domain_tables=("titles", "title_versions"),
        domain_keys={"titles": ("title_id",), "title_versions": ("title_id", "start")},
        # no cookies, no tokens, no cross-task transport state (probed
        # 2026-08-31): every task is an independent keyless GET
        parallel_safe=True,
        # Cleaning rules table is deliberately EMPTY (probed 2026-08-31 and
        # 2026-10-02: FRL as-made EPUBs carry zero site decoration; the pdf
        # leg needs no routing rules — every PDF is digital-native geometry)
        clean=CleanDefinition(
            task_type="frl_clean",
            version=CLEAN_VERSION,
            targets=("frl_doc",),
        ),
    )
