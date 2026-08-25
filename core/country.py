"""Country abstraction for GlobalPolicyInfra.

A ``Country`` is a thin, frozen handle binding an ISO3 code to a data root.
It performs **path computation only**, delegating every layout decision to
:mod:`core.paths` (the sole path authority).

Deliberately deferred to Part 2 (ARCHITECTURE.md section 7): deeper ISO3
validation, non-country entities such as the EU, and the country registry
mechanism. v1 validates the code's format only.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from core import paths

__all__ = ["Country"]


class Country(BaseModel):
    """A policy jurisdiction whose data lives under ``{data_root}/{ISO3}_policy``."""

    model_config = {"frozen": True}

    code: str = Field(
        ...,
        pattern=r"^[A-Z]{3}$",
        description="ISO 3166-1 alpha-3 code, uppercase (format-checked only in v1)",
    )
    data_root: Path = Field(..., description="Root directory for all country data")

    # -- path properties (delegated to core.paths) -------------------------

    @property
    def country_dir(self) -> Path:
        return paths.country_dir(self.data_root, self.code)

    @property
    def metadata_dir(self) -> Path:
        return paths.metadata_dir(self.data_root, self.code)

    @property
    def index_path(self) -> Path:
        return paths.index_path(self.data_root, self.code)

    @property
    def listings_dir(self) -> Path:
        return paths.listings_dir(self.data_root, self.code)

    @property
    def state_db_path(self) -> Path:
        return paths.state_db_path(self.data_root, self.code)

    # -- parameterized paths ------------------------------------------------

    def raw_dir(self, fmt: str) -> Path:
        """``01_raw/{fmt}/``; ``fmt`` must be one of ``paths.RAW_FORMATS``."""
        return paths.raw_dir(self.data_root, self.code, fmt)

    def cleaned_dir(self, subdir: str) -> Path:
        """``02_cleaned/{subdir}/``; ``subdir`` must be in ``paths.CLEANED_SUBDIRS``."""
        return paths.cleaned_dir(self.data_root, self.code, subdir)

    def chunk_dir(self, doc_id: str) -> Path:
        """``02_cleaned/chunked/{doc_id}/``."""
        return paths.chunk_dir(self.data_root, self.code, doc_id)

    def extracted_dir(self, subdir: str) -> Path:
        """``03_extracted/{subdir}/``; ``subdir`` must be in ``paths.EXTRACTED_SUBDIRS``."""
        return paths.extracted_dir(self.data_root, self.code, subdir)

    # -- lifecycle ------------------------------------------------------------

    def ensure_directories(self) -> None:
        """Create the full standard directory tree for this country."""
        paths.ensure_layout(self.data_root, self.code)
