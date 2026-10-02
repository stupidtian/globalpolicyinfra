"""The isap source: task-type registry and seed generation.

*Dziennik Ustaw* (Dz.U.), the Journal of Laws of the Republic of Poland —
the constitutionally exclusive promulgation gazette for normative acts
(statutes, executive regulations, ratified treaties, constitutional-tribunal
judgments, consolidated texts). Collected through the Sejm's official ELI
API (``https://api.sejm.gov.pl``, OpenAPI "ELI for Polish acts" v1.0;
key-free, no application session — F5 load-balancer cookies are transport
noise, probed 2026-09-20 with samples archived in the task folder; see
docs/countries/pol/isap-zh.md). The ``isap.sejm.gov.pl`` web app is
Imperva-gated and robots-disallowed for non-crawlers — the ELI API serves
the same corpus (the WDU addresses are ISAP's own).

Entity model: one persistent act per ELI address (``DU/{year}/{pos}``)
spanning its as-enacted text plus every consolidated text (tekst jednolity);
each consolidation arrives as its own gazette announcement (Obwieszczenie)
which is a full act entry in its own right, so the ``acts`` table holds one
row per ELI and every document hangs off an act via ``entity_ref``
(enacted documents point at themselves, consolidated texts at the base
act — the version-series axis).

Task types (each = one module with ``build_request`` + ``parse``):

===============  =====================================================
type             what one task does
===============  =====================================================
isap_year        one year of the gazette (``GET /eli/acts/DU/{year}``):
                 the full listing answers in ONE response (no paging,
                 probed 1995/2024); filters by the promulgation-date
                 window and spawns one isap_act per entry
isap_changes     one page of the change feed (``GET /eli/changes/acts
                 ?since={cursor}``): every act whose data changed since
                 the cursor, all publishers; DU rows spawn isap_act
                 (signal = changeDate), a full page chains the next
                 offset, the terminal page advances the cursor
isap_act         one act (``GET /eli/acts/DU/{y}/{p}``): upserts the
                 acts row, archives the raw response (act.json, the
                 lossless copy of the nine-category reference graph),
                 spawns the text downloads and one isap_act per
                 consolidation announcement referenced
isap_text        the act's HTML text (``/text.html``) — the primary
                 document file when the act has one (textHTML)
isap_pdf         the act's original PDF (``/text.pdf``) — primary
                 carrier when there is no HTML (consolidation
                 announcements), else the typeset sibling
isap_clean       strips one collected HTML text to plain text
                 (framework-cleaning; targets isap_text only — PDFs
                 are out of cleaning scope, OCR undecided)
===============  =====================================================

Params (key=value on the CLI)::

    year=2026         gazette year (1918-current); one isap_year sweep
    from=… to=…       optional closed promulgation-date window inside the
                      year (scope travels in the sweep task's params, so
                      widening it later means new task identities)
    max_acts=N        cap on isap_act spawns per sweep (test guard)
    sync=1            from = kv cursor isap_last_change (changeDate
                      watermark; needs a previous sweep)
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "API_BASE",
    "CURSOR_KEY",
    "ELI_BASE",
    "FIRST_YEAR",
    "PUBLISHER",
    "build_source",
    "canonical_source_url",
    "start_tasks",
]

API_BASE = "https://api.sejm.gov.pl"
ELI_BASE = f"{API_BASE}/eli"

#: The only publisher this source collects. Monitor Polski (MP) rides the
#: same API but carries non-normative government material (statements,
#: appointments) — the gazette for normative acts is DU alone.
PUBLISHER = "DU"

#: First year of the DU coverage the API reports (1918-2026, probed).
FIRST_YEAR = 1918

CURSOR_KEY = "isap_last_change"

#: Server default page size of /eli/changes/acts (OpenAPI).
CHANGES_PAGE_LIMIT = 100


def canonical_source_url(publisher: str, year: int, pos: int) -> str:
    """The rebuildable canonical address of one act — doc_id hashes this
    (entry-level, so the format policy can change without changing ids)."""
    return f"{ELI_BASE}/acts/{publisher}/{year}/{pos}"


def act_folder(publisher: str, year: int | str, pos: int | str) -> str:
    """Raw-folder path below the country root, e.g. ``01_raw/isap/DU/2024/0001``."""
    return f"01_raw/isap/{publisher}/{int(year)}/{int(pos):04d}"


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country pol --source isap year=2026 from=2026-09-14 to=2026-09-20\n"
        "  python cli.py collect --country pol --source isap year=2024 max_acts=5\n"
        "  python cli.py collect --country pol --source isap sync=1\n"
        "  python cli.py status --country pol --source isap"
    )


def _parse_date(raw: str, label: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None


def _parse_year(raw: str) -> int:
    try:
        year = int(raw)
    except ValueError:
        raise _fail(f"year must be a number (got {raw!r})") from None
    if year < FIRST_YEAR or year > datetime.now(UTC).year:
        raise _fail(f"year {year} is outside the gazette coverage {FIRST_YEAR}-current")
    return year


def _parse_window(
    params: dict[str, Any], year: int
) -> tuple[str | None, str | None]:
    """Optional ``from``/``to`` promulgation-date window, validated to sit
    inside the swept year (a window crossing years is one sweep per year)."""
    from_raw = str(params.get("from", "")).strip()
    to_raw = str(params.get("to", "")).strip()
    if not from_raw and not to_raw:
        return None, None
    from_date = _parse_date(from_raw, "from") if from_raw else None
    to_date = _parse_date(to_raw, "to") if to_raw else None
    if from_date and from_date.year != year:
        raise _fail(f"from {from_raw} must fall inside the swept year {year}")
    if to_date and to_date.year != year:
        raise _fail(f"to {to_raw} must fall inside the swept year {year}")
    if from_date and to_date and from_date > to_date:
        raise _fail(f"window start {from_raw} is after its end {to_raw}")
    return from_raw or None, to_raw or None


def _parse_max_acts(params: dict[str, Any]) -> int | None:
    raw = str(params.get("max_acts", "")).strip()
    if not raw:
        return None
    if not raw.isdigit() or int(raw) < 1:
        raise _fail(f"max_acts must be a positive integer (got {raw!r})")
    return int(raw)


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")
    year_raw = str(params.get("year", "")).strip()

    if is_sync:
        if year_raw:
            raise _fail("give either year=… (backfill sweep) or sync=1 (change feed), not both")
        kv = params.get("_kv", {})
        cursor = kv.get(CURSOR_KEY)
        if not cursor:
            raise _fail("sync=1 needs a previous sweep; run an initial year=… first")
        return [TaskSeed(type="isap_changes", params={"since": str(cursor), "offset": "0"})]

    if not year_raw:
        raise _fail("give year=YYYY (optionally from=/to=/max_acts=) or sync=1")
    year = _parse_year(year_raw)
    from_str, to_str = _parse_window(params, year)
    seed_params: dict[str, Any] = {"publisher": PUBLISHER, "year": str(year)}
    if from_str:
        seed_params["from"] = from_str
    if to_str:
        seed_params["to"] = to_str
    max_acts = _parse_max_acts(params)
    if max_acts is not None:
        seed_params["max_acts"] = str(max_acts)
    return [TaskSeed(type="isap_year", params=seed_params)]


#: The register's persistent entity (ARCHITECTURE.md section 6.4 criterion):
#: one row per act. A consolidation announcement is an act entry of its own
#: (its texts[] carries the consolidated PDF, its references point back at
#: the base act), so the version lineage is fully reconstructible from this
#: table plus documents.entity_ref — no derived lineage table.
DOMAIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS acts (
    eli TEXT PRIMARY KEY,
    address TEXT,
    publisher TEXT,
    year INTEGER,
    pos INTEGER,
    volume INTEGER,
    title TEXT,
    native_type TEXT,
    status TEXT,
    in_force TEXT,
    promulgation TEXT,
    announcement_date TEXT,
    entry_into_force TEXT,
    change_date TEXT,
    released_by TEXT,
    keywords TEXT,
    raw_path TEXT
);
"""


