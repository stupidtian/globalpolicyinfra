"""Task type ``frl_doc``: one file via the register's download function.

``documents/find(titleid=…,asat=…,type=…,format=…,uniqueTypeNumber=0,
volumeNumber=…,rectificationVersionNumber=0)`` serves **two
representations, chosen per title by the server** (probed 2026-08-31:
EPBC and Marine Order return a JSON envelope whose ``bytes`` field holds
the file base64-encoded, while 2026 Acts like C2026A00073 stream the raw
bytes with an ``application/epub+zip`` content type — ``Accept`` and
``$format=json`` do not influence the choice). The parser therefore
sniffs the payload: a leading ``{`` takes the envelope path (decoded
sizes matched ``sizeInBytes`` exactly on every envelope probe; EPUBs are
valid ZIPs, PDFs start %PDF), anything else is treated as the raw file.

``asat`` must be a concrete date inside the version's validity window —
the AsMade/Current/Latest enum names the metadata advertises are *not*
accepted by the function (probed 404) — so this source always asks for
the version's own start date, and never "today": a title whose current
window is an uncompiled amendment marker has no file anywhere, and a
today-anchored request would 404 on it (the legacy pipeline's hidden
failure mode).

In the envelope the type/format fields come back as raw numbers, so the
task's params remain the source of truth for kind/format; the envelope
contributes ``fileName`` (register id of the rendered file), the
authorisation flag and the version's registration timestamp when present.
"""

from __future__ import annotations

import base64

from adapters.aus.sources.frl import API_BASE, canonical_source_url, collection_doc_type
from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from core.document import DocumentRecord, compute_doc_id

__all__ = ["FrlDocHandler"]

_MAGIC = {"epub": b"PK", "pdf": b"%PDF"}


def find_url(title_id: str, start: str, kind: str, fmt: str, vol: int) -> str:
    return (
        f"{API_BASE}/documents/find(titleid='{title_id}',asat={start},"
        f"type='{kind}',format='{fmt}',uniqueTypeNumber=0,"
        f"volumeNumber={vol},rectificationVersionNumber=0)"
    )


def file_path(title_id: str, start: str, kind: str, fmt: str, comp: str | None) -> str:
    """Raw-tree path: one folder per title; as-made under asmade/, each
    compilation at the title root named by its number and start date."""
    ext = fmt.lower()
    shard = f"01_raw/frl/{title_id[:2]}/{title_id}"
    if comp == "0":
        suffix = "ES" if kind == "ES" else ""
        return f"{shard}/asmade/{title_id}{suffix}.{ext}"
    return f"{shard}/comp{int(str(comp)):03d}_{start}.{ext}"


class FrlDocHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=find_url(
                str(task.params["title_id"]),
                str(task.params["start"]),
                str(task.params["kind"]),
                str(task.params["fmt"]),
                int(task.params.get("vol", 0)),
            )
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        if response.status_code != 200:
            raise ValueError(f"file download returned HTTP {response.status_code}")

        title_id = str(task.params["title_id"])
        start = str(task.params["start"])
        kind = str(task.params["kind"])
        comp = task.params.get("comp")
        collection = str(task.params.get("collection") or "")
        publication_date = task.params.get("publication_date") or None
        fmt = str(task.params["fmt"]).lower()

        # Dual representation (probed 2026-08-31): some titles answer with
        # the JSON envelope, others stream the raw file. Sniff, don't guess.
        if response.content.lstrip()[:1] == b"{":
            envelope = response.json()
            encoded = envelope.get("bytes")
            if not encoded:
                raise ValueError("download envelope carries no bytes field")
            content = base64.b64decode(encoded)
        else:
            envelope = {}
            content = response.content
            if not content:
                raise ValueError("download response is empty")

        magic = _MAGIC.get(fmt)
        if magic and not content.startswith(magic):
            raise ValueError(
                f"decoded {title_id} {fmt} does not start with {magic!r} "
                "— response is not the advertised format"
            )

        version = envelope.get("version") or {}
        base_name = (
            version.get("name") or task.params.get("name") or title_id
        )
        if kind == "ES":
            doc_title = f"{base_name} — Explanatory Statement"
        elif comp not in (None, "0"):
            doc_title = f"{base_name} — Compilation {comp}"
        else:
            doc_title = base_name

        as_made = comp == "0"
        source_url = canonical_source_url(title_id, start, kind, fmt, as_made)
        doc_id = compute_doc_id("AUS", source_url, publication_date)
        doc_type = "OTHER" if kind == "ES" else collection_doc_type(collection)

        meta: dict[str, str] = {
            "title_id": title_id,
            "version_start": start,
            "doc_kind": "es" if kind == "ES" else "primary",
            "collection": collection,
        }
        if comp is not None:
            meta["compilation_number"] = str(comp)
        if envelope:
            # raw-stream titles contribute none of these — meta simply
            # carries what the representation offers
            if envelope.get("fileName"):
                meta["file_name"] = str(envelope["fileName"])
            if envelope.get("sizeInBytes") is not None:
                meta["size_in_bytes"] = str(envelope["sizeInBytes"])
            if envelope.get("isAuthorised") is not None:
                meta["is_authorised"] = "1" if envelope["isAuthorised"] else "0"
            if envelope.get("compilationNumber") is not None:
                meta["envelope_compilation_number"] = str(envelope["compilationNumber"])
            registered = (version.get("registeredAt") or "")[:19]
            if registered:
                meta["registered_at"] = registered

        path = file_path(title_id, start, kind, fmt, comp)
        return TaskResult(
            documents=[
                DocumentRecord(
                    title=doc_title,
                    source_url=source_url,
                    publication_date=publication_date,
                    doc_type=doc_type,
                    entity_ref=f"titles:{title_id}",
                    language="eng",
                    raw_metadata=meta,
                )
            ],
            files=[FileOut(path=path, content=content, doc_id=doc_id)],
        )
