"""Task type ``bgbl_file``: one gazette entry's XML full text.

GET the entry's XML file on the document host — the URL comes verbatim
from the window search response (no URL guessing). The window task has
already registered the document row (metadata lives in the search
response, not in the file: the entry XML's ``<metadaten/>`` block is
empty); this task attaches the primary file to it by doc_id. The bytes
are stored exactly as served.

The response must be a gazette full-text XML document (probed
2026-09-13/14): root ``risdok`` — or ``erechtdok``, the same layout
produced by the source's e-recht converter for a handful of entries
(first seen in production 2026-09-14: BGBLA_2018_II_314) — both in the
``http://www.bka.gv.at`` namespace. Anything else — an HTML protection
page, a truncated transfer — is an unexplained shape and fails loud; the
document id is deterministic from the source URL and publication date,
so a re-run after repair lands on the same identity.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from adapters.aut.sources.ris import FILE_BASE
from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from core.document import compute_doc_id

__all__ = ["BgblFileHandler"]

#: Gazette full-text roots, in the bka namespace (risdok = standard
#: converter; erechtdok = e-recht converter, same inner layout).
_FULLTEXT_ROOTS = ("risdok", "erechtdok")


def file_path(native_id: str, pub: str) -> str:
    """Ledger-visible path relative to the country root."""
    return f"01_raw/ris/{pub[:4]}/{native_id}/{native_id}.xml"


class BgblFileHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=str(task.params["url"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        url = str(task.params["url"])
        native_id = str(task.params["id"])
        pub = str(task.params["pub"])

        if not url.startswith(f"{FILE_BASE}/") or not url.endswith(".xml"):
            raise ValueError(f"file {native_id}: url {url!r} is not a document-host XML path")

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise ValueError(
                f"file {native_id}: body is not XML ({len(response.content)} bytes): {exc}"
            ) from exc
        if not any(root.tag.endswith(name) for name in _FULLTEXT_ROOTS):
            raise ValueError(f"file {native_id}: unexpected root element {root.tag!r}")

        expected_url = f"{FILE_BASE}/{task.params['applikation']}/{native_id}/{native_id}.xml"
        if url != expected_url:
            raise ValueError(f"file {native_id}: url {url!r} does not match the "
                             f"canonical form {expected_url!r}")

        return TaskResult(
            files=[
                FileOut(
                    path=file_path(native_id, pub),
                    content=response.content,
                    doc_id=compute_doc_id("AUT", url, pub),
                )
            ],
        )
