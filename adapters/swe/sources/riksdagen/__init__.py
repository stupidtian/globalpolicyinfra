"""The riksdagen source: task-type registry, seed generation, shared helpers.

Svensk författningssamling (SFS), the Swedish statute gazette — laws
(``lag``, enacted by the Riksdag) and government ordinances
(``förordning``, issued by the Government) numbered ``{year}:{serial}``.
The corpus carried by the machine channel is the **base-statute layer**
(grundförfattningar, ~150–210 per year, 11,564 total, probed 2026-09-09);
amending statutes (~91% of each year's number space) exist only as
amendment markers folded into the base statutes' consolidated text —
their effects are collected losslessly with the base text, the citation
graph itself is analysis-side work (user ruling 2026-09-01).

Channels (probed 2026-09-09, no key / no session / no csrf / no robots):

* listing  GET https://data.riksdagen.se/dokumentlista/?doktyp=sfs&rm={year}&sz=100&p={page}
           XML envelope ``dokumentlista → dokument[]`` with ``traffar`` /
           ``sidor`` attributes. The ``rm`` (number-year) partition is the
           only reliable filter: ``from``/``to`` date windows silently
           malfunction for sfs (return window-external docs) and ``sort``
           is ignored — both probed twice.
* body     GET https://data.riksdagen.se/dokument/sfs-{year}-{serial}.html
           HTML fragment: ``<h2>`` title, header block (SFS nr /
           Departement-myndighet / Utfärdad / "Ändrad: t.o.m. SFS {y:n}" /
           Ändringsregister + Källa links to the Government register),
           optional TOC, then the anchored full text (consolidated live
           view — snapshot-at-discovery semantics). UTF-8 without a
           charset declaration: decode explicitly.

Body semantics, probed 2026-09-09: 65.9% of register statutes have been
amended — for those the text is consolidated-to-fetch-day and the header
carries the amended-through stamp (``andrad_tom``); the never-amended
34.1% serve their promulgation-day original forever (empty ``Ändrad``).
Documents are fetched once and frozen: no signal-driven reopen (a refetch
would rewrite the file under an insert-ignored documents row and drift
the recorded checksum).

Task types (each = one module with ``build_request`` + ``parse``):

===============  =====================================================
type             what one task does
===============  =====================================================
sfs_list         one listing page of one number-year; spawns one sfs_doc
                 per row; ``p < sidor`` chains to the next page; a year
                 with zero rows (below the 1736 corpus start) is an
                 explained empty
sfs_doc          one statute's HTML; cross-checks the listing row (SFS
                 number, promulgation date) against the page header — a
                 mismatch is a shape change and escalates loudly; emits
                 the document + the response bytes verbatim as doc.html
===============  =====================================================

Params (key=value on the CLI)::

    years=2026         one number-year, or a closed range years=2024:2026
    sync=1             re-walk the previous + current number-year's
                       listing pages with a fresh ``refresh`` timestamp
                       (task identity changes, done documents skip);
                       two years because promulgation-to-registration
                       lags a few days across year boundaries
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "API_BASE",
    "LIST_URL",
    "PAGE_SIZE",
    "build_riksdagen",
    "canonical_doc_url",
    "dok_id_for",
    "html_path",
    "map_doc_type",
    "sfs_parts",
    "start_tasks",
]


API_BASE = "https://data.riksdagen.se"
LIST_URL = f"{API_BASE}/dokumentlista/"
PAGE_SIZE = 100


def sfs_parts(sfs_nr: str) -> tuple[str, str]:
    """'2026:1776' -> ('2026', '1776'); 'N2026:3' -> ('2026', '3').

    The year part may carry a leading ``N`` (register notices about
    agency-regulation collections). Both parts are validated: a 4-digit
    year and a numeric serial — anything else is a shape change.
    """
    year_raw, sep, serial = sfs_nr.partition(":")
    year = re.sub(r"\D", "", year_raw)
    if not sep or len(year) != 4 or not serial.isdigit() or not serial:
        raise ValueError(f"sfs number {sfs_nr!r} is not {{[N]YYYY}}:{{serial}}")
    return year, serial


def dok_id_for(sfs_nr: str) -> str:
    """'2026:1776' -> 'sfs-2026-1776' (the Riksdagen document id)."""
    return "sfs-" + sfs_nr.replace(":", "-")


def canonical_doc_url(dok_id: str) -> str:
    """Rebuildable URL of one statute's HTML (doc_id hashes this)."""
    return f"{API_BASE}/dokument/{dok_id}.html"


