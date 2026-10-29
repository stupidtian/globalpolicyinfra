"""Task types ``cze_fetch`` / ``cze_file``: the informative text package.

e-Sbírka serves every download through an asynchronous ticket service
(the portal's own two-step, probed 2026-10-15):

1. ``cze_fetch``  GET /sbr-externi/stahni/informativni-zneni/{dokumentId}/ZIP
   → a JSON ticket {"pozadavekId", "id", "stavPozadavku", "nazevDokumentu"}.
   Cached artefacts answer ``stavPozadavku: OK`` immediately; anything
   else means the job is still processing — a transient retry, the
   framework's backoff does the waiting (PROBIHA is routine for a
   package's first generation). The package NAME is the version sentinel:
   undated stem (``Sb_2016_222_IZ.zip``) = the as-declared original —
   every era; a dated stem means the id stopped resolving to the original
   (current-version packages carry the version date) — a loud shape
   change. A ticket without a usable ``id`` is a shape change too.

2. ``cze_file``   GET /souborove-sluzby/soubory/{id}
   → the ZIP bytes: ``{stem}/{stem}_IZ.pdf|.xml|.json|.docx`` (plus
   ``Prilohy/`` attachments where the act has any). Parse extracts the
   single ``*_IZ.xml`` member — the complete fragment tree (fragmentId /
   depth / type / xhtml body, ordered) plus metadata and the hierarchy
   template code — and stores it as the document's main file. The XML
   member is extracted in-memory with the stdlib (pure computation on
   response bytes, the same pattern as the EPUB reader); exactly one
   matching member is required — none or several is a shape change.

The binding-text channel (PDF-only) and the print-era scans are
deliberately not captured (user ruling 2026-10-15: no PDF) — the XML
carries the same fragment text the binding PDF is typeset from. The
FileOut carries the doc_id — recomputed from the very same (staleUrl,
publication date) the cze_doc task used, which its cross-checks guarantee
— so the ledger attaches the main file to the record the doc task already
inserted. The source-native package name (``nazevDokumentu``, e.g.
``Sb_2026_1_IZ.zip`` for the as-declared original — undated stem — or
``…_2026-01-11_IZ.zip`` for a dated version) rides in the fetch/file task
params: the tasks table keeps it durably.
"""

from __future__ import annotations

import io
import re
import zipfile

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.cze.sources.esbirka import (
    API_BASE,
    body_path,
    canonical_url,
    file_url,
    guard_block_page,
    guard_waf,
)
from core.document import compute_doc_id
from runtime.errors import TransientError

__all__ = ["CzeFetchHandler", "CzeFileHandler"]

#: kanal param → the ticket endpoint's path (probed forms).
_TICKET_PATH = {
    "informativni": "/stahni/informativni-zneni/{did}/ZIP",
}

#: A version date inside the package name (e.g. ``…_2026-01-11_IZ.zip``)
#: marks a dated version's rendering — the alias id must never name one.
_STEM_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class CzeFetchHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        kanal = str(task.params["kanal"])
        if kanal not in _TICKET_PATH:
            raise ValueError(f"unknown download channel {kanal!r}")
        path = _TICKET_PATH[kanal].format(did=int(task.params["did"]))
        return RequestSpec(url=f"{API_BASE}{path}", headers={"Accept": "application/json"})

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = dict(task.params)
        stale = str(params["stale"])
        guard_waf(response.status_code, f"ticket of {stale}")
        if response.status_code != 200:
            raise ValueError(
                f"ticket of {stale} ({params['kanal']}/{params['did']}) returned "
                f"HTTP {response.status_code}"
            )
        guard_block_page(response.content, f"ticket of {stale}")
        ticket = response.json()
        if not isinstance(ticket, dict):
            raise ValueError(f"ticket of {stale} did not return a JSON object")  # noqa: TRY004
        state = ticket.get("stavPozadavku")
        if state != "OK":
            # The artefact is still being prepared server-side — retrying
            # the ticket later is the portal's own waiting model.
            raise TransientError(
                f"ticket of {stale} is {state!r} (pozadavekId "
                f"{ticket.get('pozadavekId')!r}) — not ready yet"
            )
        file_id = ticket.get("id")
        if not isinstance(file_id, str) or not file_id.strip():
            raise ValueError(f"ticket of {stale} carries no usable file id: {ticket!r}")
        name = ticket.get("nazevDokumentu")
        # Undated stem = the as-declared original (probed every era); a
        # dated stem = the alias id resolved to a dated version's package —
        # wrong version for the event layer, loud.
        if isinstance(name, str) and name.strip() and _STEM_DATE_RE.search(name):
            raise ValueError(
                f"package of {stale} is {name!r} — a dated version's "
                "rendering, not the as-declared original"
            )
        spawn = {**params, "fid": file_id.strip()}
        if isinstance(name, str) and name.strip():
            spawn["nazev"] = name.strip()
        return TaskResult(next_tasks=[TaskSeed(type="cze_file", params=spawn)])


class CzeFileHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=file_url(str(task.params["fid"])))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = dict(task.params)
        stale = str(params["stale"])
        guard_waf(response.status_code, f"file of {stale}")
        if response.status_code != 200:
            raise TransientError(
                f"file of {stale} ({params['fid']}) returned HTTP "
                f"{response.status_code} — freshly created artefacts need a moment"
            )
        guard_block_page(response.content, f"file of {stale}")
        if not response.content.startswith(b"PK"):
            raise ValueError(f"package of {stale} does not start with PK (not a ZIP)")
        try:
            archive = zipfile.ZipFile(io.BytesIO(response.content))
        except zipfile.BadZipFile as exc:
            raise ValueError(f"package of {stale} is not a readable ZIP: {exc}") from exc
        members = [n for n in archive.namelist() if n.endswith("_IZ.xml")]
        if len(members) != 1:
            raise ValueError(
                f"package of {stale} holds {len(members)} _IZ.xml members "
                f"({members[:3]}…) — exactly one expected"
            )
        xml = archive.read(members[0])
        if not xml.lstrip().startswith(b"<?xml"):
            raise ValueError(f"XML member of {stale} does not start with an XML declaration")
        doc_id = compute_doc_id("CZE", canonical_url(stale), str(params["datum"]))
        return TaskResult(
            files=[FileOut(path=body_path(stale), content=xml, doc_id=doc_id)]
        )
