"""Task type ``rt_text``: the POST channel (documentHtml + metadata).

POST ``/api/document/{eli}`` with an (empty) JSON body — the SPA's own
call, probed 2026-09-16: bodyless POST answers 415, ``{}`` answers 200,
and the ``isRawHtml`` flag has no observable effect. The response carries
the full display metadata (including the authoritative publication date
"Offentliggørelsesdato" and the medium "Offentliggjort i") plus
``documentHtml`` — the ONLY full text for stub-era documents (probed down
to 1963; XML text starts ~2008).

Two modes, keyed by params:

- ``text=1`` (chained from a stub ``rt_doc``): store ``documentHtml`` as
  the sibling file ``text.html`` and register it in the ``doc_texts``
  domain table (doc_id recomputed on the SAME pub basis rt_doc used, so
  the keys always match; the POST-side real publication date is kept in
  doc_texts.publication_date). A textless response (e.g. Lovtidende B
  notices) is an explained empty.
- ``resolve=1`` (chained from ``rt_harvest``, which only knows accession
  numbers): derive the canonical path from the metadata medium + year +
  number and chain ``rt_doc`` on it — refresh docs keep the same
  source_url (and therefore doc_id) as their window-mode originals.
"""

from __future__ import annotations

from typing import Any

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.dnk.sources.retsinformation import (
    API_BASE,
    MEDIA_MAP,
    parse_dk_date,
    split_eli,
)
from core.document import compute_doc_id

__all__ = ["RtTextHandler"]


class RtTextHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=f"{API_BASE}/api/document{task.params['eli']}",
            method="POST",
            json_body={},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        eli = str(task.params["eli"])
        payload: Any = response.json()
        item = payload[0] if isinstance(payload, list) else payload
        if not isinstance(item, dict):
            raise TypeError(f"rt_text {eli}: unexpected payload shape")
        metadata = {
            str(m.get("displayName") or ""): str(m.get("displayValue") or "")
            for m in item.get("metadata") or []
            if isinstance(m, dict)
        }

        pub_real = parse_dk_date(metadata.get("Offentliggørelsesdato"))
        html = item.get("documentHtml") or ""

        want_text = str(task.params.get("text", "")) == "1"
        want_resolve = str(task.params.get("resolve", "")) == "1"
        if not want_text and not want_resolve:
            raise ValueError(f"rt_text {eli}: neither text=1 nor resolve=1 in params")

        files: list[FileOut] = []
        rows: dict[str, list[dict[str, Any]]] = {}
        next_tasks: list[TaskSeed] = []
        empties: list[str] = []

        if want_text:
            if not html.strip():
                empties.append(
                    f"rt_text {eli}: no documentHtml — textless document "
                    "(metadata-only registration stands)"
                )
            else:
                pub_basis = str(task.params.get("pub", "")).strip() or None
                doc_id = compute_doc_id("DNK", f"{API_BASE}{eli}", pub_basis)
                media, year, _number, flat = split_eli(eli)
                if media == "accn":
                    folder = f"01_raw/retsinformation/accn/{flat}"
                else:
                    folder = f"01_raw/retsinformation/{media}/{year}/{flat}"
                text_path = f"{folder}/text.html"
                files.append(FileOut(path=text_path, content=html.encode("utf-8")))
                rows["doc_texts"] = [
                    {"doc_id": doc_id, "text_path": text_path, "publication_date": pub_real}
                ]

        if want_resolve:
            media_name = metadata.get("Offentliggjort i (publiceringsmedie)") or ""
            media = MEDIA_MAP.get(media_name, "")
            year = metadata.get("År for udstedelse") or ""
            number = metadata.get("Forskriftens nummer") or ""
            # the change feed covers the whole site; changes outside the
            # run's media scope explain away here (nothing was collected
            # under that media, so there is nothing to refresh)
            scope = {m.strip() for m in str(task.params.get("scope", "lta,ltb")).split(",")}
            if media and media not in scope:
                return TaskResult(
                    expected_empty=(
                        f"rt_text {eli}: medium {media_name!r} outside scope "
                        f"({','.join(sorted(scope))}) — nothing collected under "
                        "it, nothing to refresh"
                    )
                )
            if media and year and number:
                canonical = f"/eli/{media}/{year}/{number}"
            else:
                canonical = eli  # accn fallback: still fetchable, documented shape
            next_tasks.append(
                TaskSeed(
                    type="rt_doc",
                    params={
                        "eli": canonical,
                        "pub": pub_real or "",
                        "code": str(task.params.get("code", "")),
                    },
                )
            )

        result = TaskResult(files=files, upsert_rows=rows, next_tasks=next_tasks)
        if empties and result.is_empty():
            result.expected_empty = "; ".join(empties)
        elif empties:
            # text wanted but absent while resolving — note it in meta-less
            # fashion by appending to the (non-empty) result's last file name
            # is pointless; surface via stdout-free explanation in the seed
            # chain instead. Nothing to do: the resolution still proceeds.
            pass
        return result
