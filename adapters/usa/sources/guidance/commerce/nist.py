"""Task types ``nist_latest`` + ``nist_release_dl``: the NIST Tech Pubs
bibliographic snapshot (see docs/countries/usa/guidance-commerce-zh.md §3).

NIST's own browse pages are incomplete, but the Research Library publishes a
monthly catalogue export on GitHub Releases (repo ``usnistgov/NIST-Tech-Pubs``,
tags like ``July2026``): ``allrecords-MODS.xml``, one ~6KB MODS record per
NIST/NBS Technical Series publication (~13k records, ~84MB). We consume it
snapshot-style — one task per release: download, archive verbatim, parse rows
locally. Task ids embed the tag, so re-running a tag is a no-op and each
monthly tag is a natural increment.

doc_type stays source-native (rule R1): only FIPS maps to STANDARD; every
other series (SP is a mixed reports/guidelines series, IR is research) is
OTHER with the series kept in native_type.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from typing import Any

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.usa.sources.guidance.common import department_of
from runtime.errors import PermanentError

__all__ = [
    "MODS_ASSET_NAME",
    "NIST_RELEASES_API",
    "NistLatestHandler",
    "NistReleaseDownloadHandler",
    "nist_doc_type",
    "nist_native_id",
    "parse_mods_records",
    "release_asset_url",
]

NIST_RELEASES_API = (
    "https://api.github.com/repos/usnistgov/NIST-Tech-Pubs/releases?per_page=1"
)
MODS_ASSET_NAME = "allrecords-MODS.xml"

_MODS_NS = "{http://www.loc.gov/mods/v3}"


def release_asset_url(tag: str) -> str:
    return (
        "https://github.com/usnistgov/NIST-Tech-Pubs/releases/download/"
        f"{tag}/{MODS_ASSET_NAME}"
    )


def nist_doc_type(series_code: str) -> str:
    """R1: only FIPS is a standard by its own name; everything else OTHER."""
    return "STANDARD" if "FIPS" in series_code.upper() else "OTHER"


def nist_native_id(
    doi: str | None,
    series_title: str | None,
    part_number: str | None,
    record_identifier: str | None,
) -> tuple[str, str]:
    """(native_id, series_code) from the citable DOI suffix — mechanical dot
    normalization, no semantics. Fallback chain: series title's first variant
    + part number, then the Alma catalogue id."""
    if doi:
        suffix = doi.strip().split("/", 1)[1].strip() if "/" in doi else doi.strip()
        if suffix:
            native_id = " ".join(suffix.split("."))
            tokens = native_id.split()
            return native_id, " ".join(tokens[:2])
    if series_title and part_number:
        first_variant = series_title.split(";")[0].strip()
        if first_variant:
            return f"{first_variant} {part_number.strip()}", first_variant
    return (f"rec-{(record_identifier or '').strip()}", "")


def _first_text(el: ET.Element, path: str) -> str | None:
    value = el.findtext(path)
    return value.strip() if value else None


def parse_mods_records(content: bytes) -> list[dict[str, Any]]:
    """Yield guidance_documents rows (agency='nist') from a MODS collection.

    iterparse with clear() only at </mods> record boundaries — clearing
    earlier eats the children (the lesson recorded in the regulations doc).
    """
    rows: list[dict[str, Any]] = []
    for event, el in ET.iterparse(io.BytesIO(content), events=("end",)):
        if el.tag != f"{_MODS_NS}mods":
            continue

        title = " ".join(
            part
            for part in (
                (el.findtext(f"{_MODS_NS}titleInfo/{_MODS_NS}nonSort") or "").strip(),
                (el.findtext(f"{_MODS_NS}titleInfo/{_MODS_NS}title") or "").strip(),
            )
            if part
        )
        doi = None
        for identifier in el.findall(f"{_MODS_NS}identifier"):
            if identifier.get("type") == "doi" and identifier.text:
                doi = identifier.text
                break
        series_title = None
        part_number = None
        series = el.find(
            f'{_MODS_NS}relatedItem[@type="series"]/{_MODS_NS}titleInfo'
        )
        if series is not None:
            series_title = series.findtext(f"{_MODS_NS}title")
            part_number = series.findtext(f"{_MODS_NS}partNumber")
        record_id = el.findtext(
            f"{_MODS_NS}recordInfo/{_MODS_NS}recordIdentifier"
        )

        # prefer the precise dateIssued (no @encoding) over the marc year
        issued = None
        for date_el in el.findall(f"{_MODS_NS}originInfo/{_MODS_NS}dateIssued"):
            if date_el.get("encoding"):
                continue
            if date_el.text:
                issued = date_el.text.strip().rstrip(".")
                break
        if issued is None:
            for date_el in el.findall(f"{_MODS_NS}originInfo/{_MODS_NS}dateIssued"):
                if date_el.text:
                    issued = date_el.text.strip().rstrip(".")
                    break

        url = el.findtext(f"{_MODS_NS}location/{_MODS_NS}url")
        product_area = el.findtext(f"{_MODS_NS}subject/{_MODS_NS}topic")

        native_id, series_code = nist_native_id(doi, series_title, part_number, record_id)
        rows.append(
            {
                "agency": "nist",
                "department": department_of("nist"),
                "native_id": native_id,
                "channel": "release",
                "native_type": series_code or None,
                "doc_type": nist_doc_type(series_code),
                "title": title or native_id,
                "issued_date": issued,
                "revised_date": None,
                "product_area": (product_area or "").strip() or None,
                "status": None,
                "url": (url or "").strip() or None,
                "file_url": (url or "").strip() or None,
                "folder": None,
                "page_class": None,
                "text_extracted": None,
            }
        )
        el.clear()
    return rows


class NistLatestHandler:
    """One GitHub API call: discover the newest release tag, spawn the
    download task for it (dedup makes an unchanged tag a no-op)."""

    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=NIST_RELEASES_API)

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        releases = response.json()
        if not isinstance(releases, list) or not releases:
            raise PermanentError("no releases found on usnistgov/NIST-Tech-Pubs")
        tag = str(releases[0].get("tag_name") or "").strip()
        assets = releases[0].get("assets") or []
        if not tag or not any(a.get("name") == MODS_ASSET_NAME for a in assets):
            raise PermanentError(
                f"release {tag or '<untagged>'!r} has no {MODS_ASSET_NAME} asset"
            )
        return TaskResult(
            next_tasks=[
                TaskSeed(type="nist_release_dl", params={"agency": "nist", "tag": tag})
            ]
        )


class NistReleaseDownloadHandler:
    """Download one release's MODS export, archive it verbatim, parse rows
    (single task, the Unified-Agenda snapshot pattern)."""

    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=release_asset_url(str(task.params["tag"])))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        tag = str(task.params["tag"])
        rows = parse_mods_records(response.content)
        # catalog = the bulk bibliographic file, not a per-document artifact
        # (layout spec 2026-09-01: one flat file per release tag)
        archive_path = f"01_raw/guidance/commerce/nist/catalog/{tag}.xml"
        snapshot = {
            "source": "nist-techpubs",
            "edition": tag,
            "file_path": archive_path,
            "n_records": len(rows),
            "run_date": None,
        }
        return TaskResult(
            upsert_rows={"guidance_documents": rows, "source_snapshots": [snapshot]},
            files=[FileOut(path=archive_path, content=response.content)],
        )
