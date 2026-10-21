"""Task types ``uqn_issue`` and ``uqn_issue_part``: the gazette issue PDFs.

``uqn_issue`` GETs the digital-issue page for one calendar date and
extracts the issue PDF part links. One probed behaviour shapes it
(2026-10-10, double-checked on two dateless days): for a date without an
issue the page answers HTTP 200 with the *latest* issue — a silent
fallback, not a 404. The guard is the date embedded in the PDF filename
(``ummalqura_pdf-20261002-1.pdf`` → 2026-10-02): a mismatch is a
legitimate no-issue day (expected_empty), anything else moves on.

``uqn_issue_part`` downloads one part (one request, one PDF, one
document — an issue may ship as several PDF files, and part numbering
does not necessarily start at 1: the 2026-10-09 issue lists only part 2).
The canonical source URL drops the ``ts`` parameter — probed 2026-10-10:
absent and altered ts both answer 200, so it is a cache buster, not a
signature, and one-time values must not enter doc_id.
"""

from __future__ import annotations

import re

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.sau.sources.uqn import SITE
from core.document import DocumentRecord, compute_doc_id

__all__ = ["UqnIssueHandler", "UqnIssuePartHandler"]

_PDF_LINK = re.compile(
    r"cdn/\?url=(uploads/pdf/\d{4}/\d{2}/\d{2}/ummalqura_pdf-(\d{8})-(\d+)\.pdf)"
)


class UqnIssueHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=f"{SITE}/digital?date={task.params['date']}")

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        date_iso = str(task.params["date"])
        try:
            text = response.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"issue {date_iso}: page is not UTF-8: {exc}") from exc

        parts: dict[int, str] = {}
        for match in _PDF_LINK.finditer(text):
            parts[int(match.group(3))] = match.group(1)
        if not parts:
            raise ValueError(
                f"issue {date_iso}: digital page carries no issue PDF links — "
                "unexpected page shape"
            )

        linked_dates = {m.group(2) for m in _PDF_LINK.finditer(text)}
        requested = date_iso.replace("-", "")
        if linked_dates != {requested}:
            return TaskResult(
                expected_empty=(
                    f"no Umm al-Qura issue on {date_iso} (the digital page fell back to "
                    f"issue dated {', '.join(sorted(linked_dates))})"
                )
            )
        return TaskResult(
            next_tasks=[
                TaskSeed(type="uqn_issue_part", params={"date": date_iso, "part": str(part)})
                for part in sorted(parts)
            ]
        )


class UqnIssuePartHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        y, m, d = str(task.params["date"]).split("-")
        part = int(str(task.params["part"]))
        return RequestSpec(
            url=f"{SITE}/cdn/?url=uploads/pdf/{y}/{m}/{d}/ummalqura_pdf-{y}{m}{d}-{part}.pdf"
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        date_iso = str(task.params["date"])
        part = int(str(task.params["part"]))
        if not response.content.startswith(b"%PDF"):
            raise ValueError(
                f"issue part {date_iso}-{part}: body is not a PDF (magic missing)"
            )

        y, m, d = date_iso.split("-")
        date_compact = date_iso.replace("-", "")
        file_name = f"ummalqura_pdf-{date_compact}-{part}.pdf"
        # Canonical form = the cdn route + the uploads path, ts dropped.
        source_url = f"{SITE}/cdn/?url=uploads/pdf/{y}/{m}/{d}/{file_name}"
        path = f"01_raw/uqn/{y}/D{date_compact}/issue/{file_name}"

        document = DocumentRecord(
            title=f"جريدة أم القرى — نسخة {date_iso}، الجزء {part}",
            source_url=source_url,
            publication_date=date_iso,
            doc_type="OTHER",
            language="ara",
            raw_metadata={"kind": "issue_part", "issue_date": date_iso, "part": str(part)},
        )
        doc_id = compute_doc_id("SAU", source_url, date_iso)

        return TaskResult(
            documents=[document],
            files=[FileOut(path=path, content=response.content, doc_id=doc_id)],
        )
