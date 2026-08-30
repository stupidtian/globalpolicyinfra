"""The lawgokr source: task-type registry, seed generation, shared parsing.

현행법령 (current statutes & decrees) of the 국가법령정보센터,
https://www.law.go.kr — the whole corpus of laws in force (statutes,
presidential/prime-ministerial/ministerial decrees, constitutional-organ
rules mixed in one list; official count 5,605 as of 2026-08-12, ~6,732 rows
including scheduled future-effective versions).

Pure GET/POST-tolerant endpoints (probed 2026-08-29/30: GET query strings
return byte-identical responses to the browser's POST forms, so the
GET-oriented transport works unchanged). No cookies, no csrf, no API key —
unlike DEU/bgbl there is no session bootstrap at all.

Versioning (the lifecycle backbone): a law's identity is ``lsId`` (stable
across amendments); every amendment creates a *new version* with its own
``lsiSeq`` and effective date ``efYd``. The current list discovers laws;
``lsHstListR.do`` returns any version's full timeline; the body endpoint
serves historical versions with the same response shape as current ones.

Task types (each = one module with ``build_request`` + ``parse``):

===============  =====================================================
type             what one task does
===============  =====================================================
kor_list         one list page (50 rows); spawns one kor_body per row;
                 with walk=1 a full page also spawns pg+1 (a page beyond
                 the last returns HTTP 200 with zero rows — expected_empty
                 stops the chain)
kor_body         one version's body + metadata (title, abbreviation,
                 promulgation no/date/type, ministry, articles); document
                 + file; spawns kor_versions (carrying lsId) + kor_reason
kor_versions     one law's version timeline; spawns kor_body + kor_reason
                 per historical version (the already-done current version
                 dedups by task_id)
kor_reason       one version's 제정·개정이유 (official amendment reason,
                 one per version); companion document + file
===============  =====================================================

Params (key=value on the CLI)::

    pages=1-2          required: "1", "1-2", "1,3" or "all"
                       (all = walk from pg=1 to the last page)
    max_laws=5         optional cap on kor_body spawns per list page
"""

from __future__ import annotations

import html as html_mod
import re
from typing import Any

from adapters.base import SourceDefinition, TaskSeed

__all__ = [
    "BASE_URL",
    "PAGE_SIZE",
    "body_params",
    "build_source",
    "canonical_body_url",
    "canonical_reason_url",
    "korean_date_to_iso",
    "list_params",
    "parse_pubinfo",
    "start_tasks",
    "xhr_headers",
]

BASE_URL = "https://www.law.go.kr"
PAGE_SIZE = 50


def xhr_headers(referer: str) -> dict[str, str]:
    """Headers every law.go.kr XHR endpoint expects (probed 2026-08-30)."""
    return {"X-Requested-With": "XMLHttpRequest", "Referer": referer}


def list_params(pg: int) -> dict[str, str]:
    """K1 form fields exactly as the browser posts them (probed shape).

    ``fsort=10,41,21,31`` is the default sort — stable across months
    (cross-checked against the 2026-04 Selenium baseline, same first rows).
    """
    return {
        "menuId": "1",
        "subMenuId": "15",
        "tabMenuId": "81",
        "q": "*",
        "outmax": str(PAGE_SIZE),
        "p7": "0",
        "p19": "1,3",
        "pg": str(pg),
        "fsort": "10,41,21,31",
        "lsType": "null",
        "section": "lawNm",
        "lsiSeq": "0",
        "p9": "2,4",
    }


def body_params(seq: str, ef_yd: str) -> dict[str, str]:
    """K2/K5 form fields — the lsValue serialization makeParam() emits."""
    return {
        "lsiSeq": seq,
        "efYd": ef_yd,
        "efYn": "Y",
        "nwJoYnInfo": "Y",
        "efGubun": "Y",
        "chrClsCd": "010202",
        "ancYnChk": "0",
        "netPrivateYn": "N",
        "vSct": "*",
    }


def canonical_body_url(seq: str, ef_yd: str) -> str:
    """Stable, rebuildable URL of one version (doc_id hashes this)."""
    return f"{BASE_URL}/lsInfoP.do?lsiSeq={seq}&efYd={ef_yd}"


def canonical_reason_url(seq: str, ef_yd: str) -> str:
    return f"{BASE_URL}/lsRvsDocInfoR.do?lsiSeq={seq}&efYd={ef_yd}"


