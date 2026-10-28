"""The `gazette` source: the Gazette of India e-Gazette portal
(egazette.gov.in), the statutory publication medium of the Union
government (General Clauses Act 1897 s. 3(24) defines the "Official
Gazette" as the Gazette of India; s. 22 makes Gazette publication the
condition for rules to take effect). Every issue ever published as one
row = one as-made snapshot; the complete time series of central
legislation, ordinances and subordinate legislation lives here.

Machine channel (probed live 2026-10-04..15, see
docs/tasks/2026-10-02-ind/probe/README.md):

- **Cookieless ASP.NET session**: the root URL 302s to
  ``/(S(id))/default.aspx``; the live session id is the *modal*
  ``(S(id))`` across the rendered page (asset paths such as
  ``/(S(id))/images/...`` repeat it; a single stale hard-coded link to
  egazette.nic.in also carries an old id — never take the first match).
- **Deep pages require a same-session Referer**: every request past the
  homepage sends ``Referer: {SITE}/(S(sid))/default.aspx``; without it
  the server bounces 302 -> error.aspx (this is what the web-archive
  crawlers hit, not anti-bot).
- **Two entries**: ``RecentUploads.aspx?Category=1`` = the latest 100
  uploads (about 3 days; 20 rows/page, page 1 used for v1) — the
  freshness window; ``GazetteDirectory.aspx`` = the backfill filter
  (Extra Ordinary/Weekly x Part/Section x Year, 1926..2026), an ASP.NET
  PostBack cascade driven through ``form_body`` (contract 2026-10-15).
- **Files are session-free**: ``/WriteReadData/{year}/{serial}.pdf``
  answers a bare GET; the serial is the UGID tail
  (``CG-{region}-{E|W}-{DDMMYYYY}-{serial}``; federal issues are
  ``CG-DL-*``, other regions are state gazettes and out of scope).
- **Page state (``__VIEWSTATE`` class) never enters task params**
  (contract discipline 2026-10-15): the PostBack chain couriers it in
  the task's ``signal`` field — identity stays the (type, params)
  tuple, and a changed signal legitimately reopens a done chain task
  whose upstream page re-rendered.

Task types (each = one module-level handler, build_request + parse):

================  =====================================================
type              what one task does
================  =====================================================
gz_home           GET the portal root (redirect-following); parse the
                  modal session id and seed the entry chains asked for
                  on the command line. Per-run ``nonce`` param (DEU
                  session-seed precedent): session-bound subtrees
                  re-execute each run; file tasks downstream stay
                  done-skipped.
gz_recent         GET RecentUploads Category=1 page 1 (same-session
                  Referer); each federal row seeds one gz_file.
                  v1 covers page 1 (newest 20 of the 100-item
                  window) — sync at least every couple of days;
                  older rows belong to the directory backfill.
gz_dir_open       GET GazetteDirectory.aspx; parse the PostBack
                  hidden fields into the page-state signal; seed
                  gz_dir_cat.
gz_dir_cat        POST the category cascade
                  (__EVENTTARGET=ddlCategory); the response repopulates
                  Part/Section; seed gz_dir_search with fresh state.
gz_dir_search     POST the search (btnSubmit) with
                  category/part/year; each federal result row seeds
                  one gz_file; zero rows is an explained empty.
gz_file           GET the issue PDF (bare, session-free). Registers
                  the document (row metadata rides in params) and
                  stores the bytes verbatim.
================  =====================================================

Params (key=value on the CLI)::

    recent=1      freshness window: home -> RecentUploads page 1
    dir=2026:1:EO[,2026:38:W...]   directory backfill per spec
                  YYYY:PART:CAT, PART = the site's own option value
                  (e.g. 1 = Part I-Section 1, 38 = No Part No Section,
                  61 = Part I — passed through verbatim), CAT = EO
                  (Extra Ordinary) or W (Weekly)
    (both may be combined; at least one is required)
"""

from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from datetime import date
from html import unescape
from typing import Any

from adapters.base import SourceDefinition, TaskSeed
from runtime.errors import PermanentError

__all__ = [
    "DIR_CATEGORIES",
    "RECENT_CATEGORY",
    "ROW_LABELS",
    "SITE",
    "build_source",
    "extract_hidden_state",
    "extract_rows",
    "extract_session_sid",
    "page_state_to_signal",
    "parse_dir_spec",
    "parse_ugid",
    "signal_to_page_state",
    "start_tasks",
]

