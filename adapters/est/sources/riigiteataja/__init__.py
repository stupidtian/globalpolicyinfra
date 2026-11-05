"""The riigiteataja source: task-type registry and seed generation.

Riigi Teataja (riigiteataja.ee) is Estonia's official gazette — the sole
legally mandated publication venue for Estonian legislation, operated by
the Ministry of Justice and Digital Affairs and purely electronic since
2010 (institutional landscape probed 2026-10-27 with two independent
sources; samples in the task folder; see docs/countries/est/
riigiteataja-zh.md). The as-published layer (algtekst) and the officially
consolidated layer (terviktekst) share one site and one version-granular
inventory, addressed here as a registry-shaped flat source: zero domain
tables, one document per published version (globaalID). Three task types:

=================  =====================================================
type               what one task does
=================  =====================================================
rt_sweep           one page of the version inventory
                   (``GET /api/oigusakt_otsing/1/otsi``, 500 rows/page
                   server cap, stable default order). Rows carry
                   globaalID, issuer, native type, validity and the
                   ``muudetud`` update stamp inline and yield one
                   ``rt_act`` seed each (with ``muudetud`` as the
                   reopen signal). scope=state drops municipal
                   issuers at row level. A non-tail page continues
                   via a same-type seed for the next page.
rt_act             one document version: ``GET /public-api/api/v1/
                   akt/{globaalID}/blob-xml`` — the full Juurakt-
                   schema XML carrying the complete bibliographic
                   block (adoption, promulgation, publication mark,
                   validity, version, amendment marks) and the body
                   in one request. The XML is stored verbatim as the
                   primary file; all metadata is parsed out of it.
rt_classifiers     ``GET /public-api/api/v1/avalik/klassifikaatorid/
                   alg-tekstid`` — the issuer/type classifier
                   (648 issuers, 529 flagged municipal), archived
                   once as the scope filter's reference snapshot.
=================  =====================================================

Params (key=value on the CLI)::

    pages=1:2                      sweep page range (or pages=3: from
                                   page 3 to the empty tail)
    dokument=seadus                optional native-type filter (free
                                   text; unknown values answer a clean
                                   empty inventory)
    refresh=2026-10-27T00:00:00Z   optional identity changer: registry
                                   sources have no date cursor, a sync
                                   re-walks the inventory under a new
                                   task identity and per-row ``muudetud``
                                   signals reopen only changed documents
    scope=state                    which issuers to keep: state = all
                                   state-level issuers (default;
                                   municipal issuers filtered out), all
                                   = everything. The scope travels in
                                   the sweep-task params, so widening
                                   it later means new task identities
                                   and an automatic backfill.

Transport note (probed 2026-10-27): www.riigiteataja.ee sits behind a
Cloudflare WAF whose UA rule rejects a specific legacy set site-wide with
403 — the framework's default Chrome/120.0.0.0 UA and curl are blocked,
python-requests' own UA and a modern Chrome UA pass. Every request in this
source therefore overrides the UA via ``REQUEST_HEADERS`` (a RequestSpec
headers field, not a framework change); first trial run failed 2/2 tasks
on the default UA and was rerun after the override.
"""

from __future__ import annotations

from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "API_BASE",
    "CURSORLESS_NOTE",
    "DEFAULT_PAGE_SIZE",
    "LAYERS",
    "PUBLIC_API_BASE",
    "REQUEST_HEADERS",
    "SITE_BASE",
    "build_source",
    "is_court_issuer",
    "is_municipal_issuer",
    "site_url_for",
    "start_tasks",
]

API_BASE = "https://www.riigiteataja.ee"
PUBLIC_API_BASE = f"{API_BASE}/public-api/api/v1"
SITE_BASE = "https://www.riigiteataja.ee"

#: The site's Cloudflare WAF rejects a specific legacy-UA set site-wide with
#: 403 (probed 2026-10-27: the framework's default Chrome/120.0.0.0 UA and
#: curl both blocked; python-requests' own UA and a modern Chrome UA both
#: pass — an upstream UA rule, not a TLS-fingerprint block). Every request
#: therefore overrides the transport default with this modern UA; the value
#: rides in the RequestSpec headers (a contract field), never in task
#: params.
REQUEST_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}

