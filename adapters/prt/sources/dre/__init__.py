"""Source ``dre``: task-type registry and seed generation.

Diário da República, the Portuguese state gazette (INCM), 1.ª Série by
default. Collected from the portal's JSON data services (see
docs/countries/prt/dre-zh.md). Flat document path: zero domain tables,
``documents`` is the whole ledger — issue-level rows (one gazette issue =
one document + its whole-issue PDF), plus targeted single-diploma fetches
by portal key (``doc=tipo/key``).

The portal is an OutSystems single-page application whose data services
validate two things on every POST: a public constant ``X-CSRFToken``
header (the same value the portal's own runtime uses for anonymous
visitors) and a per-action ``apiVersion`` token that rotates with every
portal release. ``moduleVersion`` is not validated (probed 2026-09-17:
any value answers data). Tokens live inside the portal's own frontend
module scripts at stable URLs, so every run starts with a short
``dre_version`` bootstrap chain that extracts them and carries them in
task params (the session-token pattern of ARCHITECTURE section 6.3).
Known trade-off (section 6.3, D2 family): after a portal release the
tokens change, so downstream task ids change and already-done windows
re-execute — idempotent upserts keep the ledger correct; the cost is a
few repeated requests per release.

Task types (each = one module with ``build_request`` + ``parse``):

===============  =====================================================
type             what one task does
===============  =====================================================
dre_version      GET one portal module script, regex-extract its data
                 action tokens; chains to the next module and, from the
                 last one, emits the per-day seeds (and ``doc=`` seeds)
dre_day          one calendar day × one série: POST the date-window
                 search (issue-level hits); registers each issue as a
                 document and seeds one dre_pdf per issue. An empty
                 result is the confirmed "no edition" answer and the
                 per-série watermark still advances. A day counts as
                 consumed (cursor push) only once its last page is done
dre_pdf          one issue: GET the PDF via the stable redirector;
                 the bytes become the issue document's primary file
dre_doc          one targeted diploma: POST the detail service
                 (Tipo + Key) — metadata, the four native dates, full
                 text and the PDF link in one response, stored verbatim
                 as doc.json (the primary file)
===============  =====================================================

Params (key=value on the CLI)::

    window=2026-09-14:2026-09-16   closed date range (or sync=1 / doc=)
    sync=1                         per-série increment: from = day after
                                   the kv cursor dre_last_date_<série>,
                                   to = *yesterday* (issues go out Lisbon
                                   morning; a pre-publication fetch answers
                                   the same empty shape as a no-edition
                                   day, so sync never claims today)
    series=I                       séries to collect, comma separated
                                   (default I; e.g. I,II — each série has
                                   its own watermark)
    doc=lei/62-2026-1168979170,... targeted single-diploma fetches by
                                   portal key (tipo lowercase + key
                                   numero-ano-dbId); combinable with a
                                   window
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "ANON_CSRF",
    "API_BASE",
    "DETAIL_ACTION",
    "DETAIL_HANDLER_TOKEN",
    "MODULE_ORDER",
    "MODULE_SCRIPTS",
    "REQUIRED_ACTIONS",
    "SEARCH_ACTION",
    "SERVICE_HEADERS",
    "build_source",
    "start_tasks",
    "tokens_for",
]

API_BASE = "https://diariodarepublica.pt"

#: The portal data layer's anonymous CSRF constant — public and identical
#: for every visitor (extracted from the portal runtime, probed 2026-09-17).
ANON_CSRF = "T6C+9iB49TLra4jEsMeSckDMNhQ="

SERVICE_HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Accept": "application/json",
    "X-CSRFToken": ANON_CSRF,
    "Origin": API_BASE,
    "Referer": f"{API_BASE}/dr/pesquisa",
}

SEARCH_ACTION = "dr/Pesquisas/PesquisaResultado/DataActionGetPesquisas"
DETAIL_ACTION = "dr/Legislacao_Conteudos/Conteudo_Detalhe/DataActionGetAllConteudoDetalheData"

#: Bootstrap chain: each module script is fetched once per run; its data
#: action tokens are regex-extracted (callDataAction("<name>",
#: "screenservices/...", "<token>")). The last module's parse emits the
#: working seeds.
MODULE_ORDER: tuple[str, ...] = ("pesquisa", "detalhe")
MODULE_SCRIPTS: dict[str, str] = {
    "pesquisa": f"{API_BASE}/dr/scripts/dr.Pesquisas.PesquisaResultado.mvc.js",
    "detalhe": f"{API_BASE}/dr/scripts/dr.Legislacao_Conteudos.Conteudo_Detalhe.mvc.js",
}
REQUIRED_ACTIONS: dict[str, str] = {
    "pesquisa": "DataActionGetPesquisas",
    "detalhe": "DataActionGetAllConteudoDetalheData",
}
_VIEW_NAMES: dict[str, str] = {
    "pesquisa": "Pesquisas.PesquisaResultado",
    "detalhe": "Legislacao_Conteudos.Conteudo_Detalhe",
}

_TOKEN_RE = re.compile(
    r'callDataAction\("([A-Za-z0-9_]+)", "screenservices/[^"]+", "([A-Za-z0-9+/=_-]{20,30})"'
)

DETAIL_HANDLER_TOKEN = "detalhe"


def tokens_for(module: str, js: str) -> dict[str, str]:
    """Extract {action name: apiVersion token} from one module script."""
    found = {name: token for name, token in _TOKEN_RE.findall(js)}
    needed = REQUIRED_ACTIONS[module]
    if needed not in found:
        raise ValueError(
            f"dre_version {module}: token for {needed!r} not found in the portal "
            "module script — the portal layout likely changed and the pack "
            "needs updating"
        )
    return found


def view_name(module: str) -> str:
    return _VIEW_NAMES[module]


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country prt --source dre window=2026-09-14:2026-09-16\n"
        "  python cli.py collect --country prt --source dre sync=1\n"
        "  python cli.py collect --country prt --source dre window=2026-09-14:2026-09-16 series=I,II\n"
        "  python cli.py collect --country prt --source dre doc=lei/62-2026-1168979170\n"
        "  python cli.py status --country prt --source dre"
    )


def _parse_date(raw: str, label: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None


def _parse_series(raw: str) -> list[str]:
    parts = [p.strip().upper() for p in raw.split(",") if p.strip()]
    if not parts or any(p not in ("I", "II") for p in parts):
        raise _fail("series must be a comma-separated list of I / II (e.g. I or I,II)")
    if len(parts) != len(set(parts)):
        raise _fail(f"series repeats a série (got {raw!r})")
    return parts


def _parse_docs(raw: str) -> list[dict[str, str]]:
    docs: list[dict[str, str]] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        tipo, sep, key = chunk.partition("/")
        if not sep or not tipo or not key:
            raise _fail(f"doc entries must look like tipo/key (got {chunk!r})")
        tipo, key = tipo.strip().lower(), key.strip().lower()
        if not re.fullmatch(r"[a-z0-9-]+", tipo) or not re.fullmatch(r"[a-z0-9-]+", key):
            raise _fail(f"doc tipo/key may only contain a-z 0-9 - (got {chunk!r})")
        docs.append({"tipo": tipo, "key": key})
    return docs


def _yesterday() -> date:
    """The last day sync may claim.

    Issues go out Lisbon morning; a pre-publication fetch answers the
    same empty shape as a no-edition day, so sync never claims *today* —
    the two states are indistinguishable at the response level.
    """
    return datetime.now(UTC).date() - timedelta(days=1)


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    series = _parse_series(str(params.get("series", "I")))
    docs = _parse_docs(str(params["doc"])) if params.get("doc") else []

    ranges: dict[str, tuple[date, date]] = {}
    if params.get("window"):
        window = str(params["window"])
        from_str, sep, to_str = window.partition(":")
        if not sep or not from_str or not to_str:
            raise _fail(f"window must look like FROM:TO (got {window!r})")
        from_date = _parse_date(from_str.strip(), "window FROM")
        to_date = _parse_date(to_str.strip(), "window TO")
        if from_date > to_date:
            raise _fail(f"window start {from_date} is after its end {to_date}")
        ranges = {serie: (from_date, to_date) for serie in series}
    elif str(params.get("sync", "")).strip() in ("1", "true", "yes"):
        kv = params.get("_kv", {})
        yesterday = _yesterday()
        for serie in series:
            cursor = kv.get(f"dre_last_date_{serie}")
            if not cursor:
                raise _fail(
                    f"sync=1 needs a previous sweep for série {serie}; run an "
                    "initial window=… first (kv cursor dre_last_date_"
                    f"{serie} is missing)"
                )
            from_date = date.fromisoformat(str(cursor)) + timedelta(days=1)
            if from_date <= yesterday:
                ranges[serie] = (from_date, yesterday)
    elif not docs:
        raise _fail("give window=FROM:TO, sync=1, or doc=tipo/key")

    if not ranges and docs:
        # Targeted fetches only: the bootstrap still runs (tokens needed)
        # but no day seeds are generated.
        ranges = {}

    spec = {
        "ranges": {serie: [frm.isoformat(), to.isoformat()] for serie, (frm, to) in ranges.items()},
        "docs": docs,
    }
    return [
        TaskSeed(
            type="dre_version",
            params={"module": MODULE_ORDER[0], "tok": {}, "spec": spec},
        )
    ]


def build_source() -> SourceDefinition:
    from adapters.prt.sources.dre.day import DreDayHandler
    from adapters.prt.sources.dre.doc import DreDocHandler
    from adapters.prt.sources.dre.pdf import DrePdfHandler
    from adapters.prt.sources.dre.version import DreVersionHandler

    return SourceDefinition(
        name="dre",
        start_tasks=start_tasks,
        task_types={
            "dre_version": DreVersionHandler(),
            "dre_day": DreDayHandler(),
            "dre_doc": DreDocHandler(),
            "dre_pdf": DrePdfHandler(),
        },
    )