SITE = "https://egazette.gov.in"

#: RecentUploads category "1" = the mixed recent-uploads window (the
#: freshest ~100 issues; federal rows are filtered client-side).
RECENT_CATEGORY = "1"

#: GazetteDirectory category values (site-native labels).
DIR_CATEGORIES = {"EO": "Extra Ordinary", "W": "Weekly"}

#: The result-grid label series (identical on RecentUploads and the
#: directory search); one gazette row = one issue PDF.
ROW_LABELS: tuple[str, ...] = (
    "Category",
    "Department",
    "FileSize",
    "IssueDate",
    "Ministry",
    "Office",
    "PartSection",
    "PublishDate",
    "Subject",
    "UGID",
)

_UGID_RE = re.compile(r"CG-([A-Z]+)-([EW])-(\d{8})-(\d+)")
_SID_RE = re.compile(r"/\(S\(([a-z0-9]+)\)\)")
_DIR_SPEC_RE = re.compile(r"^(\d{4}):([^:,]+):(EO|W)$")
_INPUT_RE = re.compile(r"<input[^>]*name=\"([^\"]+)\"[^>]*>", re.DOTALL)
_VALUE_RE = re.compile(r"value=\"([^\"]*)\"")
_SELECT_RE = re.compile(r"<select[^>]*name=\"(ddl[A-Za-z]+)\"[^>]*>(.*?)</select>", re.DOTALL)
_OPTION_TAG_RE = re.compile(r"<option([^>]*)>")


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country ind --source gazette recent=1\n"
        "  python cli.py collect --country ind --source gazette dir=2026:1:EO\n"
        "  python cli.py collect --country ind --source gazette dir=2026:38:W recent=1\n"
        "  python cli.py status --country ind --source gazette"
    )


def extract_session_sid(html: str) -> str:
    """The live cookieless-session id = the *modal* ``(S(id))`` on the
    rendered page. Server-rendered asset paths repeat the current id;
    a lone stale hard-coded link also carries an old one, so first-match
    lies (probed live 2026-10-15: stale ``10z20...`` vs live asset id)."""
    counts = Counter(_SID_RE.findall(html))
    if not counts:
        raise PermanentError("gazette home: no session id in page (unexpected shape)")
    sid = counts.most_common(1)[0][0]
    return str(sid)


def _current_select_value(select_html: str) -> str:
    """The value a browser would submit for this select: the option
    carrying ``selected`` if any, else the first option (HTML-unescaped,
    probed live: ddlPartSection's initial value is 'Select Part &
    Section' with an encoded ampersand)."""
    chosen: str | None = None
    first: str | None = None
    for match in _OPTION_TAG_RE.finditer(select_html):
        attrs = match.group(1)
        value_match = _VALUE_RE.search(attrs)
        value = unescape(value_match.group(1)) if value_match else ""
        if first is None:
            first = value
        if re.search(r"^\s*selected\b", " " + attrs.strip()):
            chosen = value
            break
    result = chosen if chosen is not None else first
    if result is None:
        raise PermanentError("gazette page: select without options")
    return result


def extract_hidden_state(html: str) -> dict[str, Any]:
    """PostBack page state from one render: the three identity-bearing
    hidden fields plus every other input's current value and every
    select's would-submit value. This dict travels as the next task's
    ``signal`` — never as params (contract discipline 2026-10-15)."""
    state: dict[str, Any] = {"extra": {}}
    for match in _INPUT_RE.finditer(html):
        name = match.group(1)
        value = _VALUE_RE.search(match.group(0))
        text = unescape(value.group(1)) if value else ""
        if name == "__VIEWSTATE":
            state["vs"] = text
        elif name == "__EVENTVALIDATION":
            state["ev"] = text
        elif name == "__VIEWSTATEGENERATOR":
            state["gen"] = text
        else:
            state["extra"][name] = text
    for match in _SELECT_RE.finditer(html):
        state["extra"][match.group(1)] = _current_select_value(match.group(2))
    if not state.get("vs") or not state.get("ev"):
        raise PermanentError(
            "gazette page: no PostBack state (wrong page or session bounce)"
        )
    return state


def page_state_to_signal(state: dict[str, Any]) -> str:
    return json.dumps(state, ensure_ascii=False, separators=(",", ":"))


