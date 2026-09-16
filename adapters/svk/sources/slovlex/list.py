"""Task type ``svk_list``: one page of the Collection-of-Laws listing.

Response shape (probed 2026-09-08)::

    {"numFound": 26562, "start": 0, "docs": [
        {"iri": "/SK/ZZ/2026/227/20260905", "vyhlaseny": "2026-09-05T00:00:00Z",
         "typPredp": "Oznamenie", "typPredp_value": "Oznámenie",
         "rocnik": "2026", "nazov": "Oznámenie Ministerstva …",
         "cislo": "227/2026 Z. z.", "ucinnyOd": "2026-09-05T00:00:00Z",
         "zodpovedajucaUcinnost": "2026-09-08T00:00:00Z"},
        …]}

``ucinnyDo`` appears only when the version's validity ends (repealed or
sunset laws). ``zodpovedajucaUcinnost`` is a server-time echo (today for
in-force laws, the validity end for dead ones) and deliberately never
enters task params — it would corrode task identity day by day. The
listing ``iri`` itself is only a pointer: its trailing segment is a dated
version for amended laws (drifting) or the as-declared alias for others
(both shapes probed in production, 2026-09-15) — capture always targets
the alias, so entries are validated for shape but normalized to
``vyhlasene_znenie`` regardless of what the listing points at.

The walk (vyhlaseny-descending, no server-side date filter exists):
entries newer than the window's ``to`` are skipped and the page chains
on; once an entry is older than ``from`` everything after it is older
too (sort is verified non-increasing on every page); a short page is the
corpus tail. Either terminal confirms the window fully consumed and
advances the cursor. ``max_docs`` caps the spawns and, when it bites,
stops the walk — a trial window, not a partial crawl — and withholds the
cursor (the window was not fully consumed). Out-of-window rows are not
validated beyond their date: a malformed field on a skipped entry is a
non-event, while any anomaly on an in-window entry escalates loudly.
"""

from __future__ import annotations

import re as re_mod
from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.svk.sources.slovlex import (
    API_URL,
    CURSOR_KEY,
    PAGE_SIZE,
    alias_iri,
    iri_parts,
    list_params,
)

__all__ = ["SvkListHandler", "doc_seed", "iso_day"]

#: Fields every in-window doc must carry (probed shape); their absence is
#: a listing shape change, not a data boundary. ``typPredp`` (machine name)
#: is deliberately absent: some rows carry only the Slovak word, which the
#: doc-type mapping also accepts (probed 2026-09-16).
_REQUIRED = ("iri", "vyhlaseny", "typPredp_value", "rocnik", "nazov", "cislo")


def iso_day(value: str) -> str:
    """'2026-09-05T00:00:00Z' -> '2026-09-05' (date part must be ISO)."""
    day = value[:10]
    year, sep, rest = day.partition("-")
    if not sep or len(year) != 4 or len(rest) != 5 or not day.replace("-", "").isdigit():
        raise ValueError(f"vyhlaseny {value!r} has no ISO date prefix")
    return day


def doc_seed(doc: dict[str, Any], capture_pdf: bool = True,
             versions: bool = False) -> TaskSeed:
    """Validate one in-window listing row and build its spawn.

    The capture iri is ALWAYS the as-declared alias (stable, idempotent);
    the listing's own pointer is parsed for its law coordinates and then
    normalized away. Params are otherwise the stable fields only — enough
    for the doc task to cross-check the page against the listing. The
    pdf/versions sweep flags ride the list task's identity; versions also
    marks the doc spawn so version-fetching sweeps keep their own task
    identity (done event docs are not re-opened by them).
    """
    for field in _REQUIRED:
        value = doc.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"listing doc misses {field!r}: {doc!r}")
    rocnik, number, _ver = iri_parts(doc["iri"].strip())
    machine = doc.get("typPredp")
    params: dict[str, Any] = {
        "iri": alias_iri(rocnik, number),
        "vyhlaseny": iso_day(doc["vyhlaseny"]),
        "cislo": re_mod.sub(r"[\s ]+", " ", doc["cislo"]).strip(),
        "typ_predp_value": doc["typPredp_value"].strip(),
        "nazov": doc["nazov"].strip(),
    }
    if isinstance(machine, str) and machine.strip():
        params["typ_predp"] = machine.strip()
    if versions:
        params["versions"] = 1
    for source, target in (("ucinnyOd", "ucinny_od"), ("ucinnyDo", "ucinny_do")):
        value = doc.get(source)
        if isinstance(value, str) and value.strip():
            params[target] = iso_day(value)
    if capture_pdf:
        return TaskSeed(type="svk_pdf", params=params)
    return TaskSeed(type="svk_doc", params={**params, "pdf_ok": 0})


class SvkListHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=API_URL, params=list_params(int(task.params["start"])))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = dict(task.params)
        start = int(params["start"])
        from_day = str(params["from"])
        to_day = str(params["to"])
        if response.status_code != 200:
            raise ValueError(f"listing page at start={start} returned HTTP "
                             f"{response.status_code}")
        data = response.json()
        docs = data.get("docs")
        if not isinstance(docs, list):
            # A wrong-typed payload is a listing shape change, and shape
            # changes are ValueError by country-pack convention.
            raise ValueError(  # noqa: TRY004
                f"listing page at start={start} has no docs array"
            )

        seeds: list[TaskSeed] = []
        cap = params.get("max_docs")
        capped = False
        crossed = False
        previous = ""
        capture_pdf = params.get("pdf", 1) != 0
        capture_versions = params.get("versions") == 1
        for doc in docs:
            if not isinstance(doc, dict):
                # Shape change, same convention as the docs-array guard.
                raise ValueError(  # noqa: TRY004
                    f"listing page at start={start} holds a non-object doc"
                )
            vyhlaseny = doc.get("vyhlaseny")
            if not isinstance(vyhlaseny, str) or not vyhlaseny.strip():
                raise ValueError(
                    f"listing page at start={start} holds a doc without vyhlaseny"
                )
            day = iso_day(vyhlaseny)
            if previous and day > previous:
                raise ValueError(
                    f"listing page at start={start} is not vyhlaseny-descending "
                    f"({day} after {previous}) — sort assumption broken"
                )
            previous = day
            if day > to_day:
                continue  # newer than the window — keep walking
            if day < from_day:
                crossed = True  # sorted: everything after this is older
                break
            if cap is not None and len(seeds) >= int(cap):
                capped = True
                break
            seeds.append(doc_seed(doc, capture_pdf, capture_versions))

        next_tasks: list[TaskSeed] = list(seeds)
        cursor_updates: dict[str, str] = {}
        expected_empty = None
        terminal = crossed or len(docs) < PAGE_SIZE
        if not terminal and not capped:
            next_tasks.append(
                TaskSeed(type="svk_list", params={**params, "start": start + PAGE_SIZE})
            )
        elif terminal and not capped:
            # The walk reached past the window's lower bound (or the corpus
            # end): everything dated <= to has been seen — the watermark.
            cursor_updates[CURSOR_KEY] = to_day
            if not seeds:
                expected_empty = (
                    f"window {from_day}..{to_day} holds no publications "
                    "(walk crossed the corpus boundary)"
                )
        return TaskResult(
            next_tasks=next_tasks,
            cursor_updates=cursor_updates,
            expected_empty=expected_empty,
        )