#: Server-enforced page cap — one more returns a loud 400 with the reason
#: ("Suurim tagastatav tulemuste arv on 500", probed 2026-10-27).
DEFAULT_PAGE_SIZE = 500

#: The one-line incremental semantics of a registry-shaped source: no date
#: cursor exists (the inventory is not date-partitioned); sync re-walks the
#: listing under a fresh refresh identity and per-row signals reopen only
#: changed documents (section 6.5 refresh mode, KOR/AUS precedent).
CURSORLESS_NOTE = (
    "registry-shaped source: give refresh=<timestamp> to re-walk the "
    "inventory; per-row muudetud signals reopen only changed documents"
)

#: Municipal-issuer markers (case-insensitive containment). Estonian
#: municipal bodies are named <name> Vallavolikogu / Linnavolikogu
#: (council) or <name> Vallavalitsus / Linnavalitsus (government); the
#: three compounds are unambiguous — the state government is "Vabariigi
#: Valitsus", which contains none of them. Historical municipalities
#: (pre-2017 reform, e.g. Kärdla Linnavolikogu) use the same compounds,
#: so no name list is needed. Verified 2026-10-27 against the source's
#: own classifier (529 issuers flagged kov=true) with an 84/84 sample
#: match; the classifier snapshot is archived by rt_classifiers for audit.
MUNICIPAL_MARKERS: tuple[str, ...] = (
    "volikogu",
    "vallavalitsus",
    "linnavalitsus",
)


def is_municipal_issuer(issuer: str) -> bool:
    """True when the issuer names a municipal body (scope=state filters
    these out — brief boundary: no municipal regulations)."""
    lowered = issuer.strip().lower()
    return any(marker in lowered for marker in MUNICIPAL_MARKERS)


def is_court_issuer(issuer: str) -> bool:
    """True when the issuer names a court. Court decisions ride in the
    algtekst search corpus (probed 2026-11-05: keyword searches surface
    Riigikohtu rows) but are out of scope here — every Estonian court is
    named <...> Kohus (nominative, e.g. Harju Maakohus) or appears in a
    genitive/compound form Riigi-kohtu / maakohu-tu, so the two
    substrings ``kohus`` and ``kohtu`` cover the whole declension while
    matching no non-court state body (the Ministry of Justice is
    Justiitsministeerium)."""
    lowered = issuer.strip().lower()
    return "kohus" in lowered or "kohtu" in lowered


def site_url_for(globaal_id: str) -> str:
    """The canonical, rebuildable site address of one act version (the
    form the source itself writes into the XML ``aktViide`` field,
    upgraded to https)."""
    return f"{SITE_BASE}/akt/{globaal_id}"


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country est --source riigiteataja pages=1:2\n"
        "  python cli.py collect --country est --source riigiteataja refresh=2026-10-27T00:00:00Z\n"
        "  python cli.py collect --country est --source riigiteataja pages=1:2 dokument=seadus\n"
        "  python cli.py collect --country est --source riigiteataja layer=algtekst offsets=0:300\n"
        "  python cli.py collect --country est --source riigiteataja layer=algtekst\n"
        "  python cli.py status --country est --source riigiteataja\n"
        f"  ({CURSORLESS_NOTE})"
    )


def _parse_pages(raw: str) -> tuple[int, int | None]:
    """``A:B`` (closed range) or ``A`` (from A to the empty tail)."""
    from_str, sep, to_str = raw.partition(":")
    try:
        start = int(from_str.strip())
    except ValueError:
        raise _fail(f"pages must look like A:B or A (got {raw!r})") from None
    if start < 1:
        raise _fail(f"pages start must be >= 1 (got {raw!r})")
    if not sep:
        return start, None
    if not to_str.strip():
        return start, None
    try:
        end = int(to_str.strip())
    except ValueError:
        raise _fail(f"pages must look like A:B or A (got {raw!r})") from None
    if end < start:
        raise _fail(f"pages start {start} is after its end {end}")
    return start, end


def _parse_scope(raw: str) -> str:
    scope = raw.strip().lower()
    if scope not in ("state", "all"):
        raise _fail("scope must be 'state' (state-level issuers only, default) or 'all'")
    return scope


