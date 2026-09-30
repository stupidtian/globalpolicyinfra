"""The country-pack contract: four data types and nothing else.

ARCHITECTURE.md section 6.3 — the **complete** width of the boundary between
framework and country pack. Everything a country wants to do must be
expressible through these objects; everything the framework knows about a
country comes through them. Country packs are pure functions: no requests,
no sqlite, no file writes, no browser — all I/O belongs to the framework.

    Task        = (type: str, params: dict)                 → work to do
    RequestSpec = (url, params, key_env, transport, ...)    → how to fetch it
    Response    = (bytes, status_code)                      → what came back
    TaskResult  = rows / documents / files / next_tasks / cursors
                                                          → what it yielded
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from core.document import DocumentRecord

__all__ = [
    "BROWSER_ACTIONS",
    "CleanDefinition",
    "CleanedRecord",
    "FileOut",
    "PdfRule",
    "ReplaceRows",
    "RequestSpec",
    "Response",
    "SourceDefinition",
    "TaskHandler",
    "TaskResult",
    "TaskSeed",
    "TaskView",
]

#: Action vocabulary for the browser transport (section 6.6). The vocabulary
#: is a shared framework asset; country packs compose plans from these words
#: and may not invent their own browser logic outside the exception channel.
BROWSER_ACTIONS: tuple[str, ...] = (
    "click",
    "wait_for",
    "try_click",
    "click_first_present",
    "scroll_to_end",
    "type_text",
    "wait_seconds",
)


@dataclass(frozen=True)
class TaskSeed:
    """Work a country wants enqueued: a task type plus its params.

    ``signal`` (optional) carries the source-side freshness stamp (e.g. the
    API's updateDate). Enqueue uses it to decide whether an already-done
    task must be reopened (section 6.5).
    """

    type: str
    params: dict[str, Any] = field(default_factory=dict)
    signal: str | None = None


@dataclass(frozen=True)
class TaskView:
    """A task as a country handler sees it (no scheduling fields)."""

    task_id: str
    type: str
    params: dict[str, Any]
    signal: str | None = None


@dataclass(frozen=True)
class RequestSpec:
    """How to fetch one task's data.

    ``key_env``/``key_param``: the environment variable holding the API key
    and the query-parameter slot it goes into — the key value itself never
    appears here. ``transport``: "http" today; "browser" with a
    ``browser_plan`` (a list of BROWSER_ACTIONS steps) once the browser
    transport exists. ``accept_not_found``: declare that this request's
    404/410 is *data, not an error* — the transport then hands the response
    to the country's parse instead of raising PermanentError (date-addressed
    APIs where "not found" legitimately means "nothing published that day",
    e.g. the BOE daily summary; first adopted for ESP 2026-09-01). The
    parser, not the framework, decides what the not-found response means.

    ``method``/``json_body`` (2026-09-16, user-ruled contract evolution, first
    consumer DNK retsinformation): HTTP method of the single request —
    "GET" (default, semantics untouched) or "POST" — and for POST the JSON
    request body (``None`` = bodyless POST).

    ``local_doc`` (2026-09-19, framework-cleaning): read a local file
    instead of the network — the value is a ``doc_id``; the engine resolves
    it through ``documents.local_path`` (``.gz`` suffix is decompressed
    automatically) and hands the bytes to ``parse`` as a 200 Response. No
    HTTP transport involved: no ``--delay`` pacing, no session, runs with
    transport=None. ``local_doc`` set means ``url`` is ignored; both empty
    is a loud engine error.

    ``key_header`` (2026-09-28, framework-pdf-cleaning; first consumer
    MinerU): the environment variable holding the API token, injected by
    the transport as an ``Authorization: Bearer <value>`` request header.
    Same discipline as ``key_env``: only the variable's NAME travels here —
    the value is read at the last moment and never enters params, the
    ledger, or logs.
    """

    url: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    key_env: str | None = None
    key_param: str | None = None
    transport: str = "http"
    browser_plan: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    accept_not_found: bool = False
    method: str = "GET"
    json_body: dict[str, Any] | None = None
    local_doc: str | None = None
    key_header: str | None = None


@dataclass(frozen=True)
class Response:
    """Raw bytes back from the transport, plus the HTTP status."""

    content: bytes
    status_code: int

    def json(self) -> dict[str, Any]:
        import json

        try:
            payload: dict[str, Any] = json.loads(self.content.decode("utf-8"))
            return payload
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Response is not valid JSON: {exc}") from exc


@dataclass(frozen=True)
class FileOut:
    """A file the country wants written, relative to the country root
    (e.g. ``01_raw/bills/119/HR204/text/ih.xml``). Paths must land under
    the country directory; the framework rejects escapes."""

    path: str
    content: bytes
    doc_id: str | None = None  # set when this file IS a document's artifact


@dataclass
class ReplaceRows:
    """Row-group replacement semantics: delete rows matching ``match`` in
    ``table`` (an equality dict), then insert ``rows``. Used for
    rewrite-style histories (e.g. a bill's whole action list)."""

    table: str
    match: dict[str, Any]
    rows: list[dict[str, Any]]


@dataclass(frozen=True)
class CleanedRecord:
    """One document's cleaned plain text (framework-cleaning 2026-09-19).

    The framework — never the country pack — derives the on-disk path
    (``02_cleaned/{sha256(doc_id)[:2]}/{doc_id}.txt``) and the ledger row.
    ``content`` must be deterministic UTF-8 text: ``\\n`` line breaks only,
    no BOM, exactly one trailing newline; the engine enforces this loudly.
    """

    doc_id: str
    version: int
    content: bytes


@dataclass
class TaskResult:
    """Everything one task yielded. All fields optional; a result with all
    lists empty is *empty output* — the engine warns and archives the raw
    response unless ``expected_empty`` explains it (e.g. "bill has no
    summary")."""

    upsert_rows: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    replacements: list[ReplaceRows] = field(default_factory=list)
    documents: list[DocumentRecord] = field(default_factory=list)
    files: list[FileOut] = field(default_factory=list)
    next_tasks: list[TaskSeed] = field(default_factory=list)
    cursor_updates: dict[str, str] = field(default_factory=dict)
    cleaned: list[CleanedRecord] = field(default_factory=list)
    expected_empty: str | None = None

    def is_empty(self) -> bool:
        return not (
            self.upsert_rows
            or self.replacements
            or self.documents
            or self.files
            or self.next_tasks
            or self.cleaned
        )


class TaskHandler(Protocol):
    """The entire country-side implementation of one task type: two pure
    functions."""

    def build_request(self, task: TaskView) -> RequestSpec: ...

    def parse(self, response: Response, task: TaskView) -> TaskResult: ...


@dataclass(frozen=True)
class CleanDefinition:
    """A source's cleaning declaration (framework-cleaning 2026-09-19).

    The clean task type's handler is registered in ``task_types`` like any
    other; its ``build_request`` returns ``RequestSpec(local_doc=doc_id)``
    and its ``parse`` produces ``TaskResult.cleaned``. Seeding params are
    ``{doc_id, v, kind}`` — never a file path (task_id identity).

    ``version`` is the cleaning-rule version: bumping it reseeds everything
    (``v`` rides in params → new task ids), old task rows are left alone —
    the same parameterized-reopen family as collection signals (§6.5).

    ``pdf_rules`` (framework-pdf-cleaning 2026-09-28): ordered routing
    table for PDF documents — the FIRST rule whose feature window contains
    the measured value wins; its ``channel`` is "geometry" (local
    pdfminer.six extraction) or "mineru" (MinerU network interface). No
    match with rules declared → the shape is escalated (needs_agent, loud);
    no rules at all → every PDF goes to geometry. Routing is fixed
    framework code over this declaration — zero runtime intelligence.
    """

    task_type: str
    version: int
    targets: tuple[str, ...]  # producing task types whose docs are cleanable
    pdf_rules: tuple[PdfRule, ...] = ()


@dataclass(frozen=True)
class PdfRule:
    """One row of a PDF routing table (framework-pdf-cleaning 2026-09-28):
    route to ``channel`` when ``lo <= measure_pdf()[feature] <= hi``.

    ``None`` bounds are open; ``feature`` must be a ``measure_pdf`` output
    key (pages / chars / text_coverage / columns / vertical_share /
    image_coverage / cjk_share). ``channel`` is "geometry" or "mineru" —
    anything else fails at construction (declaration bugs die at import,
    not at 3 a.m. in a backfill)."""

    feature: str
    lo: float | None = None
    hi: float | None = None
    channel: str = "geometry"

    def __post_init__(self) -> None:
        if self.channel not in ("geometry", "mineru"):
            raise ValueError(
                f"PdfRule channel must be 'geometry' or 'mineru', got {self.channel!r}"
            )


@dataclass(frozen=True)
class SourceDefinition:
    """One source of one country, as declared by the country pack.

    ``domain_keys`` maps each domain table to its primary-key column(s).
    The ledger's upsert is UPDATE-then-INSERT keyed on these, so country
    rows may be partial (merge into the existing row) without tripping
    NOT NULL constraints on the insert path.

    ``parallel_safe`` (framework-concurrency ruling 1.4): declares that any
    task of this source may run on any worker thread with any session —
    no cross-task transport-layer state (cookies/tokens) dependency. Only
    sources declaring True can use ``--workers >= 2``; the engine auto-caps
    undeclared sources to one worker with a warning, so session-bound
    sources (e.g. German-style session chains) can never be hurt.

    ``clean`` (framework-cleaning 2026-09-19): declares this source's
    cleaning task type and rule version; ``None`` (default) = the source
    has no cleaning, behavior unchanged.
    """

    name: str
    start_tasks: Callable[[dict[str, Any]], list[TaskSeed]]
    task_types: dict[str, TaskHandler]
    domain_schema: str = ""  # DDL executed once when the ledger opens
    domain_tables: tuple[str, ...] = ()  # for status counting / inspection
    domain_keys: dict[str, tuple[str, ...]] = field(default_factory=dict)
    parallel_safe: bool = False
    clean: CleanDefinition | None = None
