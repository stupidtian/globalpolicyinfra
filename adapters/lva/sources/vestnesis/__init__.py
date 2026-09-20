"""The vestnesis source: task-type registry and seed generation.

*Latvijas Vēstnesis* (vestnesis.lv), the official publication of the
Republic of Latvia (defined by section 2(1) of the Law on Official
Publications and Legal Information; electronic-only since 2013-01-01,
published continuously since 1993-02-25 — probed 2026-09-16, samples in
the task folder; see docs/countries/lva/vestnesis-zh.md). The gazette
site has no date-addressed directory, so the two task types split the
work across the publisher's two sites, which share one document id
namespace:

===============  =====================================================
type             what one task does
===============  =====================================================
vestnesis_list   one day: GET the likumi.lv day-addressed listing of
                 acts *published* that day
                 (``/ta/jaunakie/publiceti/{Y}/{M}/{D}/``, server-
                 rendered UTF-8 HTML). Every row carries the full
                 bibliographic set inline (issuer, type, number,
                 adoption/entry-into-force dates, status, publication
                 reference, gazette document id, OP number) and yields
                 one vestnesis_doc seed. A day without an issue
                 answers HTTP 200 with a clean empty listing (no
                 ``sk-jaunakie`` marker): expected_empty, and the day
                 cursor still advances.
vestnesis_doc    one document: GET
                 ``https://www.vestnesis.lv/ta/id/{docId}`` — legacy
                 documents answer directly, newer ones redirect to the
                 canonical ``/op/{year}/{issue}.{ordinal}`` address
                 (transport follows automatically). The page carries
                 the bibliographic block, the verbatim publication
                 citation and the embedded as-published text; the same
                 response registers the document AND is stored
                 verbatim as the primary file.
===============  =====================================================

Params (key=value on the CLI)::

    window=2024-06-03:2024-06-05   closed date range (required, or sync=1)
    sync=1                          from = day after the kv cursor
                                    vestnesis_last_date, to = *yesterday*
                                    (the day's issue may not be out yet;
                                    "not yet listed" and "no issue that
                                    day" answer identically)
    scope=state                     which issuers to keep: state = all
                                    state-level issuers (default; municipal
                                    councils filtered out), all = everything
                                    the listing has. The scope travels in
                                    the list-task params, so widening it
                                    later means new task identities and an
                                    automatic backfill — no ledger surgery.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "CURSOR_KEY",
    "DOC_BASE",
    "LIST_BASE",
    "MUNICIPAL_MARKERS",
    "build_source",
    "is_municipal_issuer",
    "source_url_for",
    "start_tasks",
]

LIST_BASE = "https://likumi.lv"
DOC_BASE = "https://www.vestnesis.lv"

CURSOR_KEY = "vestnesis_last_date"

#: Issuer substrings (case-insensitive) that identify a municipal council.
#: ``dome``/``padome`` alone are unsafe — state agencies like the electronic
#: media council (Nacionālā elektronisko plašsaziņas līdzekļu padome) end in
#: ``padome`` — so the markers name the municipal forms explicitly. Observed
#: against the 2024-06-04 listing (Daugavpils pilsētas dome, Jūrmalas
#: pilsētas dome, Alūksnes/Ādažu/Tukuma novada dome — probed 2026-09-16).
MUNICIPAL_MARKERS: tuple[str, ...] = (
    "novada dome",
    "pilsētas dome",
    "novada padome",
    "rajona padome",
    "pilsētas padome",
    "pagasta padome",
    "ciema padome",
    "rīgas dome",
)


def is_municipal_issuer(issuer: str) -> bool:
    """True when the issuer names a municipal council (scope=state filters
    these out; brief boundary: no municipal regulations)."""
    lowered = issuer.lower()
    return any(marker in lowered for marker in MUNICIPAL_MARKERS)


def source_url_for(doc_id_src: str) -> str:
    """The canonical, rebuildable document URL on the gazette site. It
    serves both eras — legacy ids answer directly, newer ones redirect to
    their /op/ address (which is preserved in the document's meta)."""
    return f"{DOC_BASE}/ta/id/{doc_id_src}"


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country lva --source vestnesis window=2024-06-03:2024-06-05\n"
        "  python cli.py collect --country lva --source vestnesis sync=1\n"
        "  python cli.py collect --country lva --source vestnesis window=2024-06-03:2024-06-05 scope=all\n"
        "  python cli.py status --country lva --source vestnesis"
    )


def _parse_date(raw: str, label: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None


def _parse_scope(raw: str) -> str:
    scope = raw.strip().lower()
    if scope not in ("state", "all"):
        raise _fail("scope must be 'state' (state-level issuers only, default) or 'all'")
    return scope


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")
    scope = _parse_scope(str(params.get("scope", "state")))

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
        # Never claim *today*: the day's issue may not be out / listed yet,
        # and "not yet listed" answers like a clean empty day.
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
                type="vestnesis_list",
                params={"date": day.isoformat(), "scope": scope},
            )
        )
        day += timedelta(days=1)
    return seeds


def build_source() -> SourceDefinition:
    from adapters.lva.sources.vestnesis.doc import VestnesisDocHandler
    from adapters.lva.sources.vestnesis.list import VestnesisListHandler

    return SourceDefinition(
        name="vestnesis",
        start_tasks=start_tasks,
        task_types={
            "vestnesis_list": VestnesisListHandler(),
            "vestnesis_doc": VestnesisDocHandler(),
        },
    )
