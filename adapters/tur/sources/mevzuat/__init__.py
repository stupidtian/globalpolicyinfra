"""The mevzuat source: task-type registry, seed generation, entity DDL.

Mevzuat Bilgi Sistemi (mevzuat.gov.tr), Turkey's consolidated-current
legislation registry run by the Presidency's Directorate of Law and
Legislation (online since 1995-06-01; probed 2026-09-27, samples in the
task folder; see docs/countries/tur/mevzuat-zh.md). Registry-shaped
source with one persistent entity per regulation: identity is the triple
``(MevzuatTur, MevzuatNo, MevzuatTertip)`` — Tertip is the Düstür
compilation era (3 ≈ 1960s, 5 = current). "Kodifiye" (consolidation)
means the site merges every amendment into one current text; publication
originals are the resmigazete source's job. Both endpoints are key-free,
cookie-free JSON/HTML (the old hardcoded antiforgery token was never
needed).

Task types:

===============  =====================================================
type             what one task does
===============  =====================================================
mev_list         one page of one type's catalogue (``POST
                 /anasayfa/MevzuatDatatable``, DataTables envelope +
                 ``parameters``): every record upserts a ``mevzuat``
                 entity row and seeds one mev_metin; a full page seeds
                 the next page (``pages=`` caps the walk for trial
                 runs). Unknown type codes fall back to the whole
                 catalogue server-side, so turs are validated against
                 the known set at seed time.
mev_metin        one entity's consolidated text (``GET
                 /anasayfa/MevzuatFihristDetayIframe?…``): stored
                 verbatim as ``metin.html``; the header block (statute
                 number, adoption/BKK date, gazette date+issue with
                 Mükerrer note, Düstür volume/page, underlying statute)
                 enriches the entity row and cross-checks the seed —
                 five probed dialects; tebliğ (tur 9) carries no header
                 at all and rides on the seed.
mev_pdf          the file-only entity's text PDF (``GET /MevzuatMetin/
                 {t}.{r}.{n}.pdf``): for records with ``fileType=2`` —
                 no iframe body exists (the whole CB Kararı corpus,
                 probed 2026-09-28), so the PDF is the only text, not a
                 redundant rendering. Stored verbatim as ``metin.pdf``;
                 the mandatory PDF-magic check turns the endpoint's
                 200+HTML fake pages into loud failures.
===============  =====================================================

Params (key=value on the CLI)::

    turs=1,2,3,4,5,9,19,20,21   mevzuat type codes to walk (default =
                                 core legislative types plus the whole
                                 Yönetmelik family, user-ruled 2026-09-28;
                                 3 is the union of 7/8/10 — pass either
                                 form, never both)
    pages=2                      per type, stop after this many pages
                                 (trial runs; default = walk to the end)
    refresh=2026-10-01T09:00:00  parameterized reopen: changes list-task
                                 identities so the catalogue is re-walked
                                 (new entities fetch; done metin tasks
                                 are skipped — KOR refresh semantics).
"""

from __future__ import annotations

import re
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "API_BASE",
    "DEFAULT_TURS",
    "KNOWN_TURS",
    "PAGE_SIZE",
    "build_source",
    "detail_url",
    "to_iso_date",
]

API_BASE = "https://www.mevzuat.gov.tr"
PAGE_SIZE = 100

#: Real type codes (probed 2026-09-27). Codes 0/6/16/17/18 answer any
#: query with the whole catalogue, so unknown codes are rejected up front.
KNOWN_TURS: frozenset[int] = frozenset({0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 16, 17, 18, 19, 20, 21})

#: User-ruled default (2026-09-28): core legislative types + full
#: Yönetmelik family (3 = the union of 7/8/10).
DEFAULT_TURS = "1,2,3,4,5,9,19,20,21"

_TR_DOTS_RE = re.compile(r"^(\d{1,2})[.](\d{1,2})[.](\d{4})$")