def signal_to_page_state(signal: str | None) -> dict[str, Any]:
    if not signal:
        raise PermanentError("gazette postback task without page-state signal")
    try:
        state = json.loads(signal)
    except json.JSONDecodeError as exc:
        raise PermanentError(f"gazette page-state signal is not JSON: {exc}") from None
    if not isinstance(state, dict) or "vs" not in state or "ev" not in state:
        raise PermanentError("gazette page-state signal lacks vs/ev")
    return state


def parse_ugid(ugid: str) -> dict[str, str]:
    """``CG-{region}-{E|W}-{DDMMYYYY}-{serial}`` — federal issues are
    printed at Delhi (region DL); any other region is a state gazette."""
    match = _UGID_RE.fullmatch(ugid.strip())
    if not match:
        raise PermanentError(f"unrecognised UGID shape: {ugid!r}")
    region, kind, ddmmyyyy, serial = match.groups()
    date_iso = date(
        int(ddmmyyyy[4:]), int(ddmmyyyy[2:4]), int(ddmmyyyy[:2])
    ).isoformat()
    return {
        "region": region,
        "kind": kind,
        "date": date_iso,
        "serial": serial,
        "year": ddmmyyyy[-4:],
    }


def is_federal(ugid: str) -> bool:
    return parse_ugid(ugid)["region"] == "DL"


def extract_rows(html: str) -> list[dict[str, str]]:
    """Result-grid rows: zip the label series by row index (a missing
    series or ragged counts is a loud shape error — probe rule: shapes
    not seen during probing are production shapes)."""
    series: dict[str, list[str]] = {}
    for label in ROW_LABELS:
        values = re.findall(
            r"gvGazetteList_lbl_" + label + r"_\d+\"[^>]*>(.*?)</span>", html, re.DOTALL
        )
        series[label] = [unescape(re.sub(r"<[^>]+>", "", v)).strip() for v in values]
    lengths = {len(v) for v in series.values()}
    if not lengths or lengths != {len(series["UGID"])}:
        raise PermanentError("gazette grid: ragged row series (unexpected shape)")
    if not series["UGID"]:
        return []
    return [
        {label: series[label][i] for label in ROW_LABELS}
        for i in range(len(series["UGID"]))
    ]


def parse_dir_spec(raw: str) -> dict[str, str]:
    match = _DIR_SPEC_RE.fullmatch(raw.strip())
    if not match:
        raise _fail(
            f"dir spec must look like YYYY:PART:CAT with CAT in EO|W (got {raw!r})"
        )
    year, part, cat = match.groups()
    return {"year": year, "part": part, "cat": cat, "label": DIR_CATEGORIES[cat]}


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    recent = str(params.get("recent", "")).strip() in ("1", "true", "yes")
    raw_specs = str(params.get("dir", "")).strip()
    specs = [parse_dir_spec(s) for s in raw_specs.split(",") if s.strip()] if raw_specs else []
    if not recent and not specs:
        raise _fail("give recent=1 and/or dir=YYYY:PART:CAT[, ...]")

    nonce = params.get("_nonce")  # test seam; the engine never passes it
    if not isinstance(nonce, str) or not nonce:
        nonce = uuid.uuid4().hex[:12]

    home: dict[str, Any] = {"nonce": nonce}
    if recent:
        home["recent"] = "1"
    if specs:
        home["dir"] = [f"{s['year']}:{s['part']}:{s['cat']}" for s in specs]
    return [TaskSeed(type="gz_home", params=home)]


def build_source() -> SourceDefinition:
    from adapters.ind.sources.gazette.browse import (
        GzDirOpenHandler,
        GzHomeHandler,
        GzRecentHandler,
    )
    from adapters.ind.sources.gazette.file import GzFileHandler
    from adapters.ind.sources.gazette.postbacks import (
        GzDirCatHandler,
        GzDirSearchHandler,
    )

    return SourceDefinition(
        name="gazette",
        start_tasks=start_tasks,
        task_types={
            "gz_home": GzHomeHandler(),
            "gz_recent": GzRecentHandler(),
            "gz_dir_open": GzDirOpenHandler(),
            "gz_dir_cat": GzDirCatHandler(),
            "gz_dir_search": GzDirSearchHandler(),
            "gz_file": GzFileHandler(),
        },
        # Session-bound chain (cookieless ASP.NET id + same-session
        # Referer): tasks of one run share server-side state, so the
        # source stays single-worker (engine caps undeclared sources).
        parallel_safe=False,
    )
