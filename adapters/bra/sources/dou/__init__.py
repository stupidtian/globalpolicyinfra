"""The dou source: task-type registry and seed generation.

Diário Oficial da União, the Brazilian federal gazette — section 1 (the
finished federal normative acts: leis, decretos, portarias, resoluções…)
plus its extra editions. Flat document path: zero domain tables,
``documents`` is the whole ledger (see docs/countries/bra/dou-zh.md).

The portal serves no JSON API for enumeration; the date-and-section
addressed *reading page* IS the machine interface — its ``#params``
element carries a JSON payload with the day's whole item list (title,
text snippet, issuing-agency hierarchy, edition, page, native type,
slug). Two task types (each = one module with ``build_request`` +
``parse``):

===============  =====================================================
type             what one task does
===============  =====================================================
dou_leitura      one (calendar day, seção) pair: GET the reading page
                 ``leiturajornal?secao&data`` and turn every kept item
                 into a dou_artigo seed. A day with no edition answers
                 HTTP 200 with an empty ``jsonArray`` and all-false
                 ``typeNormDay`` flags — an explained empty that still
                 advances that seção's watermark. Extra editions are a
                 first-class stream: some days publish the *entire*
                 section as an extra (2021-04-01: DO1_EXTRA_F carried
                 Lei 14.133/2021 while DO1 answered zero), so do1 and
                 do1e are swept together by default and each seção
                 keeps its own watermark.
dou_artigo       one gazette entry: GET the detail page
                 ``/web/dou/-/{urlTitle}`` (server-rendered HTML with
                 stable classes; the full as-published text lives in
                 ``p.dou-paragraph`` blocks); registers the document
                 and stores the response bytes verbatim as the
                 doc.html primary file.
===============  =====================================================

Params (key=value on the CLI)::

    window=2026-10-01:2026-10-02   closed date range (required, or sync=1)
    sync=1                          from = day after each seção's
                                    dou_last_<secao> cursor, to =
                                    *yesterday* (the gazette is generated
                                    Brasília-morning; a pre-publication
                                    fetch answers like a no-edition day)
    secoes=do1,do1e                 comma-separated seção codes to sweep
                                    (default do1,do1e; do2/do2e/do3/do3e
                                    available). Each seção gets its own
                                    watermark, so widening later just
                                    starts that stream fresh.
    tipos=normativo                 artType scope (default = the pack's
                                    normative preset: leis, medidas
                                    provisórias, emendas constitucionais,
                                    decretos, portarias, resoluções,
                                    instruções normativas, atos
                                    normativos, retificações — ~50% of
                                    the section's volume; the rest is
                                    procedural/judicial residue).
                                    ``all`` = keep everything section 1
                                    carries; or an explicit comma-
                                    separated list. The resolved list
                                    travels in the leitura task params,
                                    so widening later re-walks the days
                                    (1 request/day/seção) and pulls only
                                    the newly-kept items; already-fetched
                                    artigos are never re-fetched.

Reachability: in.gov.br sits behind an edge that resets plain
connections from some networks (probed 2026-10-02: direct China-bound
routes die at the HTTP layer regardless of client fingerprint, a Hong
Kong datacenter exit is refused, a US exit works). The transport is
plain requests; where a proxy is the answer, standard ``HTTPS_PROXY``
works with zero code changes.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from adapters.base import CleanDefinition, SourceDefinition, TaskSeed

__all__ = [
    "BASE_URL",
    "CURSOR_PREFIX",
    "NORMATIVO_TIPOS",
    "SECOES",
    "build_source",
    "cursor_key",
    "parse_secoes",
    "parse_tipos",
    "start_tasks",
]

BASE_URL = "https://www.in.gov.br"

#: Known seção codes of the gazette (lowercase, as the reading page takes
#: them). do1/do2/do3 are the regular sections; the ``e`` suffixes are the
#: extra-edition families — a whole regular edition may be published as an
#: extra (probed 2026-10-02 and on 2021-04-01), so do1+do1e are the
#: default pair.
SECOES = ("do1", "do1e", "do2", "do2e", "do3", "do3e")

#: Watermark keys are per seção stream: dou_last_do1 / dou_last_do1e / …
CURSOR_PREFIX = "dou_last_"

#: The default collection scope (``tipos=normativo``): the gazette's
#: native type words for normative instruments — statutes (leis, medidas
#: provisórias, emendas constitucionais), decrees, the administrative
#: normative workhorses (portarias incl. conjunta/interministerial,
#: resoluções, instruções normativas, atos normativos) and retificações
#: (corrections of previously published acts — needed to track amendments
#: to already-collected items). Everything else section 1 carries
#: (despachos, pautas, acórdãos, atas, decisões…) is procedural/judicial
#: residue and stays out — ~50% of the section's volume, probed over the
#: 2026-10-02 + 2021-04-01 trial days. Resolved into an explicit comma
#: list at seed time so the task identity is self-describing; widening
#: later = new task identity = automatic re-fetch of the delta
#: (already-fetched artigos are never re-fetched).
NORMATIVO_TIPOS = (
    "Lei",
    "Medida Provisória",
    "Emenda Constitucional",
    "Decreto",
    "Portaria",
    "Resolução",
    "Instrução Normativa",
    "Ato Normativo",
    "Retificação",
)


def parse_secoes(raw: str) -> list[str]:
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    if not parts:
        raise _fail("secoes must be a comma-separated list (e.g. do1,do1e)")
    for p in parts:
        if p not in SECOES:
            raise _fail(
                f"unknown secao {p!r} (known: {','.join(SECOES)})"
            )
    return parts


def parse_tipos(raw: str) -> str:
    """Resolve the tipos scope: default/``normativo`` -> the preset;
    ``all`` -> no filter (everything section 1 carries); otherwise an
    explicit comma-separated list of artType words."""
    value = raw.strip()
    if not value or value.lower() == "normativo":
        return ",".join(NORMATIVO_TIPOS)
    if value.lower() == "all":
        return ""
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if not parts:
        raise _fail("tipos must be 'normativo', 'all', or a comma-separated list of artType words")
    return ",".join(parts)


def cursor_key(secao: str) -> str:
    return CURSOR_PREFIX + secao.strip().lower()


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country bra --source dou window=2026-10-01:2026-10-02\n"
        "  python cli.py collect --country bra --source dou sync=1\n"
        "  python cli.py collect --country bra --source dou window=2026-10-01:2026-10-02 secoes=do1,do1e,do2\n"
        "  python cli.py collect --country bra --source dou window=2026-10-01:2026-10-02 tipos=normativo\n"
        "  python cli.py status --country bra --source dou"
    )


def _parse_date(raw: str, label: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")
    secoes = parse_secoes(str(params.get("secoes", "do1,do1e")))
    tipos = parse_tipos(str(params.get("tipos", "")))
    starts: dict[str, date] = {}

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
        for secao in secoes:
            cursor = kv.get(cursor_key(secao))
            if not cursor:
                raise _fail(
                    f"sync=1 needs a previous sweep for seção {secao}; "
                    "run an initial window=… first"
                )
            starts[secao] = date.fromisoformat(cursor) + timedelta(days=1)
        from_date = min(starts.values())
        # Never claim *today*: the gazette is generated Brasília-morning,
        # and a pre-publication fetch answers like a no-edition day.
        to_date = datetime.now(UTC).date() - timedelta(days=1)
        if from_date > to_date:
            return []  # already in sync — nothing due
    else:
        raise _fail("give window=FROM:TO or sync=1")

    seeds: list[TaskSeed] = []
    day = from_date
    while day <= to_date:
        for secao in secoes:
            if is_sync and day < starts[secao]:
                continue  # this seção's stream already consumed past that day
            seed_params: dict[str, Any] = {"date": day.isoformat(), "secao": secao}
            if tipos:
                seed_params["tipos"] = tipos
            seeds.append(TaskSeed(type="dou_leitura", params=seed_params))
        day += timedelta(days=1)
    return seeds


def build_source() -> SourceDefinition:
    from adapters.bra.sources.dou.artigo import DouArtigoHandler
    from adapters.bra.sources.dou.clean import CLEAN_VERSION, DouCleanHandler
    from adapters.bra.sources.dou.leitura import DouLeituraHandler

    return SourceDefinition(
        name="dou",
        start_tasks=start_tasks,
        task_types={
            "dou_leitura": DouLeituraHandler(),
            "dou_artigo": DouArtigoHandler(),
            "dou_clean": DouCleanHandler(),
        },
        # The as-published text rides the server-rendered article page's
        # own container (#materia) — four furniture divs with stable
        # classes dropped around it (clean-plan.md §1; probed 2026-10-19,
        # 300-doc survey). A version bump reseeds every cleaned document.
        clean=CleanDefinition(
            task_type="dou_clean",
            version=CLEAN_VERSION,
            targets=("dou_artigo",),
        ),
        # The reading pages and detail pages are stateless public GETs:
        # no session, no cookies, no cross-task transport state — safe on
        # any worker with any session (framework-concurrency ruling 1.4).
        # The layout-PDF channel (not collected by this pack) would be
        # session-bound; if it is ever added, revisit this flag.
        parallel_safe=True,
    )