def korean_date_to_iso(text: str) -> str | None:
    """'2023. 8. 8.' -> '2023-08-08' (first date inside the text)."""
    match = re.search(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})", text)
    if match is None:
        return None
    year, month, day = (int(g) for g in match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


def parse_pubinfo(text: str) -> dict[str, str]:
    """Parse a '[시행 …] [법률 제19592호, 2023. 8. 8., 타법개정]' header.

    Returns whatever it finds — keys: effective_date (ISO), promulgation_type,
    promulgation_no, promulgation_date (ISO), amendment_type. Missing pieces
    are simply absent; callers decide on fallbacks.
    """
    out: dict[str, str] = {}
    effective = re.search(r"\[시행\s*([^\]]*)\]", text)
    if effective is not None:
        out["effective_date"] = korean_date_to_iso(effective.group(1)) or ""
        out["effective_raw"] = html_mod.unescape(effective.group(1)).strip()
    promulgation = re.search(
        r"\[\s*([^\s,\]]+)\s*제\s*(\d+)\s*호\s*,?\s*([^\]]*)\]", text
    )
    if promulgation is not None:
        out["promulgation_type"] = html_mod.unescape(promulgation.group(1))
        out["promulgation_no"] = promulgation.group(2)
        rest = promulgation.group(3)
        date = korean_date_to_iso(rest)
        if date is not None:
            out["promulgation_date"] = date
        parts = [p.strip() for p in rest.split(",") if p.strip()]
        if parts:
            out["amendment_type"] = parts[-1]
    return out


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country kor --source lawgokr pages=1-2\n"
        "  python cli.py collect --country kor --source lawgokr pages=1 max_laws=5\n"
        "  python cli.py collect --country kor --source lawgokr pages=all\n"
        "  python cli.py status --country kor --source lawgokr"
    )


def _parse_pages(raw: str) -> list[int] | str:
    """"all" | "1" | "1,3" | "1-2" -> sorted page numbers, or "all"."""
    raw = raw.strip()
    if raw.lower() == "all":
        return "all"
    numbers: set[int] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        lo_str, sep, hi_str = token.partition("-")
        try:
            lo = int(lo_str)
            hi = int(hi_str) if sep else lo
        except ValueError:
            raise _fail(f"pages token {token!r} is not a number or range") from None
        if lo < 1 or hi < lo:
            raise _fail(f"pages token {token!r} is not a valid ascending range")
        numbers.update(range(lo, hi + 1))
    if not numbers:
        raise _fail('pages must be "all", a list like 1,3 or a range like 1-2')
    return sorted(numbers)


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    raw_pages = str(params.get("pages", "")).strip()
    if not raw_pages:
        raise _fail("pages is required")
    pages = _parse_pages(raw_pages)

    max_laws: int | None = None
    raw_max = str(params.get("max_laws", "")).strip()
    if raw_max:
        try:
            max_laws = int(raw_max)
        except ValueError:
            raise _fail(f"max_laws must be a positive integer (got {raw_max!r})") from None
        if max_laws < 1:
            raise _fail(f"max_laws must be a positive integer (got {raw_max!r})")

    # Repeatable discovery (user ruling 2026-08-31): refresh=<timestamp>
    # re-opens the already-done list tasks (ledger reopen rule, section 6.5)
    # so a later run discovers new laws and new amendments — while done
    # body/reason tasks stay skipped, i.e. nothing stored is re-fetched.
    refresh = str(params.get("refresh", "")).strip()
    if refresh:
        parsed_refresh = _iso_timestamp(refresh)
        if parsed_refresh is None:
            raise _fail("refresh must be an ISO timestamp, e.g. 2026-08-31T12:00")

    if pages == "all":
        seeds = [TaskSeed(type="kor_list", params={"pg": 1, "walk": 1}, signal=refresh or None)]
    else:
        seeds = [
            TaskSeed(type="kor_list", params={"pg": pg}, signal=refresh or None)
            for pg in pages
        ]
    if max_laws is not None:
        seeds = [
            TaskSeed(
                type=seed.type,
                params={**seed.params, "max_laws": max_laws},
                signal=seed.signal,
            )
            for seed in seeds
        ]
    return seeds


def _iso_timestamp(raw: str) -> str | None:
    import re as _re

    return raw if _re.fullmatch(r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?)?", raw) else None


#: The law entity (user ruling 2026-08-31): one row per law; every version
#: and reason document hangs off it via ``entity_ref = laws:{ls_id}``. This
#: replaces the plan's original zero-table claim — Korea's versioned corpus
#: has a real entity the lifecycle hangs on (the German flat analogy does
#: not carry over).
DOMAIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS laws (
    ls_id TEXT PRIMARY KEY,
    law_name TEXT NOT NULL,
    abbreviation TEXT,
    ministry TEXT,
    ministry_dept TEXT,
    doc_type TEXT,
    promulgation_type TEXT,
    current_seq TEXT NOT NULL,
    current_ef_yd TEXT NOT NULL
);
"""


def build_source() -> SourceDefinition:
    from adapters.kor.sources.lawgokr.body import KorBodyHandler
    from adapters.kor.sources.lawgokr.list import KorListHandler
    from adapters.kor.sources.lawgokr.reason import KorReasonHandler
    from adapters.kor.sources.lawgokr.versions import KorVersionsHandler

    return SourceDefinition(
        name="lawgokr",
        start_tasks=start_tasks,
        task_types={
            "kor_list": KorListHandler(),
            "kor_body": KorBodyHandler(),
            "kor_versions": KorVersionsHandler(),
            "kor_reason": KorReasonHandler(),
        },
        domain_schema=DOMAIN_SCHEMA,
        domain_tables=("laws",),
        domain_keys={"laws": ("ls_id",)},
    )
