"""The govza source: task-type registry and seed generation.

The documents portal of the South African government website
(``www.gov.za/document``, probed 2026-10-10, samples in the task
folder; see docs/countries/zaf/govza-zh.md). The portal is the official
web channel mirroring the Government Gazette — the listing rows carry
the gazette numbers (``G. 51889``, ``RG 11783``) and notice numbers
(``GeN 2930``) that anchor every entry to its printed issue — plus the
other policy layers of the portal: Acts, Bills, draft bills, green and
white papers. One flat document-shaped source: zero domain tables,
documents only.

Task types:

===============  =====================================================
type             what one task does
===============  =====================================================
govza_list       one slice of the date-filtered listing
                 (``GET /document`` with server-side
                 ``field_gcisdoc_document_date[min/max]``): one
                 publication date (``date``) per task, 30 rows per page,
                 continued by same-type seeds while a page comes back
                 full. Rows carry href, title, document date, document
                 type and gazette codes inline and yield one detail seed
                 each. An exhausted page (or the portal's clean "No
                 Results" answer — weekends, no-gazette days, pages past
                 the end) is a fully consumed day: explained empty and
                 the day cursor advances.
govza_detail     one document record: ``GET`` the document's own page
                 (``/documents/{type}/{slug}``). Registers the document
                 (title/date/type from the listing row — the detail page
                 itself repeats none of them reliably), extracts the
                 attached PDF links and seeds govza_file for the primary
                 one. A page without any PDF (the early non-gazette
                 layers, e.g. 1995 white papers: probed sample
                 detail-1995-wp.html) stores its own HTML as the primary
                 file — the inline body in ``div.field--name-body`` is
                 that document's only carrier.
govza_file       one PDF fetch (the document page's first ``.pdf`` link,
                 under ``/sites/default/files/gcis_document/…``). The
                 bytes must start with the ``%PDF`` magic — anything
                 else dies loud.
govza_clean      one collected document → plain text: format sniff
                 (PDF → scan floor → geometry channel; HTML → the
                 ``div.field--name-body`` whitelist), per the AUS FRL
                 mixed-carrier precedent.
===============  =====================================================

Params (key=value on the CLI)::

    window=2025-01-06:2025-01-10   closed publication-date range (or…)
    sync=1                          from = day after the kv cursor
                                    govza_last_date, to = *yesterday*
                                    (the day's items may not be posted yet)
    scope=policy                    which document types to keep: policy
                                    = everything except Tenders and
                                    Annual reports (default), all =
                                    everything. The scope travels in the
                                    list-task params, so widening it
                                    later means new task identities and
                                    an automatic backfill — no ledger
                                    surgery.
    types=notices,acts              exact document-type selection (comma
                                    list out of TYPE_SLUGS, row-level
                                    filter) — instead of scope=. Travels
                                    in the list-task params the same
                                    way; mutually exclusive with scope=

Publication date is the portal's own document-date field
(``field_gcisdoc_document_date``), the axis the date filter runs on. It
normally equals the date printed in the gazette PDF itself (verified on
the 2025/2005 samples, 2026-10-10); individual retro-digitised records
carry data-entry errors (one 2000-era sample says 2000-01-06 while its
gazette G. 23798 is printed 6 September 2002) — the gazette codes travel
in meta so the cleaning stage can reconcile.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from adapters.base import CleanDefinition, SourceDefinition, TaskSeed

__all__ = [
    "BASE_URL",
    "CURSOR_KEY",
    "DOC_TYPE_MAP",
    "DOC_TYPE_NAMES",
    "LIST_URL",
    "POLICY_EXCLUDED_TYPES",
    "TYPE_SLUGS",
    "build_source",
    "map_doc_type",
    "site_url_for",
    "slug_for",
    "start_tasks",
]

BASE_URL = "https://www.gov.za"
LIST_URL = f"{BASE_URL}/document"

CURSOR_KEY = "govza_last_date"

#: The portal's document-type taxonomy (the ``field_gcisdoc_doctype``
#: select options, probed 2026-10-10): term id → native name. The name is
#: the native type of every row (the row links ``/taxonomy/term/{id}``).
DOC_TYPE_NAMES: dict[str, str] = {
    "542": "Acts",
    "543": "Bills",
    "544": "Draft bills",
    "1534": "Constitution",
    "552": "Constitutional amendments",
    "545": "Notices",
    "547": "Green papers",
    "546": "White papers",
    "548": "Tenders",
    "550": "Annual reports",
    "553": "Other",
}

#: scope=policy drops these two native types: procurement notices and
#: departmental annual reports are not policy documents. The filter runs
#: at row level (the native type rides in every row, normalized from
#: either doctype-link shape) and the scope value travels in the
#: list-task params.
POLICY_EXCLUDED_TYPES: frozenset[str] = frozenset({"Tenders", "Annual reports"})

#: The document-type slug vocabulary (the portal's own
#: ``/documents-categories/{slug}`` words, lowercase CLI-friendly) — the
#: accepted values of the ``types=`` parameter, which selects exact
#: document types at row level and travels in the list-task params
#: (widening the selection later = new task identities = automatic
#: backfill, no ledger surgery). Mutually exclusive with ``scope=``.
TYPE_SLUGS: dict[str, str] = {
    "acts": "Acts",
    "bills": "Bills",
    "draft-bills": "Draft bills",
    "constitution": "Constitution",
    "constitutional-amendments": "Constitutional amendments",
    "notices": "Notices",
    "green-papers": "Green papers",
    "white-papers": "White papers",
    "tenders": "Tenders",
    "annual-reports": "Annual reports",
    "other": "Other",
}

#: Native type word → controlled doc_type. Deliberately minimal (section
#: 5.3 labelling rules: map only what maps cleanly, never guess) — whether
#: a Notice is a regulation is a semantic judgement left to the analysis
#: side; the native word always travels in meta.
DOC_TYPE_MAP: dict[str, str] = {
    "Acts": "STATUTE",
    "Constitution": "STATUTE",
    "Constitutional amendments": "STATUTE",
    "Bills": "BILL",
    "Draft bills": "BILL",
}


def map_doc_type(native_type: str) -> str:
    return DOC_TYPE_MAP.get(native_type.strip(), "OTHER")


def site_url_for(href: str) -> str:
    """The canonical, rebuildable address of one document (its slug URL,
    no session parameters — the doc_id hash basis)."""
    if href.startswith(("http://", "https://")):
        return href
    return f"{BASE_URL}{href}"


def slug_for(href: str) -> str:
    """The document's URL slug (the last path segment) — unique per
    document, used as the on-disk folder name."""
    return href.rstrip("/").rsplit("/", 1)[-1]


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country zaf --source govza window=2025-01-06:2025-01-10\n"
        "  python cli.py collect --country zaf --source govza sync=1\n"
        "  python cli.py collect --country zaf --source govza window=2025-01-06:2025-01-10 scope=all\n"
        "  python cli.py collect --country zaf --source govza window=2025-01-06:2025-01-10 types=notices,acts\n"
        "  python cli.py status --country zaf --source govza"
    )


def _parse_date(raw: str, label: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None


def _parse_scope(raw: str) -> str:
    scope = raw.strip().lower()
    if scope not in ("policy", "all"):
        raise _fail("scope must be 'policy' (non-policy types dropped, default) or 'all'")
    return scope


def _parse_types(raw: str) -> str:
    """A comma list of TYPE_SLUGS, normalized (order/dedup stable) — the
    value that rides in the list-task params."""
    slugs: list[str] = []
    for part in raw.split(","):
        slug = part.strip().lower()
        if not slug:
            continue
        if slug not in TYPE_SLUGS:
            raise _fail(
                f"unknown type {slug!r} — choose a comma list out of "
                f"{', '.join(TYPE_SLUGS)}"
            )
        if slug not in slugs:
            slugs.append(slug)
    if not slugs:
        raise _fail(f"types= must be a comma list out of {', '.join(TYPE_SLUGS)}")
    return ",".join(slugs)


def _pubdate_seeds(from_date: date, to_date: date, scope: str, types: str) -> list[TaskSeed]:
    seeds: list[TaskSeed] = []
    day = from_date
    while day <= to_date:
        seed_params: dict[str, Any] = {"date": day.isoformat(), "page": "1"}
        if types:
            seed_params["types"] = types
        else:
            seed_params["scope"] = scope
        seeds.append(TaskSeed(type="govza_list", params=seed_params))
        day += timedelta(days=1)
    return seeds


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")
    if params.get("scope") and params.get("types"):
        raise _fail("give scope= or types=, not both")
    scope = _parse_scope(str(params.get("scope", "policy")))
    types = _parse_types(str(params.get("types", ""))) if params.get("types") else ""

    if params.get("window"):
        window = str(params["window"])
        from_str, sep, to_str = window.partition(":")
        if not sep or not from_str or not to_str:
            raise _fail(f"window must look like FROM:TO (got {window!r})")
        from_date = _parse_date(from_str.strip(), "window FROM")
        to_date = _parse_date(to_str.strip(), "window TO")
        if from_date > to_date:
            raise _fail(f"window start {from_date} is after its end {to_date}")
        return _pubdate_seeds(from_date, to_date, scope, types)

    if is_sync:
        kv = params.get("_kv", {})
        cursor = kv.get(CURSOR_KEY)
        if not cursor:
            raise _fail("sync=1 needs a previous sweep; run an initial window=… first")
        from_date = date.fromisoformat(str(cursor)) + timedelta(days=1)
        # Never claim *today*: the day's items may not be posted yet, and
        # "not yet posted" answers like a clean empty day.
        to_date = datetime.now(UTC).date() - timedelta(days=1)
        if from_date > to_date:
            return []  # already in sync — nothing due
        return _pubdate_seeds(from_date, to_date, scope, types)

    raise _fail("give window=FROM:TO or sync=1")


def build_source() -> SourceDefinition:
    from adapters.zaf.sources.govza.clean import CLEAN_VERSION, GovzaCleanHandler
    from adapters.zaf.sources.govza.detail import DetailHandler
    from adapters.zaf.sources.govza.file import FileHandler
    from adapters.zaf.sources.govza.list import ListHandler

    return SourceDefinition(
        name="govza",
        start_tasks=start_tasks,
        task_types={
            "govza_list": ListHandler(),
            "govza_detail": DetailHandler(),
            "govza_file": FileHandler(),
            "govza_clean": GovzaCleanHandler(),
        },
        clean=CleanDefinition(
            task_type="govza_clean",
            version=CLEAN_VERSION,
            targets=("govza_detail",),
        ),
        # Key-free stateless HTML portal, no cookies, no session (probed
        # 2026-10-10): every task is one independent GET.
        parallel_safe=True,
    )