def to_iso_date(raw: str | None) -> str | None:
    """'18.08.2026' → '2026-08-18' (registry dates are dd.mm.yyyy)."""
    if not raw:
        return None
    match = _TR_DOTS_RE.match(raw.strip())
    if not match:
        return None
    d, m, y = match.groups()
    return f"{y}-{m.zfill(2)}-{d.zfill(2)}"


def detail_url(tur: int, no: str, tertip: int) -> str:
    """Canonical, rebuildable detail-page address (the doc's source_url)."""
    return f"{API_BASE}/mevzuat?MevzuatNo={no}&MevzuatTur={tur}&MevzuatTertip={tertip}"


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country tur --source mevzuat turs=19\n"
        "  python cli.py collect --country tur --source mevzuat turs=1 pages=2\n"
        "  python cli.py collect --country tur --source mevzuat\n"
        "  python cli.py collect --country tur --source mevzuat refresh=2026-10-01T09:00:00\n"
        "  python cli.py status --country tur --source mevzuat"
    )


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    raw_turs = str(params.get("turs", DEFAULT_TURS))
    try:
        turs = [int(part.strip()) for part in raw_turs.split(",") if part.strip()]
    except ValueError:
        raise _fail(f"turs must be a comma list of integers (got {raw_turs!r})") from None
    if not turs:
        raise _fail("turs must not be empty")
    unknown = sorted(set(turs) - KNOWN_TURS)
    if unknown:
        raise _fail(
            f"unknown type codes {unknown} (known: {sorted(KNOWN_TURS)}); "
            "the server answers unknown codes with the whole catalogue"
        )
    if 3 in turs and ({7, 8, 10} & set(turs)):
        raise _fail("turs mixes 3 with 7/8/10 — type 3 already is their union")

    pages = 0
    if params.get("pages"):
        try:
            pages = int(str(params["pages"]))
        except ValueError:
            raise _fail(f"pages must be an integer (got {params['pages']!r})") from None
        if pages < 1:
            raise _fail(f"pages must be >= 1 (got {pages})")

    refresh = str(params["refresh"]).strip() if params.get("refresh") else None

    seeds: list[TaskSeed] = []
    for tur in turs:
        seed_params: dict[str, Any] = {"tur": tur, "start": 0}
        if pages:
            seed_params["pages"] = pages
        if refresh:
            seed_params["refresh"] = refresh
        seeds.append(TaskSeed(type="mev_list", params=seed_params))
    return seeds


_MEVZUAT_DDL = """
CREATE TABLE IF NOT EXISTS mevzuat (
  mevzuat_tur     INTEGER NOT NULL,
  mevzuat_no      TEXT    NOT NULL,
  mevzuat_tertip  INTEGER NOT NULL,
  mevzuat_adi     TEXT,
  kabul_tarihi    TEXT,
  rg_tarihi       TEXT,
  rg_sayisi       TEXT,
  mukerrer        TEXT,
  PRIMARY KEY (mevzuat_tur, mevzuat_no, mevzuat_tertip)
);
"""


def build_source() -> SourceDefinition:
    from adapters.tur.sources.mevzuat.catalog import MevListHandler
    from adapters.tur.sources.mevzuat.metin import MevMetinHandler
    from adapters.tur.sources.mevzuat.pdf import MevPdfHandler

    return SourceDefinition(
        name="mevzuat",
        start_tasks=start_tasks,
        task_types={
            "mev_list": MevListHandler(),
            "mev_metin": MevMetinHandler(),
            "mev_pdf": MevPdfHandler(),
        },
        domain_schema=_MEVZUAT_DDL,
        domain_tables=("mevzuat",),
        domain_keys={"mevzuat": ("mevzuat_tur", "mevzuat_no", "mevzuat_tertip")},
        parallel_safe=True,  # stateless JSON POST + GET, no cookies (probed 2026-09-27)
    )
