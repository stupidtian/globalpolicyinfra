"""The regulations source: task-type registry and seed generation.

Task types (each = one module with ``build_request`` + ``parse``):

===============  =====================================================
type             what one task does
===============  =====================================================
fr_list_page     one page of a publication-date window; spawns detail
                 tasks (deep=all) and the next page
fr_detail        one FR document's full metadata row + folder mirror +
                 one download task per text format
fr_text_dl       download one text artifact (raw.txt / full.xml / doc.pdf)
ua_edition       one Unified Agenda edition XML → rulemakings (latest
                 state) + ua_entries (per-edition snapshot)
oira_file        one OIRA review file (a completed year, or a rolling
                 daily file) → oira_reviews
===============  =====================================================

Params (key=value on the CLI)::

    window=FROM:TO          FR chain: documents published in the range
    sync=1                  FR chain: FROM = kv cursor fr_last_pub_date,
                            TO = today (an initial window must exist first)
    deep=none|all           whether listing spawns detail+text (default none)
    formats=txt,xml         text formats to download (pdf optional)
    cases=DOCNUM[,…]        deep-crawl these documents with or without a window
    max_pages=N             stop the listing chain after N pages
    agenda=all|ED[,…]       agenda editions to ingest (e.g. 202510)
    oira=all|NAME[,…]       review files: years (1981→) and/or
                            UNDER_REVIEW / YTD / LAST30

The three chains are independent: running ``window=… agenda=all`` starts
both; each needs no state from the other.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from adapters.base import SourceDefinition, TaskSeed
from adapters.usa.schema import DOMAIN_KEYS, DOMAIN_SCHEMA, DOMAIN_TABLES

__all__ = ["build_source"]


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country usa --source regulations "
        "window=2026-08-17:2026-08-19 deep=all\n"
        "  python cli.py collect --country usa --source regulations agenda=all oira=all\n"
        "  python cli.py collect --country usa --source regulations sync=1"
    )


def _split_window(raw: str) -> tuple[str, str]:
    from_str, sep, to_str = raw.strip().partition(":")
    if not sep or not from_str or not to_str:
        raise _fail(f"window must look like FROM:TO (got {raw!r})")
    return from_str.strip(), to_str.strip()


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    seeds: list[TaskSeed] = []
    deep = str(params.get("deep", "none")).strip()
    if deep not in ("none", "all"):
        raise _fail(f"deep must be none or all (got {deep!r})")
    formats = str(params.get("formats", "txt,xml"))
    cases = [c.strip() for c in str(params.get("cases", "") or "").split(",") if c.strip()]
    max_pages = int(params["max_pages"]) if params.get("max_pages") else None
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")

    # -- FR chain: a window (explicit or from the sync cursor) or bare cases
    if params.get("window") or is_sync:
        if params.get("window"):
            from_str, to_str = _split_window(str(params["window"]))
        else:
            kv = params.get("_kv", {})
            from_str = kv.get("fr_last_pub_date")
            if not from_str:
                raise _fail("sync=1 needs a previous sweep; run an initial window=… first")
            to_str = datetime.now(UTC).date().isoformat()
        seeds.append(
            TaskSeed(
                type="fr_list_page",
                params={
                    "from": from_str,
                    "to": to_str,
                    "page": 1,
                    "deep": deep,
                    "formats": formats,
                    "cases": cases,
                    "sync": is_sync,
                    **({"max_pages": max_pages} if max_pages else {}),
                },
            )
        )
    elif cases:
        for number in cases:
            seeds.append(
                TaskSeed(type="fr_detail", params={"document_number": number, "formats": formats})
            )

    # -- agenda chain
    agenda = str(params.get("agenda", "") or "").strip()
    if agenda:
        from adapters.usa.sources.regulations.agenda import KNOWN_EDITIONS

        editions = list(KNOWN_EDITIONS) if agenda == "all" else [
            e.strip() for e in agenda.split(",") if e.strip()
        ]
        unknown = [e for e in editions if e not in KNOWN_EDITIONS]
        if unknown:
            raise _fail(
                f"unknown agenda edition(s) {unknown}; known editions are "
                f"199510–{KNOWN_EDITIONS[0]} (see docs/countries/usa-regulations.md)"
            )
        seeds.extend(TaskSeed(type="ua_edition", params={"edition": e}) for e in editions)

    # -- OIRA chain; rolling files carry today as the reopen signal
    oira = str(params.get("oira", "") or "").strip()
    if oira:
        from adapters.usa.sources.regulations.oira import FIRST_YEAR, ROLLING_FILES

        current_year = datetime.now(UTC).year
        if oira == "all":
            names = [str(y) for y in range(FIRST_YEAR, current_year)]
            names += ["YTD", "UNDER_REVIEW"]
        else:
            names = [n.strip().upper() for n in oira.split(",") if n.strip()]
        today = datetime.now(UTC).date().isoformat()
        for name in names:
            if name.isdigit() and not (FIRST_YEAR <= int(name) < current_year):
                raise _fail(f"oira year {name} is outside {FIRST_YEAR}–{current_year - 1}")
            if not name.isdigit() and name not in ROLLING_FILES:
                raise _fail(f"oira name {name!r} is not a year or one of {sorted(ROLLING_FILES)}")
            signal = today if name in ROLLING_FILES else None
            seeds.append(TaskSeed(type="oira_file", params={"name": name}, signal=signal))

    if not seeds:
        raise _fail("nothing to do: give at least one of window=/sync=1/cases=/agenda=/oira=")
    return seeds


def build_source() -> SourceDefinition:
    from adapters.usa.sources.regulations.agenda import UaEditionHandler
    from adapters.usa.sources.regulations.detail import (
        FrDetailHandler,
        FrTextDownloadHandler,
    )
    from adapters.usa.sources.regulations.enumerate import FrListPageHandler
    from adapters.usa.sources.regulations.oira import OiraFileHandler

    return SourceDefinition(
        name="regulations",
        start_tasks=start_tasks,
        task_types={
            "fr_list_page": FrListPageHandler(),
            "fr_detail": FrDetailHandler(),
            "fr_text_dl": FrTextDownloadHandler(),
            "ua_edition": UaEditionHandler(),
            "oira_file": OiraFileHandler(),
        },
        domain_schema=DOMAIN_SCHEMA,
        domain_tables=DOMAIN_TABLES,
        domain_keys=DOMAIN_KEYS,
    )
