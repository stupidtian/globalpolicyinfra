"""Task type ``rt_classifiers``: the issuer/type classifier, archived once.

``GET /public-api/api/v1/avalik/klassifikaatorid/alg-tekstid`` — the
source's own vocabulary: 648 issuers (529 flagged ``kov: true``, covering
current and pre-2017-reform municipalities) and 25 native act types
(probed 2026-10-27). The snapshot is stored as
``01_raw/riigiteataja/classifiers.json`` — the reference copy that makes
the row-level municipal filter auditable against the vocabulary as it
stood at collection time. The runtime filter itself is the compound-word
rule in the source package (pure functions cannot read files), so this
task runs once per ledger (done-skipped afterwards) and produces no
documents.
"""

from __future__ import annotations

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.est.sources.riigiteataja import PUBLIC_API_BASE, REQUEST_HEADERS

__all__ = ["ClassifiersHandler"]


class ClassifiersHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=f"{PUBLIC_API_BASE}/avalik/klassifikaatorid/alg-tekstid",
            headers=REQUEST_HEADERS,
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(f"rt_classifiers: body is not JSON: {exc}") from exc
        issuers = payload.get("aktiAndjad")
        types = payload.get("aktiLiigid")
        if not isinstance(issuers, list) or not isinstance(types, list) or not issuers:
            raise ValueError(
                "rt_classifiers: unexpected response shape "
                f"(keys={sorted(payload)!r}) — classifier may have moved"
            )
        return TaskResult(
            files=[
                FileOut(
                    path="01_raw/riigiteataja/classifiers.json",
                    content=response.content,
                )
            ]
        )