def _parse_offsets(raw: str) -> tuple[int, int | None]:
    """``A:B`` (walk offsets A .. B exclusive) or ``A`` (to the empty tail)."""
    from_str, sep, to_str = raw.partition(":")
    try:
        start = int(from_str.strip())
    except ValueError:
        raise _fail(f"offsets must look like A:B or A (got {raw!r})") from None
    if start < 0:
        raise _fail(f"offsets start must be >= 0 (got {raw!r})")
    if not sep or not to_str.strip():
        return start, None
    try:
        end = int(to_str.strip())
    except ValueError:
        raise _fail(f"offsets must look like A:B or A (got {raw!r})") from None
    if end <= start:
        raise _fail(f"offsets end {end} must be after its start {start}")
    return start, end


#: Text layers of the source. "current" (default) walks the version
#: inventory (rt_sweep, one row per version ever in force — consolidated
#: texts included); "algtekst" walks the as-published layer (rt_alglist,
#: one row per adoption-time original). The two are complementary, not
#: alternatives: the same unamended act resolves to the same document id
#: in both channels and the engine dedupes it.
LAYERS: tuple[str, ...] = ("current", "algtekst")


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    scope = _parse_scope(str(params.get("scope", "state")))
    layer = str(params.get("layer", "current")).strip().lower()
    if layer not in LAYERS:
        raise _fail(f"layer must be one of {'/'.join(LAYERS)} (got {layer!r})")
    refresh = str(params.get("refresh", "")).strip()

    if layer == "algtekst":
        if "pages" in params:
            raise _fail("pages belongs to the current layer; give offsets= for layer=algtekst")
        if params.get("dokument"):
            raise _fail("dokument belongs to the current layer (the algtekst search has no type filter)")
        if "offsets" in params:
            offsets_raw = str(params["offsets"]).strip()
            if not offsets_raw:
                raise _fail("offsets must look like A:B or A (got an empty value)")
            start, end = _parse_offsets(offsets_raw)
        else:
            # no offsets = the full walk: offset 0 until the empty tail
            start, end = 0, None
        list_params: dict[str, Any] = {"scope": scope}
        if refresh:
            list_params["refresh"] = refresh
        if end is not None:
            list_params["offsets_end"] = str(end)
        return [
            TaskSeed(type="rt_alglist", params={**list_params, "offset": str(start)}),
            TaskSeed(type="rt_classifiers", params={}),
        ]

    if "offsets" in params:
        raise _fail("offsets belongs to layer=algtekst; give pages= for the current layer")

    sweep_params: dict[str, Any] = {"scope": scope}
    if params.get("dokument"):
        dokument = str(params["dokument"]).strip()
        if not dokument:
            raise _fail("dokument must be a non-empty native type (e.g. seadus)")
        sweep_params["dokument"] = dokument
    if refresh:
        sweep_params["refresh"] = refresh

    if "pages" in params:
        pages_raw = str(params["pages"]).strip()
        if not pages_raw:
            raise _fail("pages must look like A:B or A (got an empty value)")
        start, end = _parse_pages(pages_raw)
    else:
        start, end = 1, None
    if end is not None:
        sweep_params["pages_end"] = str(end)

    seeds = [
        TaskSeed(type="rt_sweep", params={**sweep_params, "page": str(start)}),
        TaskSeed(type="rt_classifiers", params={}),
    ]
    return seeds


def build_source() -> SourceDefinition:
    from adapters.est.sources.riigiteataja.act import ActHandler
    from adapters.est.sources.riigiteataja.alg import AlgListHandler
    from adapters.est.sources.riigiteataja.classifiers import ClassifiersHandler
    from adapters.est.sources.riigiteataja.sweep import SweepHandler

    return SourceDefinition(
        name="riigiteataja",
        start_tasks=start_tasks,
        task_types={
            "rt_sweep": SweepHandler(),
            "rt_act": ActHandler(),
            "rt_alglist": AlgListHandler(),
            "rt_classifiers": ClassifiersHandler(),
        },
        parallel_safe=True,  # key-free stateless APIs, no cookies (probed 2026-10-27)
    )