def html_path(sfs_nr: str) -> str:
    """Raw-folder path of the main file below the country root.

    One folder per SFS number (':' is illegal in Windows paths — dash
    form), sharded by number-year to keep directories small.
    """
    year, _ = sfs_parts(sfs_nr)
    return f"01_raw/riksdagen/{year}/{sfs_nr.replace(':', '-')}/doc.html"


def map_doc_type(title: str) -> str:
    """Title's native head word -> controlled doc_type.

    Swedish statute titles open with the instrument word, either alone
    (``Lag (2026:43) …``) or as a compound head (``Skollag (2010:800)``,
    ``Mottagandeförordning (2026:…)``). The head segment before the
    parenthetical is read and its last word suffix-mapped; anything else
    (Tillkännagivande, kungörelser, odd rows) is OTHER. The native title
    is always kept verbatim — re-labelling never needs a re-crawl.
    """
    head = re.split(r"\(", title.strip(), maxsplit=1)[0].strip()
    words = head.split()
    word = words[-1].lower() if words else ""
    if word == "lag" or word.endswith("lag"):
        return "STATUTE"
    if word == "förordning" or word.endswith("förordning"):
        return "REGULATION"
    return "OTHER"


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country swe --source riksdagen years=2026\n"
        "  python cli.py collect --country swe --source riksdagen years=2024:2026\n"
        "  python cli.py collect --country swe --source riksdagen sync=1\n"
        "  python cli.py status --country swe --source riksdagen"
    )


def _parse_year(raw: str, label: str) -> int:
    raw = raw.strip()
    if not re.fullmatch(r"\d{4}", raw):
        raise _fail(f"{label} must be a 4-digit year (got {raw!r})")
    return int(raw)


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    is_sync = str(params.get("sync", "")).strip() in ("1", "true", "yes")
    refresh: str | None = None

    if params.get("years"):
        years = str(params["years"])
        from_raw, sep, to_raw = years.partition(":")
        if not sep:
            to_raw = from_raw
        from_year = _parse_year(from_raw, "years FROM")
        to_year = _parse_year(to_raw, "years TO")
        if from_year > to_year:
            raise _fail(f"years start {from_year} is after its end {to_year}")
        year_list = range(from_year, to_year + 1)
    elif is_sync:
        # No date cursor exists (the listing's date filters malfunction);
        # increment = parameterised re-walk (KOR refresh precedent): a fresh
        # timestamp changes the listing tasks' identity, done documents skip.
        # Two years absorb the promulgation->registration lag across Jan 1.
        this_year = datetime.now(UTC).year
        year_list = range(this_year - 1, this_year + 1)
        refresh = datetime.now(UTC).isoformat(timespec="seconds")
    else:
        raise _fail("give years=YYYY (or years=YYYY:YYYY), or sync=1")

    seeds: list[TaskSeed] = []
    for year in year_list:
        seed_params: dict[str, Any] = {"ar": str(year), "p": 1}
        if refresh is not None:
            seed_params["refresh"] = refresh
        seeds.append(TaskSeed(type="sfs_list", params=seed_params))
    return seeds


def build_riksdagen() -> SourceDefinition:
    from adapters.swe.sources.riksdagen.doc import SfsDocHandler
    from adapters.swe.sources.riksdagen.list import SfsListHandler

    return SourceDefinition(
        name="riksdagen",
        start_tasks=start_tasks,
        task_types={
            "sfs_list": SfsListHandler(),
            "sfs_doc": SfsDocHandler(),
        },
    )