def build_source() -> SourceDefinition:
    from adapters.base import CleanDefinition
    from adapters.pol.sources.isap.act import IsapActHandler
    from adapters.pol.sources.isap.changes import IsapChangesHandler
    from adapters.pol.sources.isap.clean import CLEAN_VERSION, IsapCleanHandler
    from adapters.pol.sources.isap.pdf import IsapPdfHandler
    from adapters.pol.sources.isap.text import IsapTextHandler
    from adapters.pol.sources.isap.year import IsapYearHandler

    return SourceDefinition(
        name="isap",
        start_tasks=start_tasks,
        task_types={
            "isap_year": IsapYearHandler(),
            "isap_changes": IsapChangesHandler(),
            "isap_act": IsapActHandler(),
            "isap_text": IsapTextHandler(),
            "isap_pdf": IsapPdfHandler(),
            "isap_clean": IsapCleanHandler(),
        },
        # The ELI HTML is a bare document body (h1 + act structure, no site
        # chrome); text.html files clean with a body-level whitelist. The
        # targets are the act tasks — isap_act registers every HTML-primary
        # document (isap_pdf registers PDF-primary ones, out of cleaning
        # scope until OCR is decided).
        clean=CleanDefinition(
            task_type="isap_clean",
            version=CLEAN_VERSION,
            targets=("isap_act",),
        ),
        domain_schema=DOMAIN_SCHEMA,
        domain_tables=("acts",),
        domain_keys={"acts": ("eli",)},
        # Key-free stateless GETs; no cookies, no csrf, no cross-task
        # transport state (probed 2026-09-20) — safe on any worker with any
        # session (framework-concurrency ruling 1.4).
        parallel_safe=True,
    )
