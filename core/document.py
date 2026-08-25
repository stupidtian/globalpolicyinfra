"""Document abstraction for GlobalPolicyInfra.

Field list per ARCHITECTURE.md section 5.1 (task-model revision, 2026-08-24):
fixed columns carry only cross-country-common fields; country-specific
extras go to ``raw_metadata``. ``entity_ref`` links a document to its domain
entity (``{table}:{pk}``, e.g. ``bills:USA_119_HR_204``; NULL for flat
countries) and ``produced_by`` records the task that produced it.

``doc_id`` follows the frozen rule ``{ISO3}_{YYYYMMDD}_{sha256(source_url)[:8]}``
(decision record 2026-08-20); the date part is the publication date, or
``00000000`` when unknown. The id is **framework-generated** — country
parsers produce :class:`DocumentRecord` without it.
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field

__all__ = ["Document", "DocumentRecord", "compute_doc_id"]


def compute_doc_id(country_code: str, source_url: str, publication_date: str | None) -> str:
    """The one place where doc_id is computed (idempotency contract)."""
    date_part = publication_date.replace("-", "")[:8] if publication_date else "00000000"
    digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:8]
    return f"{country_code.upper()}_{date_part}_{digest}"


class DocumentRecord(BaseModel):
    """What a country's parse function reports for one document.

    Bibliographic fields only: no ``doc_id``, no file fields — identity
    belongs to the framework, files to the download task.
    """

    model_config = {"frozen": True}

    title: str
    source_url: str
    publication_date: str | None = None
    issuing_authority: str | None = None
    doc_type: str | None = None
    entity_ref: str | None = None
    language: str | None = None
    raw_metadata: dict[str, str] = Field(default_factory=dict)


class Document(BaseModel):
    """A single policy document (full section 5.1 field set)."""

    model_config = {"frozen": True}

    doc_id: str
    country_code: str
    title: str
    source_url: str
    publication_date: str | None = None
    issuing_authority: str | None = None
    doc_type: str | None = None
    entity_ref: str | None = Field(
        default=None,
        description="Domain-entity backlink, '{table}:{pk}' (e.g. bills:USA_119_HR_204)",
    )
    produced_by: str | None = Field(default=None, description="Task id that produced this")
    raw_format: str | None = None
    local_path: str | None = None
    file_hash: str | None = None
    content_length: int | None = None
    language: str | None = None
    collection_date: str | None = None
    raw_metadata: dict[str, str] = Field(default_factory=dict)
