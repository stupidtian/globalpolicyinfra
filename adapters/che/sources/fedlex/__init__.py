"""The fedlex source: task-type registry, seed generation, shared helpers.

Fedlex (fedlex.admin.ch, operated by the Federal Chancellor's office) is the
official publication platform for federal-law Switzerland. One source, two
layers (each with its own CLI entry):

- **AS** — Amtliche Sammlung / Recueil officiel / Raccolta ufficiale, the
  official collection: publication events, one work per promulgation,
  numbered per year and grouped in memorial issues. The time-series
  backbone. 49,594 works 1848-11-15 → 2026-09 (probed 2026-09-09); digital
  files exist from 1998-09-01 only (earlier works are ledger rows without
  documents — the printed era).
- **SR** — Systematische Sammlung, the classified compilation of law in
  force: 17,299 entries, each an evergreen ``ConsolidationAbstract`` whose
  point-in-time ``Consolidation`` versions (56,370, applicability windows
  native) form the version lineage.

Both layers are read from the platform's public SPARQL 1.1 endpoint (GET,
no key, no session, no browser — probed 2026-09-09; burst querying trips a
connection-drop throttle that self-heals within minutes, hence the
recommended ``--delay 3:6``). Every file URL comes from the graph's
``jolux:isExemplifiedBy`` — never constructed (a guessed filestore URL
returns an HTML error page with HTTP 206, not a 404; probed 2026-09-09).

Multilingual model (first multilingual source in this repo): one work →
one expression per language → manifestations (formats). AS works are
strictly de/fr/it (rm/en counts are 0 across the whole corpus); SR version
expressions occasionally add rm/en. Identity design: the work/entry is the
entity (``as_works`` / ``sr_entries`` rows, ``entity_ref`` target), each
language variant is its own documents row hashing its own file URL.

Task types (each = one module with ``build_request`` + ``parse``):

===============  =====================================================
type             what one task does
===============  =====================================================
che_as_day       seed: one AS publication date — works with their
                 expressions and file URLs in one SPARQL request;
                 upserts as_works, spawns one che_file per
                 (work, language, format); an empty day is a legal
                 empty and still advances the date cursor; caps
                 spawns (not enumeration) at max_works
che_sr_walk      seed: paged enumeration of all SR entries
                 (LIMIT/OFFSET chains); spawns one che_sr_entry per
                 entry; the chain's last page sets the SR modified
                 watermark to the sweep's start timestamp (minus a
                 1-hour skew margin)
che_sr_feed      seed: SR change feed — Consolidations with
                 dct:modified newer than the watermark, ascending;
                 spawns che_sr_entry per touched entry carrying the
                 newest modified stamp as its reopen signal
che_sr_entry     one SR entry's metadata: SR number, basicAct
                 backlink, effectivity window/status, native type
                 label, per-language titles; upserts sr_entries and
                 spawns che_sr_versions carrying the titles through
che_sr_versions  one entry's whole lineage (replaced whole-group) plus
                 the file URLs of the anchor version — the
                 max-dateApplicability version, future-dated scheduled
                 consolidations included (their windows live in the
                 lineage; AUS latest-documented-anchor parity); fills
                 the entry's latest_version_date pointer. (Entry and
                 lineage are two tasks on purpose: the endpoint's
                 degraded windows kill large-join queries while each
                 half alone keeps answering, observed 2026-09-12/13)
che_file         one file from the portal-host filestore (graph URL
                 with the data host swapped for the robots-friendly
                 portal host); magic-byte check per format; document
                 row hanging off the work/entry entity
===============  =====================================================

Params (key=value on the CLI)::

    as_window=2024-01-03:2024-01-05  AS date window (or as_sync=1)
    as_sync=1                          from = day after the kv cursor
                                       fedlex_as_last_date, to = yesterday
    sr_walk=1                          full SR backfill (paged)
    sr_sync=1                          SR feed from the kv watermark
                                       fedlex_sr_last_modified
    sr_since=2026-09-01T00:00:00       explicit feed watermark (catch-up)
    sr_entry={entry-uri}               one entry directly (walkthrough)
    sr=anchor|all                      version scope: anchor files only
                                       (default) or every version's files
    langs=de,fr,it                     language filter (default: all
                                       expressions the graph offers)
    fmts=html                          format filter (default html)
    max_works=N / max_entries=N        spawn caps (test guards)
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "ACCEPT_SPARQL_JSON",
    "AS_CURSOR_KEY",
    "FEED_PAGE",
    "LANG_ALIASES",
    "LANG_CODES",
    "SPARQL_ENDPOINT",
    "SR_CURSOR_KEY",
    "WALK_PAGE",
    "WWW_FILESTORE",
    "build_source",
    "doc_type_for",
    "file_fmt_from_url",
    "normalize_www_url",
    "raw_file_path",
    "start_tasks",
]

SPARQL_ENDPOINT = "https://fedlex.data.admin.ch/sparqlendpoint"
WWW_FILESTORE = "https://www.fedlex.admin.ch/filestore/"
DATA_FILESTORE = "https://fedlex.data.admin.ch/filestore/"
ACCEPT_SPARQL_JSON = {"Accept": "application/sparql-results+json"}

AS_CURSOR_KEY = "fedlex_as_last_date"
SR_CURSOR_KEY = "fedlex_sr_last_modified"
WALK_PAGE = 500
FEED_PAGE = 500

#: EU language-authority code (the graph's ?lang tail) → ISO 639-3 lower.
LANG_CODES = {
    "DEU": "deu",
    "FRA": "fra",
    "ITA": "ita",
    "RMS": "rms",
    "ENG": "eng",
}

#: CLI language aliases (both two- and three-letter forms) → the EU
#: language-authority code the graph's ?lang binding carries.
LANG_ALIASES = {
    "de": "DEU", "fr": "FRA", "it": "ITA", "rm": "RMS", "en": "ENG",
    "deu": "DEU", "fra": "FRA", "ita": "ITA", "rms": "RMS", "eng": "ENG",
}

#: resource-type German label → cross-country doc_type. The mapping keys on
#: the label (not the vocabulary code: plain "Bundesgesetz" carries a label
#: but no skos:notation — probed 2026-09-12; labels are the stable common
#: denominator). Only confident classes are mapped; everything else is
#: OTHER with the native word preserved in meta (section 5.3 rule: never
#: guess). Coverage per the usage census 2026-09-12: the mapped classes
#: account for ~46,000 of 49,594 works.
_DOC_TYPES = {
    "Bundesgesetz": "STATUTE",
    "Dringliches Bundesgesetz": "STATUTE",
    # the source's own spelling of "obligatorischen" is preserved verbatim
    "Bundesbeschluss der dem obligatorschen Referendum untersteht": "STATUTE",
    "Bundesbeschluss der dem fakultativen Referendum untersteht (Verträge)": "STATUTE",
    "Gewährleistungen Kantonsverfassung": "STATUTE",
    "Verordnung des Bundesrates": "REGULATION",
    "Departementsverordnung": "REGULATION",
    "Amtsverordnung": "REGULATION",
    "Verordnung der Bundesversammlung": "REGULATION",
    "Kantonsverfassung": "CONSTITUTION",
    "Erlass des Nationalrates": "SECONDARY_LEGISLATION",
    "Erlass des Ständerates": "SECONDARY_LEGISLATION",
    "Erlass von Kommissionen": "SECONDARY_LEGISLATION",
    "Erlass selbständiger Betriebe und Anstalten": "SECONDARY_LEGISLATION",
}


def doc_type_for(type_de: str | None) -> str:
    return _DOC_TYPES.get((type_de or "").strip(), "OTHER")


def normalize_www_url(graph_url: str) -> str:
    """The graph serves filestore URLs on the data host; downloads and
    source_url use the portal host (robots: Allow /) — same path."""
    if graph_url.startswith(DATA_FILESTORE):
        return WWW_FILESTORE + graph_url[len(DATA_FILESTORE):]
    return graph_url


def file_fmt_from_url(url: str) -> str:
    """Format of one filestore URL = the path segment before the filename
    (…/eli/oc/2026/449/fr/html/<name>.html → html)."""
    segments = url.rstrip("/").split("/")
    return segments[-2]


def raw_file_path(kind: str, url: str, sr_number: str | None = None) -> str:
    """01_raw layout from a filestore URL (§6.7: top level = source, one
    policy one folder, source filename verbatim).

    AS:  ``01_raw/fedlex/as/{volume}/{number}/{filename}`` — the volume
    segment is the year for modern works and a roman numeral for the
    1848–1961 era, taken from the work URI either way.
    SR:  ``01_raw/fedlex/sr/{SR number}/{intro-ids}/{filename}`` — the SR
    number is not unique across eras (SR 101 is both the 1874 and the 1999
    constitution), so the entry's intro ids ride along to keep folders
    unique.
    """
    after_store = url.split("/filestore/", 1)[1]
    segments = after_store.split("/")  # fedlex.data.admin.ch/eli/{oc|cc}/...
    filename = segments[-1]
    if kind == "as":
        volume, number = segments[3], segments[4]
        return f"01_raw/fedlex/as/{volume}/{number}/{filename}"
    if kind == "sr":
        if not sr_number:
            raise ValueError("sr file path needs the entry's SR number")
        ids = segments[4]
        return f"01_raw/fedlex/sr/{sr_number}/{ids}/{filename}"
    raise ValueError(f"unknown file kind {kind!r}")


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country che --source fedlex "
        "as_window=2024-01-03:2024-01-05\n"
        "  python cli.py collect --country che --source fedlex as_sync=1\n"
        "  python cli.py collect --country che --source fedlex sr_walk=1\n"
        "  python cli.py collect --country che --source fedlex sr_sync=1\n"
        "  python cli.py status --country che --source fedlex"
    )


def _parse_date(raw: str, label: str) -> str:
    try:
        date.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{label} must be an ISO date YYYY-MM-DD (got {raw!r})") from None
    return raw


def _mode(params: dict[str, Any]) -> dict[str, str]:
    """Sweep options flowing down the chains (part of task identity —
    widening them later means new task ids, never a rebuild)."""
    fmts = str(params.get("fmts", "html")).strip() or "html"
    langs = str(params.get("langs", "")).strip()
    if langs:
        unknown = [x for x in langs.split(",") if x.strip() not in LANG_ALIASES]
        if unknown:
            raise _fail(
                f"langs must be a comma list of {sorted(LANG_ALIASES)} (got {langs!r})"
            )
    sr_mode = str(params.get("sr", "anchor")).strip()
    if sr_mode not in ("anchor", "all"):
        raise _fail(f"sr must be anchor or all (got {sr_mode!r})")
    return {"fmts": fmts, "langs": langs, "sr": sr_mode}


def _positive_int(params: dict[str, Any], key: str) -> str | None:
    raw = str(params.get(key, "")).strip()
    if not raw:
        return None
    if not raw.isdigit() or int(raw) < 1:
        raise _fail(f"{key} must be a positive integer (got {raw!r})")
    return raw


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    mode = _mode(params)
    max_works = _positive_int(params, "max_works")
    max_entries = _positive_int(params, "max_entries")
    seeds: list[TaskSeed] = []

    as_window = str(params.get("as_window", "")).strip()
    as_sync = str(params.get("as_sync", "")).strip() in ("1", "true", "yes")
    sr_walk = str(params.get("sr_walk", "")).strip() in ("1", "true", "yes")
    sr_sync = str(params.get("sr_sync", "")).strip() in ("1", "true", "yes")
    sr_since = str(params.get("sr_since", "")).strip()
    sr_entry = str(params.get("sr_entry", "")).strip()

    if sum(1 for flag in (as_window, as_sync, sr_walk, sr_sync, sr_since, sr_entry) if flag) != 1:
        raise _fail(
            "give exactly one entry: as_window=FROM:TO | as_sync=1 | "
            "sr_walk=1 | sr_sync=1 | sr_since=ISO_DATETIME | sr_entry=URI"
        )

    if as_window:
        from_str, sep, to_str = as_window.partition(":")
        if not sep or not from_str or not to_str:
            raise _fail(f"as_window must look like FROM:TO (got {as_window!r})")
        from_str = _parse_date(from_str.strip(), "as_window FROM")
        to_str = _parse_date(to_str.strip(), "as_window TO")
        if from_str > to_str:
            raise _fail(f"as_window start {from_str} is after its end {to_str}")
        day = date.fromisoformat(from_str)
        end = date.fromisoformat(to_str)
        while day <= end:
            seeds.append(
                TaskSeed(type="che_as_day", params={**mode, "date": day.isoformat(),
                                                    **({"max_works": max_works} if max_works else {})})
            )
            day += timedelta(days=1)
        return seeds

    if as_sync:
        kv = params.get("_kv", {})
        cursor = kv.get(AS_CURSOR_KEY)
        if not cursor:
            raise _fail("as_sync=1 needs a previous sweep; run as_window=… first")
        from_str = (date.fromisoformat(cursor) + timedelta(days=1)).isoformat()
        # End at yesterday: today's memorial can still gain entries until
        # the issue closes (4 works already visible on 2026-09-09 at
        # midday — the ESP/FRA late-publication precaution).
        to_str = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
        if from_str > to_str:
            return []  # already in sync
        day = date.fromisoformat(from_str)
        while day <= date.fromisoformat(to_str):
            seeds.append(
                TaskSeed(type="che_as_day", params={**mode, "date": day.isoformat(),
                                                    **({"max_works": max_works} if max_works else {})})
            )
            day += timedelta(days=1)
        return seeds

    if sr_walk:
        # The watermark the feed will resume from: this sweep's start
        # (minus a 1h clock-skew margin). Set only by the chain's last
        # page, so a crashed walk never advances it.
        mark_ts = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        seed_params: dict[str, Any] = {**mode, "offset": 0, "mark_ts": mark_ts}
        if max_entries:
            seed_params["max_entries"] = max_entries
        seeds.append(TaskSeed(type="che_sr_walk", params=seed_params))
        return seeds

    if sr_sync or sr_since:
        if sr_sync:
            kv = params.get("_kv", {})
            since = kv.get(SR_CURSOR_KEY)
            if not since:
                raise _fail("sr_sync=1 needs a watermark; run sr_walk=1 first "
                            "(or give sr_since=ISO_DATETIME)")
        else:
            since = sr_since
            try:
                datetime.fromisoformat(since)
            except ValueError:
                raise _fail(
                    f"sr_since must be an ISO datetime (got {since!r})"
                ) from None
        seeds.append(TaskSeed(type="che_sr_feed", params={**mode, "since": since, "offset": 0}))
        return seeds

    # sr_entry: single-entry walkthrough
    if not sr_entry.startswith("https://fedlex.data.admin.ch/eli/cc/"):
        raise _fail(f"sr_entry must be an SR entry URI …/eli/cc/… (got {sr_entry!r})")
    return [TaskSeed(type="che_sr_entry", params={**mode, "entry_uri": sr_entry})]


#: Three domain tables (per ARCHITECTURE.md section 6.4 the corpus has real
#: cross-document persistent entities on both layers): the AS publication
#: event groups a work's language variants and — before 1998-09-01 — is the
#: only record the event ever happened (no files exist); the SR entry is a
#: law with a version lineage no single document can express.
DOMAIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS as_works (
    work_uri TEXT PRIMARY KEY,
    seq INTEGER,
    publication_date TEXT NOT NULL,
    date_document TEXT,
    date_entry_in_force TEXT,
    date_no_longer_in_force TEXT,
    sr_class TEXT,
    issue INTEGER,
    type_de TEXT,
    institution_de TEXT,
    institution_fr TEXT,
    title_de TEXT,
    title_fr TEXT,
    title_it TEXT
);
CREATE TABLE IF NOT EXISTS sr_entries (
    entry_uri TEXT PRIMARY KEY,
    sr_number TEXT,
    basic_act TEXT,
    date_document TEXT,
    date_entry_in_force TEXT,
    date_no_longer_in_force TEXT,
    in_force_status TEXT,
    historical_legal_id TEXT,
    title_de TEXT,
    title_fr TEXT,
    latest_version_date TEXT
);
CREATE TABLE IF NOT EXISTS sr_versions (
    entry_uri TEXT NOT NULL,
    version_date TEXT NOT NULL,
    date_end_applicability TEXT,
    modified TEXT,
    is_current INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (entry_uri, version_date)
);
"""


def build_source() -> SourceDefinition:
    from adapters.che.sources.fedlex.as_day import CheAsDayHandler
    from adapters.che.sources.fedlex.file import CheFileHandler
    from adapters.che.sources.fedlex.sr_entry import CheSrEntryHandler
    from adapters.che.sources.fedlex.sr_feed import CheSrFeedHandler
    from adapters.che.sources.fedlex.sr_versions import CheSrVersionsHandler
    from adapters.che.sources.fedlex.sr_walk import CheSrWalkHandler

    return SourceDefinition(
        name="fedlex",
        start_tasks=start_tasks,
        task_types={
            "che_as_day": CheAsDayHandler(),
            "che_sr_walk": CheSrWalkHandler(),
            "che_sr_feed": CheSrFeedHandler(),
            "che_sr_entry": CheSrEntryHandler(),
            "che_sr_versions": CheSrVersionsHandler(),
            "che_file": CheFileHandler(),
        },
        domain_schema=DOMAIN_SCHEMA,
        domain_tables=("as_works", "sr_entries", "sr_versions"),
        domain_keys={
            "as_works": ("work_uri",),
            "sr_entries": ("entry_uri",),
            "sr_versions": ("entry_uri", "version_date"),
        },
    )
