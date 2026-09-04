"""The lovtidende source: task-type registry and seed generation.

Norsk lovtidende avdeling I, the Norwegian legal gazette for laws (lov)
and central regulations (forskrift), published electronically — and
officially — since 2001 by Stiftelsen Lovdata on behalf of the Ministry
of Justice. Collected from Lovdata's public-data bulk packages (see
docs/countries/nor/lovtidende-zh.md). Flat document path: zero domain
tables, ``documents`` is the whole ledger.

Task types (each = one module with ``build_request`` + ``parse``):

===============  =====================================================
type             what one task does
===============  =====================================================
lt_list          the freshness probe: GET the package catalogue
                 (``/v1/publicData/list``); every ``lovtidend-avd1-*``
                 package in scope yields one lt_pack task carrying the
                 package's identity stamp (``{sizeBytes}@{lastModified}``)
                 in its params — an unchanged stamp means the lt_pack
                 task already exists and is done, so it is skipped for
                 zero requests; a rebuilt package gets a new task
                 identity and re-sweeps idempotently. The ``gjeldende-*``
                 consolidated-law packages are out of scope and ignored.
lt_pack          one bulk package: GET ``/v1/publicData/get/{filename}``
                 (tar.bz2), stream every ``lti/{year}/{nl|sf}-*.xml``
                 member and register one document + one verbatim file
                 per gazette entry. One package = one task = one
                 transaction (user ruling 2026-09-03: the 38,182-entry
                 archive package is accepted as a single large write in
                 exchange for a one-time 69 MB download per sweep).
===============  =====================================================

Params (key=value on the CLI)::

    sync=1                required; seeds one lt_list whose identity
                          includes the run day (bucket) — same-day
                          re-runs deduplicate to zero requests, the next
                          day re-checks the catalogue naturally
    packages=all          all | year | archive — which packages the
                          catalogue may spawn (year = current-year
                          package only; the small-window shape)
    bucket=2026-09-03     optional override of the run-day bucket, to
                          force a fresh catalogue check the same day
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = ["build_source", "start_tasks"]

_SCOPE_VALUES = ("all", "year", "archive")


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country nor --source lovtidende sync=1\n"
        "  python cli.py collect --country nor --source lovtidende sync=1 packages=year\n"
        "  python cli.py collect --country nor --source lovtidende sync=1 packages=archive\n"
        "  python cli.py collect --country nor --source lovtidende sync=1 bucket=2026-09-03b\n"
        "  python cli.py status --country nor --source lovtidende"
    )


def _parse_packages(raw: str) -> str:
    value = raw.strip().lower()
    if value not in _SCOPE_VALUES:
        raise _fail(f"packages must be one of {', '.join(_SCOPE_VALUES)} (got {raw!r})")
    return value


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")
    if not is_sync:
        raise _fail("give sync=1 (the catalogue task is both the first run and the increment)")
    packages = _parse_packages(str(params.get("packages", "all")))
    bucket = str(params.get("bucket") or "").strip() or datetime.now(UTC).date().isoformat()
    return [
        TaskSeed(
            type="lt_list",
            params={"bucket": bucket, "packages": packages},
        )
    ]


def build_source() -> SourceDefinition:
    from adapters.nor.sources.lovtidende.catalog import LtListHandler
    from adapters.nor.sources.lovtidende.pack import LtPackHandler

    return SourceDefinition(
        name="lovtidende",
        start_tasks=start_tasks,
        task_types={
            "lt_list": LtListHandler(),
            "lt_pack": LtPackHandler(),
        },
    )
