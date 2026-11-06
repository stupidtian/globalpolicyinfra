"""Shared record→document conversion for the gazette task types.

Both ``gazette_day`` (small days, all records in the day response) and
``gazette_slice`` (busy days, one type-name slice) parse DigitalNZ
records with the same rules. Probed shapes the conversion relies on
(2026-10-11/12, verbatim samples in the task folder):

- The notice number appears twice — ``dc_identifier`` as
  ``["Notice Number: 2026-sl5906"]`` and as the last segment of
  ``landing_url``. Both probed channels agree; disagreement is an
  unexplained shape. The canonical source_url is derived from the
  number itself.
- ``date`` is a single-element list whose day equals the queried
  partition date on every probed record. A record with an empty
  ``date`` list still registers (publication date falls back to the
  partition date, raw emptiness kept in meta); a record dated a
  *different* day under this day's filter is an unexplained shape and
  dies loudly.
- ``fulltext`` carries the notice text (all probed 2026-day records had
  it); a record without it still registers with ``fulltext_chars=0`` —
  the PDF pathway is intentionally out of scope (robots-disallowed on
  the gazette site).
"""

from __future__ import annotations

import json
from typing import Any

from adapters.base import FileOut
from adapters.nzl.sources.gazette import (
    COLLECTION,
    NOTICE_TYPE_NAMES,
    parse_notice_number,
)
from core.document import DocumentRecord, compute_doc_id

__all__ = ["records_to_documents"]

_SITE_BASE = "https://gazette.govt.nz/notice/id/"


def _notice_number_of(record: dict[str, Any]) -> str:
    """The gazette notice number, cross-checked between its two channels."""
    from_identifier = ""
    identifiers = record.get("dc_identifier")
    if isinstance(identifiers, list):
        for raw in identifiers:
            text = str(raw).strip()
            if text.lower().startswith("notice number:"):
                from_identifier = text.split(":", 1)[1].strip()
                break
    from_landing = ""
    landing = str(record.get("landing_url") or "").strip()
    if landing:
        from_landing = landing.rstrip("/").rsplit("/", 1)[-1]

    if from_identifier and from_landing and from_identifier != from_landing:
        raise ValueError(
            f"gazette record {record.get('id')!r}: notice number disagreement — "
            f"dc_identifier says {from_identifier!r}, landing_url says {from_landing!r}"
        )
    number = from_identifier or from_landing
    if not number:
        raise ValueError(
            f"gazette record {record.get('id')!r}: neither dc_identifier nor "
            "landing_url yields a notice number"
        )
    if parse_notice_number(number) is None:
        raise ValueError(
            f"gazette record {record.get('id')!r}: notice number {number!r} does not "
            "match the YYYY-<type><serial> shape"
        )
    return number


def _publication_date(record: dict[str, Any], partition_date: str) -> tuple[str, bool]:
    """ISO publication date; True when the partition date was the fallback."""
    raw_dates = record.get("date")
    if isinstance(raw_dates, list) and raw_dates:
        iso = str(raw_dates[0])[:10]
        if iso != partition_date:
            raise ValueError(
                f"gazette record {record.get('id')!r}: dated {iso} but arrived under "
                f"the {partition_date} day filter — unexplained shape"
            )
        return iso, False
    return partition_date, True


def _joined(value: Any, *, drop: set[str] | None = None) -> str:
    if not isinstance(value, list):
        text = str(value).strip()
        return "" if (drop and text in drop) else text
    parts = [str(item).strip() for item in value if str(item).strip()]
    return ";".join(parts)


def records_to_documents(
    records: list[Any], day: str
) -> tuple[list[DocumentRecord], list[FileOut]]:
    """Convert one complete batch of day records into documents + files.

    A record that belongs to two type collections can arrive from two
    slices of the same day; the doc_id-keyed ledger upsert and the
    deterministic per-notice file make that harmless, so duplicates are
    folded here rather than treated as an error (unlike duplicates
    *within* one response, which stay loud).
    """
    documents: list[DocumentRecord] = []
    files: list[FileOut] = []
    seen_numbers: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError(  # noqa: TRY004 — an unexplained shape, not a caller bug
                f"gazette {day}: a result entry is {type(record).__name__}, not an object"
            )
        number = _notice_number_of(record)
        if number in seen_numbers:
            raise ValueError(f"gazette {day}: notice {number} appears twice in one response")
        seen_numbers.add(number)

        landing = str(record.get("landing_url") or "").strip().rstrip("/")
        if landing and landing != f"{_SITE_BASE}{number}":
            raise ValueError(
                f"gazette {day}: notice {number} landing_url {landing!r} is "
                f"not the canonical {_SITE_BASE}{number}"
            )

        pub_date, date_from_partition = _publication_date(record, day)
        parsed = parse_notice_number(number)
        assert parsed is not None  # _notice_number_of validated the shape
        _, type_code, _ = parsed
        type_name = NOTICE_TYPE_NAMES.get(type_code, "")
        if not type_name:
            titles = record.get("collection_title")
            if isinstance(titles, list) and titles:
                first = str(titles[0]).strip()
                if first and first != COLLECTION:
                    type_name = first

        fulltext = record.get("fulltext")
        meta: dict[str, str] = {
            "notice_number": number,
            "digitalnz_id": str(record.get("id", "")),
            "notice_type_code": type_code,
            "fulltext_chars": str(len(fulltext) if isinstance(fulltext, str) else 0),
        }
        if type_name:
            meta["notice_type_name"] = type_name
        if date_from_partition:
            meta["publication_date_source"] = "partition_date"
        subject = _joined(record.get("subject"))
        if subject:
            meta["subject"] = subject
        for key in ("replaces", "is_replaced_by"):
            joined = _joined(record.get(key), drop={"Unknown"})
            if joined:
                meta[key] = joined

        path = f"01_raw/gazette/{day[:4]}/{day[5:7]}/{number}.json"
        meta["files"] = f"{number}.json"
        # Lossless per-notice record: the whole DigitalNZ entry,
        # re-serialized deterministically (sorted keys, fixed indent).
        content = (json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")

        source_url = f"{_SITE_BASE}{number}"
        documents.append(
            DocumentRecord(
                title=str(record.get("title") or "").strip() or number,
                source_url=source_url,
                publication_date=pub_date,
                issuing_authority=_joined(record.get("publisher")) or None,
                doc_type="SECONDARY_LEGISLATION" if type_code == "sl" else "OTHER",
                language=None,  # source marks no language on probed records
                raw_metadata=meta,
            )
        )
        files.append(
            FileOut(path=path, content=content, doc_id=compute_doc_id("NZL", source_url, pub_date))
        )
    return documents, files
