"""Task type ``kanpo_doc``: one gazette entry, one request, one document.

GET the entry PDF whose address is constructed from the TOC link the seed
carries (``{issue}/pdf/{base}.pdf`` — probed 2026-09-07: the wrapper page
``…f.html`` is a 2.7KB shell whose iframe embeds exactly this PDF, so the
shell is pure UI and never fetched).

Identity (the two Japan-specific twists, see docs/countries/jpn/
kanpo-zh.md §4):

- ``source_url`` is always the **permanent /old/ form**, even when the
  bytes were fetched from the transient root namespace: the same document
  changes namespace at the ~90-day line and byte-identical twins must not
  fork into two doc_ids on a re-crawl (documents upsert is INSERT OR
  IGNORE on the doc_id primary key). The /old/ address does not resolve
  for the first ~90 days after publication — a documented activation lag.
- the ``#e{ordinal}`` fragment disambiguates entries sharing one page PDF
  (2026-09-04 号外 page 2 carries four 政令). Fragments are never sent to
  the server, so the URL stays a working link to the portal's viewer.

A 404 here is *not* declared as data: the entry came from a TOC fetched
moments ago, so not-found means something truly broke and must fail loud.
The response must be a PDF (``%PDF`` magic); anything else is an
unexplained shape.
"""

from __future__ import annotations

import re

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.jpn.sources.kanpo import SITE, USER_AGENT
from adapters.jpn.sources.kanpo.enumerate import map_doc_type
from core.document import DocumentRecord, compute_doc_id

__all__ = ["KanpoDocHandler"]

_TRAILING_PARENS_RE = re.compile(r"（([^（）]*)）\s*$")


def _notice_no(title: str) -> str | None:
    """The trailing numbering paren, e.g. ``（法務四八）``/``（二六九）`` —
    the gazette's own identifier words, kept verbatim (kanji numerals
    included; no interpretation)."""
    match = _TRAILING_PARENS_RE.search(title.strip())
    return match.group(1) if match else None


class KanpoDocHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        params = task.params
        ymd = str(params["date"]).replace("-", "")
        prefix = "" if params.get("ns") == "root" else "/old"
        issue = str(params["issue"])
        base = str(params["base"])
        return RequestSpec(
            url=f"{SITE}{prefix}/{ymd}/{issue}/pdf/{base}.pdf",
            headers={"User-Agent": USER_AGENT},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = task.params
        date = str(params["date"])
        issue = str(params["issue"])
        base = str(params["base"])
        ordinal = int(params["e"])
        title = str(params["title"])
        h2 = str(params.get("h2", ""))

        if not response.content.startswith(b"%PDF"):
            head = response.content[:80]
            raise ValueError(
                f"doc {base}e{ordinal}: response is not a PDF "
                f"(status {response.status_code}, head {head!r})"
            )

        source_url = f"{SITE}/old/{date.replace('-', '')}/{issue}/{base}f.html#e{ordinal}"
        ymd = date.replace("-", "")

        meta: dict[str, str] = {
            "date": date,
            "issue_type": str(params.get("issue_type", "")),
            "issue_code": issue,
            "issue_no": str(params.get("issue_no", "")),
            "native_type": h2,
            "section_h2": h2,
            "page": str(params.get("page", "")),
            "ordinal_in_issue": str(ordinal),
            "ns_fetched": str(params.get("ns", "old")),
        }
        for key in ("h3", "h4"):
            if params.get(key):
                meta[f"section_{key}"] = str(params[key])
        notice = _notice_no(title)
        if notice is not None:
            meta["notice_no"] = notice
        meta["files"] = f"{base}.pdf"

        record = DocumentRecord(
            title=title,
            source_url=source_url,
            publication_date=date,
            issuing_authority=None,
            doc_type=map_doc_type(h2),
            language="jpn",
            raw_metadata=meta,
        )
        doc_id = compute_doc_id("JPN", source_url, date)
        path = f"01_raw/kanpo/{ymd[:4]}/D{ymd}/{issue}/{base}e{ordinal}/{base}.pdf"

        return TaskResult(
            documents=[record],
            files=[FileOut(path=path, content=response.content, doc_id=doc_id)],
        )
