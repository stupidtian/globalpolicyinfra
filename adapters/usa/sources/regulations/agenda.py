"""Task type ``ua_edition``: one edition of the Unified Agenda.

GET reginfo.gov/public/do/XMLViewFileAction?f=REGINFO_RIN_DATA_{edition}.xml
— one XML file per agenda edition (spring ``04`` / fall ``10``; the fall
edition additionally carries the Regulatory Plan entries). Parse yields:

- ``rulemakings`` rows — the latest known state of every RIN the edition
  mentions (merged across editions; the *history* lives in ua_entries);
- ``ua_entries`` rows — the RIN × edition snapshot (stage evolution);
- ``source_snapshots`` row + the raw XML kept under 01_raw/regulations/.

Edition ids are the files' internal PUBLICATION_ID (YYYYMM). Two filenames
deviate from the pattern and are mapped explicitly below.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.usa.schema import yn_flag

__all__ = ["KNOWN_EDITIONS", "UaEditionHandler", "edition_file"]

#: Bytes forbidden by XML 1.0 (control chars outside tab/LF/CR). The 2004
# editions ship a handful of these at the source (e.g. an apostrophe mangled
#: to 0x19 inside an abstract), making the raw file not well-formed. We strip
#: them for parsing only — the archived file keeps the bytes verbatim.
_XML_FORBIDDEN = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")

#: All 60 machine-readable editions, verified 2026-08-26 (reginfo.gov
#: eAgendaXmlReport listing). Refresh when a new edition appears (twice a
#: year) — an unknown edition id is rejected at seed time.
KNOWN_EDITIONS: tuple[str, ...] = (
    "202510", "202504", "202410", "202404", "202310", "202304",
    "202210", "202204", "202110", "202104", "202010", "202004",
    "201910", "201904", "201810", "201804", "201710", "201704",
    "201610", "201604", "201510", "201504", "201410", "201404",
    "201310", "201304", "201210", "201110", "201104", "201010",
    "201004", "200910", "200904", "200810", "200804", "200710",
    "200704", "200610", "200604", "200510", "200504", "200410",
    "200404", "200310", "200304", "200210", "200204", "200110",
    "200104", "200010", "200004", "199910", "199904", "199810",
    "199804", "199710", "199704", "199610", "199604", "199510",
)

_IRREGULAR_FILES: dict[str, str] = {
    # spring 2012 was never published; these two break the naming pattern
    "201804": "2018-SPRING-RIN-DATA.xml",
    "201210": "REGINFO_RIN_DATA_2012.xml",
}

_API_URL = "https://www.reginfo.gov/public/do/XMLViewFileAction"


def edition_file(edition: str) -> str:
    return _IRREGULAR_FILES.get(edition, f"REGINFO_RIN_DATA_{edition}.xml")


def _agencies(entry: ET.Element) -> list[dict[str, str]]:
    """Direct-child AGENCY elements only (each CONTACT embeds another one)."""
    rows = []
    for el in entry.findall("AGENCY"):
        rows.append(
            {
                "code": (el.findtext("CODE") or "").strip(),
                "name": (el.findtext("NAME") or "").strip(),
                "acronym": (el.findtext("ACRONYM") or "").strip(),
            }
        )
    return rows


def _timetable(entry: ET.Element) -> list[dict[str, str]]:
    return [
        {
            "action": (t.findtext("TTBL_ACTION") or "").strip(),
            "date": (t.findtext("TTBL_DATE") or "").strip(),
        }
        for t in entry.findall("./TIMETABLE_LIST/TIMETABLE")
    ]


class UaEditionHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        edition = str(task.params["edition"])
        return RequestSpec(url=_API_URL, params={"f": edition_file(edition)})

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        edition = str(task.params["edition"])
        root = ET.fromstring(_XML_FORBIDDEN.sub(b"", response.content))
        run_date = (root.get("RUN_DATE") or "")[:10] or None

        rulemakings: list[dict[str, Any]] = []
        ua_entries: list[dict[str, Any]] = []
        for entry in root.findall("RIN_INFO"):
            rin = (entry.findtext("RIN") or "").strip()
            if not rin:
                continue
            agencies = _agencies(entry)
            parent = entry.find("PARENT_AGENCY")
            timetable = _timetable(entry)
            title = (entry.findtext("RULE_TITLE") or "").strip()
            common = {
                "rin": rin,
                "title": title,
                "priority_category": (entry.findtext("PRIORITY_CATEGORY") or "").strip(),
                "rin_status": (entry.findtext("RIN_STATUS") or "").strip(),
                "timetable": timetable,
            }
            lead = agencies[0] if agencies else {}
            rulemakings.append(
                {
                    **common,
                    "lead_agency_code": lead.get("code") or None,
                    "lead_agency_name": lead.get("name") or None,
                    "parent_agency_name": (parent.findtext("NAME") or "").strip()
                    if parent is not None
                    else None,
                    "agencies": agencies,
                    "current_stage": (entry.findtext("RULE_STAGE") or "").strip(),
                    "is_plan_entry": yn_flag(entry.findtext("RPLAN_ENTRY")),
                    "major": yn_flag(entry.findtext("MAJOR")),
                    "abstract": (entry.findtext("ABSTRACT") or "").strip() or None,
                    "cfr": [c.text.strip() for c in entry.findall("./CFR_LIST/CFR") if c.text],
                    "legal_authority": [
                        a.text.strip()
                        for a in entry.findall("./LEGAL_AUTHORITY_LIST/LEGAL_AUTHORITY")
                        if a.text
                    ],
                }
            )
            ua_entries.append(
                {
                    **common,
                    "edition_id": edition,
                    "rule_stage": (entry.findtext("RULE_STAGE") or "").strip(),
                    "rplan_entry": yn_flag(entry.findtext("RPLAN_ENTRY")),
                }
            )

        snapshot = {
            "source": "agenda",
            "edition": edition,
            "file_path": f"01_raw/regulations/agenda/{edition}.xml",
            "n_records": len(rulemakings),
            "run_date": run_date,
        }
        return TaskResult(
            upsert_rows={
                "rulemakings": rulemakings,
                "ua_entries": ua_entries,
                "source_snapshots": [snapshot],
            },
            files=[
                FileOut(
                    path=f"01_raw/regulations/agenda/{edition}.xml",
                    content=response.content,
                )
            ],
        )
