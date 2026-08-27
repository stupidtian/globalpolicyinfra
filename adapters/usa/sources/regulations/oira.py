"""Task type ``oira_file``: one OIRA review file (EO 12866 line).

GET reginfo.gov/public/do/XMLViewFileAction?f=EO_RULE_COMPLETED_{year}.xml —
one file per completed calendar year (1981→), plus rolling files updated
daily (rules currently under review, completions year-to-date / last 30
days). Each REGACT is one White House review of one draft: RIN, stage,
dates received/completed, decision.

Rolling files keep changing, so their seeds carry the spawn date as the
reopen signal (§6.5): re-running ``oira=…`` re-fetches a rolling file only
when the day is new; completed-year files are immutable and carry no signal.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.usa.schema import yn_flag

__all__ = ["FIRST_YEAR", "ROLLING_FILES", "OiraFileHandler"]

_API_URL = "https://www.reginfo.gov/public/do/XMLViewFileAction"

#: Verified oldest completed-year file (2026-08-26 listing shows 1981→2025).
FIRST_YEAR = 1981

#: rolling (mutable) files beyond the per-year completed ones
ROLLING_FILES: dict[str, str] = {
    "UNDER_REVIEW": "EO_RULES_UNDER_REVIEW.xml",
    "YTD": "EO_RULE_COMPLETED_YTD.xml",
    "LAST30": "EO_RULE_COMPLETED_30_DAYS.xml",
}


def oira_file_name(name: str) -> str:
    if name in ROLLING_FILES:
        return ROLLING_FILES[name]
    return f"EO_RULE_COMPLETED_{name}.xml"


class OiraFileHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        name = str(task.params["name"])
        return RequestSpec(url=_API_URL, params={"f": oira_file_name(name)})

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        name = str(task.params["name"])
        root = ET.fromstring(response.content)
        run_date = (root.get("RUNDATE") or "")[:10] or None

        rows: list[dict[str, Any]] = []
        for regact in root.findall("REGACT"):
            rin = (regact.findtext("RIN") or "").strip()
            stage = (regact.findtext("STAGE") or "").strip()
            received = (regact.findtext("DATE_RECEIVED") or "").strip()
            if not (rin and stage and received):
                continue  # malformed record; framework archive keeps the raw file
            rows.append(
                {
                    "rin": rin,
                    "stage": stage,
                    "date_received": received,
                    "date_completed": (regact.findtext("DATE_COMPLETED") or "").strip()
                    or None,
                    "decision": (regact.findtext("DECISION") or "").strip() or None,
                    "agency_code": (regact.findtext("AGENCY_CODE") or "").strip() or None,
                    "title": (regact.findtext("TITLE") or "").strip() or None,
                    "economically_significant": yn_flag(
                        regact.findtext("ECONOMICALLY_SIGNIFICANT")
                    ),
                    "major": yn_flag(regact.findtext("MAJOR")),
                    "legal_deadline": (regact.findtext("LEGAL_DEADLINE") or "").strip()
                    or None,
                    "source_file": name,
                }
            )

        snapshot = {
            "source": "oira",
            "edition": name,
            "file_path": f"01_raw/regulations/oira/{name}.xml",
            "n_records": len(rows),
            "run_date": run_date,
        }
        return TaskResult(
            upsert_rows={"oira_reviews": rows, "source_snapshots": [snapshot]},
            files=[
                FileOut(
                    path=f"01_raw/regulations/oira/{name}.xml",
                    content=response.content,
                )
            ],
        )
