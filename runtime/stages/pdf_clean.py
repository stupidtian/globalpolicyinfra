"""PDF cleaning router (framework-pdf-cleaning 2026-09-28).

One framework handler serves every country's PDF cleaning: it measures
the document (:func:`runtime.stages.cleaning.measure_pdf`), routes by the
country's declared rule table (:class:`adapters.base.PdfRule` — fixed
code over declaration data, zero runtime intelligence), and either
extracts locally (geometry channel, version ``v*100``) or derives the
MinerU chain (version ``v*100 + fp`` at fetch time). Scans fail
permanently; shapes outside the declared table escalate loudly.

Routing rules are fixed code, so the loud outcomes are fixed code too:

- fewer than 20 text chars (deep-collected) → PermanentError "扫描件——
  OCR 界外" (user ruling 2026-09-19/28: no OCR in this project);
- rules declared but none matches → unclassified exception → the engine
  escalates to needs_agent (never guess a channel);
- no rules at all → every digital PDF goes to the geometry channel.
"""

from __future__ import annotations

from typing import Any

from adapters.base import (
    CleanDefinition,
    CleanedRecord,
    PdfRule,
    RequestSpec,
    Response,
    TaskHandler,
    TaskResult,
    TaskSeed,
    TaskView,
)
from runtime.errors import PermanentError
from runtime.stages import pdf_mineru
from runtime.stages.cleaning import geometry_pdf_to_text, measure_pdf

__all__ = ["PdfCleanHandler", "pdf_clean_handlers"]

#: Documents with fewer deep-collected text chars than this are treated as
#: image-only (scans): OCR is out of scope by user ruling, so they fail
#: permanently and loudly.
SCAN_CHAR_FLOOR = 20


def route_channel(measure: dict[str, float | int], rules: tuple[PdfRule, ...]) -> str:
    """First matching rule wins; no match with rules declared is an
    escalation; no rules at all defaults to geometry."""
    for rule in rules:
        value: Any = measure.get(rule.feature)
        if value is None:
            continue
        if rule.lo is not None and value < rule.lo:
            continue
        if rule.hi is not None and value > rule.hi:
            continue
        return rule.channel
    if rules:
        raise RuntimeError(
            f"PDF shape outside the declared routing rules: {measure}"
        )
    return "geometry"


class PdfCleanHandler(TaskHandler):
    """The framework-side clean handler for PDF documents.

    Registered under the source's ``CleanDefinition.task_type`` (usually
    via :func:`pdf_clean_handlers`); seeding params are ``{doc_id, v,
    kind}`` as for every clean task.
    """

    def __init__(self, definition: CleanDefinition) -> None:
        self._definition = definition

    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(local_doc=str(task.params["doc_id"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        doc_id = str(task.params["doc_id"])
        data = response.content
        measure = measure_pdf(data)
        if int(measure["chars"]) < SCAN_CHAR_FLOOR:
            raise PermanentError(
                f"扫描件——OCR 界外: doc {doc_id} has {measure['chars']} text chars "
                f"across {measure['pages']} page(s); scanned documents are out of "
                "scope (2026-09-19 user ruling)"
            )
        channel = route_channel(measure, self._definition.pdf_rules)
        if channel == "geometry":
            text = geometry_pdf_to_text(data)
            return TaskResult(
                cleaned=[
                    CleanedRecord(
                        doc_id=doc_id,
                        # Geometry is deterministic per rule version, so the
                        # stored version is v*100 (fingerprint slot 0) — same
                        # encoding the MinerU channel uses with fp > 0.
                        version=int(task.params["v"]) * 100,
                        content=text.encode("utf-8"),
                    )
                ]
            )
        pages = int(measure["pages"])
        if not pdf_mineru.try_reserve_pages(pages):
            # Over the run's --api-pages budget: complete silently; the
            # seed's fresh date signal reopens the task the next day.
            return TaskResult(
                expected_empty=(
                    f"MinerU daily page budget exhausted; doc {doc_id} "
                    f"({pages}p) deferred — re-run clean tomorrow"
                )
            )
        return TaskResult(
            next_tasks=[
                TaskSeed(
                    type=pdf_mineru.SUBMIT_TYPE,
                    params={
                        "doc_id": doc_id,
                        "v": task.params["v"],
                        "kind": task.params["kind"],
                    },
                )
            ]
        )


def pdf_clean_handlers(
    definition: CleanDefinition, *, submit_session: Any = None
) -> dict[str, TaskHandler]:
    """Everything one PDF-clean declaration registers: the router under
    the declared type plus the MinerU chain. (Thin alias — the chain
    handlers live with their protocol in :mod:`runtime.stages.pdf_mineru`.)"""
    return pdf_mineru.chain_handlers(definition, submit_session=submit_session)
