"""Task type ``pravo_text``: one document's lookup in the legal-text bank.

GET the bank's version ledger (``redactions``) addressed by the
publication number — the same number the official publication uses, so
the two systems meet on one key (probed shapes 2026-10-12, raw samples
in the task folder):

    {"docid": 333380, "dochash": "…", "serverdate": "…",
     "redactions": [{"redid": 497662, "reddate": "20261006",
                     "statename": "Действует без изменений",
                     "redinitial": true, "redofficial": true,
                     "reddocrefid": 0, …}, …]}

- ``redinitial`` marks the *initial* redaction — the as-published text,
  which is the snapshot this source collects. Later redactions (when a
  document was amended) also carry text; their dates, effectivity states
  and amendment references all travel to meta — raw version-series
  fields, graph building stays analysis-side.
- ``docid: 0`` / no redactions / no initial redaction = the document is
  not in the bank. Three known causes: international treaties and UNSC
  resolutions (never in the bank), fresh acts awaiting Ministry-of-
  Justice registration (lags days behind publication), the odd
  historical gap (2 of 5 sampled acts from one 2017 day). All one
  answer: a permanent "bank-miss" — the repair channel (``requeue``)
  re-fetches later, which is exactly how the freshness lag heals.
- The bank is a test-mode system: an HTTP 5xx here is a transient (the
  server answered badly, retrying is meaningful); a 404-shaped
  ``{"Message": …}`` body is the ASP.NET router answering — treat as
  permanent (the route vanished or the request is wrong; either way
  retrying cannot fix it).
"""

from __future__ import annotations

import json
from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.rus.sources.pravo import BANK_API
from runtime.errors import PermanentError, TransientError

__all__ = ["PravoTextHandler"]


def _carry(params: dict[str, Any]) -> dict[str, str]:
    """Listing-derived fields pravo_body needs, kept verbatim."""
    out: dict[str, str] = {}
    for key in (
        "номер",
        "pub_date",
        "title",
        "doc_type",
        "doc_number",
        "doc_date",
        "issuing_authority",
        "pdf_pages",
        "scope",
    ):
        value = str(params.get(key, ""))
        if value:
            out[key] = value
    return out


class PravoTextHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        pnum = str(task.params["номер"])
        t = json.dumps({"pnum": pnum}, ensure_ascii=False, separators=(",", ":"))
        return RequestSpec(
            url=f"{BANK_API}/redactions/",
            params={"bpa": "ebpi", "t": t},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        pnum = str(task.params["номер"])
        if response.status_code >= 500:
            raise TransientError(
                f"pravo_text {pnum}: text-bank answered HTTP "
                f"{response.status_code} (test-mode system flake)"
            )
        if response.status_code != 200:
            raise PermanentError(
                f"pravo_text {pnum}: unexpected HTTP {response.status_code}"
            )
        payload = response.json()

        docid = int(payload.get("docid") or 0)
        redactions = payload.get("redactions") or []
        if not docid or not redactions:
            raise PermanentError(
                f"pravo_text {pnum}: not in the text bank (bank-miss; "
                "requeue later — fresh acts register with a lag, treaties "
                "and UNSC resolutions never enter)"
            )
        initial = next((r for r in redactions if r.get("redinitial")), None)
        if initial is None or not initial.get("redid"):
            raise PermanentError(
                f"pravo_text {pnum}: bank has no initial redaction "
                f"(docid {docid}) — as-published text unavailable"
            )

        versions: list[str] = []
        for red in redactions:
            parts = [
                str(red.get("redid", "")),
                f"@{red.get('reddate', '')}",
                f"/{red.get('statename', '')}",
            ]
            refid = str(red.get("reddocrefid") or "")
            if refid and refid != "0":
                parts.append(f"/amended-by:{refid}")
            versions.append("".join(parts))

        fields = _carry(dict(task.params))
        fields.update(
            {
                "redid": str(initial["redid"]),
                "docid": str(docid),
                "ebpi_docstate": str(initial.get("statename") or ""),
                "ebpi_versions": ";".join(versions),
            }
        )
        return TaskResult(
            next_tasks=[TaskSeed(type="pravo_body", params=fields)],
        )
