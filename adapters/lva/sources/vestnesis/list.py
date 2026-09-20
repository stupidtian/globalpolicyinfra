"""Task type ``vestnesis_list``: one day of the publication-date listing.

GET the likumi.lv day-addressed listing of acts published that day
(``/ta/jaunakie/publiceti/{Y}/{M}/{D}/``) and turn every kept row into a
``vestnesis_doc`` seed. Probed behaviours shaping this handler (samples
in the task folder, probed 2026-09-16; see docs/countries/lva/vestnesis-zh.md):

- The page is server-rendered UTF-8 HTML with no JavaScript dependency.
  The document rows live under the ``sk-jaunakie`` list; a day without an
  issue (weekends, no-gazette days) answers HTTP 200 *without* that
  marker at all — a clean, fully consumed slice: expected_empty, and the
  day cursor still advances (empty windows are confirmed-consumed, USA
  precedent). A page without the ``ta/jaunakie`` navigation marker is not
  a listing page at all: loud shape failure.
- Each row is one ``<li class=''>`` chunk whose tooltip carries the full
  bibliographic set inline (issuer, type, number, adoption date,
  entry-into-force date, loss-of-force date, status, publication
  reference with the gazette link, OP number), so rows parse
  self-contained — the issuer→type group headers need no tracking. The
  publication reference names the gazette issue and date and embeds the
  vestnesis.lv document id, which is the seed key; a few short row
  fields the document page lacks (entry-into-force, number, status,
  loss-of-force, the untruncated title) travel in the seed params.
- One day is one page: the heaviest probed day (2024-12-19, 76 acts)
  renders whole with no pagination.
- scope=state filters out municipal-council issuers at parse time (the
  scope travels in the task params, so widening it later re-enumerates
  with new task identities); the day counts as consumed either way.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.lva.sources.vestnesis import CURSOR_KEY, LIST_BASE, is_municipal_issuer

__all__ = ["VestnesisListHandler"]

#: A listing row is one ``<li class=''>…`` chunk (group headers are plain
#: ``<li>``); only document rows carry the status-icon tooltip.
_ROW_SPLIT = "<li class=''>"
_ROW_MARKER = "statusu-ikonas"

_FIELDS: dict[str, re.Pattern[str]] = {
    "doc_id": re.compile(r"vestnesis\.lv/ta/id/(\d+)"),
    # Title runs to this link's own closer (titles carry no nested anchors)
    # and may embed inline tags in the older eras (e.g. "(<i>sākums</i>)",
    # the gazette's continuation marker — probed 1995-05-04) as well as
    # CRLF soft-wraps inside the anchor (2000-era pages). DOTALL + the
    # whitespace collapse in _field handle both.
    "title": re.compile(r"class='t1[^']*'[^>]*>(.+?)</a>", re.DOTALL),
    "issuer": re.compile(r"Izdevējs: </font><font class='fcw3'>([^<]+)</font>"),
    "veids": re.compile(r"Veids: </font><font class='fcw3'>([^<]+)</font>"),
    "number": re.compile(r"Numurs: </font><font class='fcw3'>([^<]+)</font>"),
    "status": re.compile(r"Statuss: </font><font class='fcw3'>([^<]+)</font>"),
    "adoption": re.compile(r"Pieņemts: </font><font class='fcw3'>(\d{1,2}\.\d{2}\.\d{4})"),
    "entry_into_force": re.compile(r"Stājas spēkā: </font><font class='fcw3'>(\d{1,2}\.\d{2}\.\d{4})"),
    "loss_of_force": re.compile(r"Zaudē spēku: </font><font class='fcw3'>(\d{1,2}\.\d{2}\.\d{4})"),
    # Publication reference: the FIRST "Latvijas Vēstnesis, {issue}, {date}"
    # occurrence — inside a link (usual shape) or a plain span (republication
    # lists, probed 2004-01-29: a treaty re-published across 13 issues lists
    # every reference; the first one is the original publication event).
    "lv_nr": re.compile(r"Latvijas Vēstnesis(?:</a>)?,\s*([^,]+),"),
    "lv_date": re.compile(r"Latvijas Vēstnesis(?:</a>)?,\s*[^,]+,\s*(\d{1,2}\.\d{2}\.\d{4})"),
}

_REQUIRED = ("doc_id", "title", "lv_date")


def _field(chunk: str, name: str) -> str | None:
    match = _FIELDS[name].search(chunk)
    if match is None:
        return None
    value = match.group(1)
    if name == "title":
        value = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", value)).strip()
    return value


def _lv_to_iso(raw: str) -> str:
    """``04.06.2024`` / ``1.07.1993`` -> ``2024-06-04`` / ``1993-07-01``."""
    day, month, year = raw.rstrip(".").split(".")
    return f"{year}-{month}-{int(day):02d}"


class VestnesisListHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        day = date.fromisoformat(str(task.params["date"]))
        return RequestSpec(
            url=(
                f"{LIST_BASE}/ta/jaunakie/publiceti/"
                f"{day.year}/{day.month:02d}/{day.day:02d}/"
            ),
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        day_iso = str(task.params["date"])
        scope = str(task.params.get("scope", "state"))
        try:
            html = response.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"vestnesis_list {day_iso}: listing is not UTF-8 ({exc}) — "
                "encoding may have changed"
            ) from exc

        if "ta/jaunakie" not in html:
            raise ValueError(
                f"vestnesis_list {day_iso}: no jaunakie navigation marker in the "
                "response — the day-addressed listing page may have moved"
            )

        chunks = [
            chunk
            for chunk in html.split(_ROW_SPLIT)[1:]
            if _ROW_MARKER in chunk
        ]
        if not chunks:
            return TaskResult(
                expected_empty=(
                    f"{day_iso}: no gazette issue / no acts published (clean "
                    "empty listing — no sk-jaunakie marker)"
                ),
                cursor_updates={CURSOR_KEY: day_iso},
            )

        seeds: list[TaskSeed] = []
        parsed = 0
        for chunk in chunks:
            values = {name: _field(chunk, name) for name in _FIELDS}
            missing = [name for name in _REQUIRED if not values[name]]
            if missing:
                raise ValueError(
                    f"vestnesis_list {day_iso}: row missing {', '.join(missing)} "
                    "— listing row markup may have changed"
                )
            parsed += 1
            # Correction announcements (Precizējums, probed 2000-01-14) have
            # no issuer in the tooltip at all — unclassifiable rows are kept
            # (the document page remains the issuer authority downstream);
            # only rows that name a municipal council are filtered out.
            issuer = values["issuer"]
            if scope == "state" and issuer is not None and is_municipal_issuer(issuer):
                continue
            pub_iso = _lv_to_iso(values["lv_date"] or "")
            entry_into_force = values["entry_into_force"]
            loss_of_force = values["loss_of_force"]
            params: dict[str, Any] = {
                "doc_id_src": values["doc_id"],
                "pub_date": pub_iso,
                "pub_nr": values["lv_nr"] or "",
                "in_force": _lv_to_iso(entry_into_force) if entry_into_force else "",
                "numurs": values["number"] or "",
                "statuss": values["status"] or "",
                "zaude": _lv_to_iso(loss_of_force) if loss_of_force else "",
                "row_title": values["title"],
                "scope_slice": scope,
            }
            seeds.append(TaskSeed(type="vestnesis_doc", params=params))

        # Rows that fail to parse at all are a shape change (loud); a day
        # whose rows all parse but all fall outside the scope is a
        # legitimate empty yield (explained, cursor still advances).
        if parsed == 0:
            raise ValueError(
                f"vestnesis_list {day_iso}: listing renders {len(chunks)} rows "
                "but none parseable — listing row markup may have changed"
            )
        if not seeds:
            return TaskResult(
                expected_empty=(
                    f"{day_iso}: all {parsed} published acts fall outside "
                    f"scope={scope} (municipal issuers)"
                ),
                cursor_updates={CURSOR_KEY: day_iso},
            )
        return TaskResult(next_tasks=seeds, cursor_updates={CURSOR_KEY: day_iso})
