"""Standard on-disk layout contract for GlobalPolicyInfra.

This module is the **sole path authority** of the package (ARCHITECTURE.md,
decision record 2026-08-19). All other modules must obtain paths through the
functions below; hand-rolled path concatenation elsewhere is forbidden.

The layout follows the numbered-stage structure proven by the legacy
``path_resolver`` of ``global_policies``::

    {data_root}/{ISO3}_policy/
    ├── 01_raw/                        # country-pack territory: one folder per
    │                                   # policy (a bill, a decree); internal
    │                                   # structure declared by the pack (§6.7)
    ├── 02_cleaned/                     # document-pipeline territory; subdirs
    │                                   # created on demand by the stages
    ├── 03_extracted/                   # (same)
    ├── failures/                       # incident archive (raw responses, meta)
    ├── 00_metadata/                    # created on demand (export /
    │                                   # events-archive write here)
    └── state.db                        # per-country SQLite operational state

``ensure_layout`` pre-creates only the framework-owned skeleton (01_raw
itself, 02_cleaned, 03_extracted, failures) — 01_raw's top level belongs to
source names, and nothing is pre-created inside the country pack's or the
pipeline stages' territory (framework-hardening 1.4, 2026-09-02).

Notes:
- Reports live with the data (``02_cleaned/reports/``), not in git. This is a
  provisional decision; the exploration workflow discussion (Part 3) may
  revisit it.
- Operational state moved from manifest JSON files to SQLite (decision record
  2026-08-19), so no manifest paths are defined here.
- The ``raw_dir``/``listings_dir`` helpers below are legacy path formulas
  from the pre-2026-08-24 layout; they no longer correspond to directories
  the framework creates.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "CLEANED_SUBDIRS",
    "EXTRACTED_SUBDIRS",
    "RAW_FORMATS",
    "chunk_dir",
    "cleaned_dir",
    "country_dir",
    "ensure_layout",
    "extracted_dir",
    "index_path",
    "listings_dir",
    "metadata_dir",
    "raw_dir",
    "state_db_path",
]

COUNTRY_DIR_SUFFIX = "_policy"

STAGE_DIRS = ("00_metadata", "01_raw", "02_cleaned", "03_extracted")

#: Formats accepted under ``01_raw/``.
RAW_FORMATS = ("html", "pdf", "xml")

#: Subdirectories of ``02_cleaned/`` (includes co-opted intermediates).
CLEANED_SUBDIRS = ("normalized_txt", "body_only", "chunked", "classification", "reports")

#: Subdirectories of ``03_extracted/``.
EXTRACTED_SUBDIRS = ("super_json", "goal_json", "merged")

INDEX_FILE_NAME = "policy_index.parquet"
STATE_DB_FILE_NAME = "state.db"


def _check_choice(value: str, choices: tuple[str, ...], what: str) -> str:
    if value not in choices:
        raise ValueError(f"Unknown {what} {value!r}; expected one of {sorted(choices)}.")
    return value


def country_dir(data_root: str | Path, country_code: str) -> Path:
    """Top-level directory for one country: ``{data_root}/{ISO3}_policy``."""
    return Path(data_root) / f"{country_code}{COUNTRY_DIR_SUFFIX}"


def metadata_dir(data_root: str | Path, country_code: str) -> Path:
    """``00_metadata/`` — metadata indexes."""
    return country_dir(data_root, country_code) / "00_metadata"


def index_path(data_root: str | Path, country_code: str) -> Path:
    """Path of the parquet policy-index snapshot (``00_metadata/policy_index.parquet``)."""
    return metadata_dir(data_root, country_code) / INDEX_FILE_NAME


def raw_dir(data_root: str | Path, country_code: str, fmt: str) -> Path:
    """``01_raw/{fmt}/`` for ``fmt`` in :data:`RAW_FORMATS`."""
    _check_choice(fmt, RAW_FORMATS, "raw format")
    return country_dir(data_root, country_code) / "01_raw" / fmt


def listings_dir(data_root: str | Path, country_code: str) -> Path:
    """``01_raw/listings/`` — listing pages (not document originals)."""
    return country_dir(data_root, country_code) / "01_raw" / "listings"


def cleaned_dir(data_root: str | Path, country_code: str, subdir: str) -> Path:
    """``02_cleaned/{subdir}/`` for ``subdir`` in :data:`CLEANED_SUBDIRS`."""
    _check_choice(subdir, CLEANED_SUBDIRS, "cleaned subdir")
    return country_dir(data_root, country_code) / "02_cleaned" / subdir


def chunk_dir(data_root: str | Path, country_code: str, doc_id: str) -> Path:
    """``02_cleaned/chunked/{doc_id}/`` — chunks of one document."""
    return cleaned_dir(data_root, country_code, "chunked") / doc_id


def extracted_dir(data_root: str | Path, country_code: str, subdir: str) -> Path:
    """``03_extracted/{subdir}/`` for ``subdir`` in :data:`EXTRACTED_SUBDIRS`."""
    _check_choice(subdir, EXTRACTED_SUBDIRS, "extracted subdir")
    return country_dir(data_root, country_code) / "03_extracted" / subdir


def state_db_path(data_root: str | Path, country_code: str) -> Path:
    """``{ISO3}_policy/state.db`` — per-country SQLite operational state."""
    return country_dir(data_root, country_code) / STATE_DB_FILE_NAME


def ensure_layout(data_root: str | Path, country_code: str) -> None:
    """Create the framework-owned directory skeleton for one country
    (idempotent): the country root plus exactly ``01_raw/``,
    ``02_cleaned/``, ``03_extracted/`` and ``failures/`` — nothing else.
    ``01_raw``'s top level belongs to source names (section 6.7), pipeline
    subdirs are created on demand by their stages, ``00_metadata`` is
    created by its writers, and ``state.db`` by the store
    (framework-hardening 1.4, ruling 2026-09-02)."""
    root = country_dir(data_root, country_code)
    for name in ("01_raw", "02_cleaned", "03_extracted", "failures"):
        (root / name).mkdir(parents=True, exist_ok=True)
