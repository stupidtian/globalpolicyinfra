"""The dof source: task-type registry and seed generation.

Diario Oficial de la Federación, the Mexican federal gazette — laws,
decretoos, acuerdos, circulares and the rest of the day's issue as the
federal government publishes them. Flat document path: zero domain
tables, ``documents`` is the whole ledger (see docs/countries/mex/dof-zh.md).

The site serves no JSON API (the 2015-era ``WS_*`` web services answer
404 since the redesign, probed 2026-09-14); the date-addressed edition
page IS the machine interface. Two task types (each = one module with
``build_request`` + ``parse``):

===============  =====================================================
type             what one task does
===============  =====================================================
dof_index        one (calendar day, edición) pair: GET the date-
                 addressed edition page ``index.php?year&month&day&
                 edicion``. The page's own ``Fecha: DD/MM/YYYY -
                 Edición X`` header must echo the requested day or the
                 parse refuses to collect (the site never 404s here);
                 every ``a.enlaces`` row (whose ``fecha`` must equal the
                 header date too — the page also carries visit-tracking
                 ``enlaces_leido`` twins with a bogus 1926 year, probed
                 2026-09-14) becomes a dof_nota seed carrying its
                 departamento / organismo / sección. A no-edition
                 (day, edición) pair answers the same page chrome with
                 no Fecha header and no rows — an explained empty that
                 still advances that edition's watermark.
dof_nota         one gazette entry: GET the canonical note page
                 ``nota_detalle.php?codigo&fecha``; registers the
                 document and stores the response bytes verbatim as
                 the nota.html primary file.
===============  =====================================================

Params (key=value on the CLI)::

    window=2026-09-09:2026-09-11   closed date range (required, or sync=1)
    sync=1                          from = day after the kv cursor
                                    dof_last_<edicion>, to = *yesterday*
                                    (the matutina is published
                                    Mexico-City morning; a pre-publication
                                    fetch answers like a no-edition day)
    ediciones=MAT                   comma-separated edition codes to sweep
                                    (MAT matutina, VES vespertina; default
                                    MAT). Each edition gets its own
                                    watermark key, so widening later just
                                    starts that stream fresh.
    tipos=normativo                 keep only notes whose native title type
                                    word is in the set — ``normativo``
                                    expands to the pack's normative preset
                                    (decrees, leyes, acuerdos, resoluciones,
                                    circulares, NOMs, reglamentos, reglas,
                                    tratados); or give an explicit
                                    comma-separated list. Omit for
                                    everything the gazette carries. The
                                    resolved list travels in the index
                                    task params, so widening later re-walks
                                    the editions (1 request/day) and pulls
                                    only the newly-kept notes; already-
                                    fetched notes are never re-fetched.

Note on reachability: dof.gob.mx sits on SEGOB's own Telmex address
space and is unreachable from some networks (probed 2026-09-14: the
site answers HTTP 200 from US/EU vantage points while the collection
host's route to the whole 187.218.29.0/24 block times out). The
transport is plain requests; where a proxy is the answer, standard
``HTTPS_PROXY`` works with zero code changes.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "BASE_URL",
    "CURSOR_PREFIX",
    "NORMATIVE_TIPOS",
    "build_source",
    "cursor_key",
    "parse_ediciones",
    "parse_tipos",
    "start_tasks",
]

BASE_URL = "https://dof.gob.mx"

#: Watermark keys are per edition stream: dof_last_mat / dof_last_ves.
CURSOR_PREFIX = "dof_last_"

#: The ``tipos=normativo`` preset: the gazette's native type words for
#: enacted regulatory instruments (decrees, statutes, agency agreements,
#: resolutions, circulars, official standards, regulations, rules,
#: treaties). Everything else the gazette carries (registry extracts,
#: rate-table publications, judicial notices, auction/assembly calls,
#: annex tables, drafts) is out of this scope. Resolved into an explicit
#: comma list at seed time so the task identity is self-describing;
#: widening later = new task identity = automatic re-fetch of the delta.
NORMATIVE_TIPOS = (
    "ACUERDO",
    "CIRCULAR",
    "DECRETO",
    "LEY",
    "NOM",
    "NORMA",
    "REGLAMENTO",
    "REGLAS",
    "RESOLUCION",
    "TRATADO",
)


def parse_tipos(raw: str) -> str:
    """``normativo`` expands to the preset; otherwise an explicit list."""
    value = raw.strip()
    if not value:
        return ""
    if value.lower() == "normativo":
        return ",".join(NORMATIVE_TIPOS)
    parts = [p.strip().upper() for p in value.split(",") if p.strip()]
    if not parts:
        raise _fail("tipos must be 'normativo' or a comma-separated list of type words")
    for p in parts:
        if not p.isalpha():
            raise _fail(f"tipo words must be alphabetic (got {p!r})")
    return ",".join(parts)


def cursor_key(edicion: str) -> str:
    return CURSOR_PREFIX + edicion.strip().lower()


def parse_ediciones(raw: str) -> list[str]:
    parts = [p.strip().upper() for p in raw.split(",") if p.strip()]
    if not parts:
        raise _fail("ediciones must be a comma-separated list (e.g. MAT or MAT,VES)")
    for p in parts:
        if not p.isalpha():
            raise _fail(f"edicion codes must be alphabetic (got {p!r})")
    return parts


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country mex --source dof window=2026-09-09:2026-09-11\n"
        "  python cli.py collect --country mex --source dof sync=1\n"
        "  python cli.py collect --country mex --source dof window=2026-09-09:2026-09-11 ediciones=MAT,VES\n"
        "  python cli.py status --country mex --source dof"
    )


def _parse_date(raw: str, label: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")
    ediciones = parse_ediciones(str(params.get("ediciones", "MAT")))
    tipos = parse_tipos(str(params.get("tipos", "")))

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
        starts = []
        for ed in ediciones:
            cursor = kv.get(cursor_key(ed))
            if not cursor:
                raise _fail(
                    f"sync=1 needs a previous sweep for edition {ed}; "
                    "run an initial window=… first"
                )
            starts.append(date.fromisoformat(cursor) + timedelta(days=1))
        from_date = min(starts)
        # Never claim *today*: the matutina is generated Mexico-City morning,
        # and a pre-publication fetch answers like a no-edition day.
        to_date = datetime.now(UTC).date() - timedelta(days=1)
        if from_date > to_date:
            return []  # already in sync — nothing due
    else:
        raise _fail("give window=FROM:TO or sync=1")

    seeds: list[TaskSeed] = []
    day = from_date
    while day <= to_date:
        for ed in ediciones:
            seed_params: dict[str, Any] = {"date": day.isoformat(), "edicion": ed}
            if tipos:
                seed_params["tipos"] = tipos
            seeds.append(TaskSeed(type="dof_index", params=seed_params))
        day += timedelta(days=1)
    return seeds


def build_source() -> SourceDefinition:
    from adapters.mex.sources.dof.index import DofIndexHandler
    from adapters.mex.sources.dof.nota import DofNotaHandler

    return SourceDefinition(
        name="dof",
        start_tasks=start_tasks,
        task_types={
            "dof_index": DofIndexHandler(),
            "dof_nota": DofNotaHandler(),
        },
        # DOF is a plain public gazette: stateless GETs, no session or
        # cross-task transport state — safe on any worker with any session
        # (framework-concurrency ruling 1.4).
        parallel_safe=True,
    )
