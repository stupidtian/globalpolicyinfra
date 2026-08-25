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
    "FileOut",
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
    transport exists.
    """

    url: str
    params: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    key_env: str | None = None
    key_param: str | None = None
    transport: str = "http"
    browser_plan: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


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
    (e.g. ``01_raw/policies/119/HR204/text/ih.xml``). Paths must land under
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
    expected_empty: str | None = None

    def is_empty(self) -> bool:
        return not (
            self.upsert_rows
            or self.replacements
            or self.documents
            or self.files
            or self.next_tasks
        )


class TaskHandler(Protocol):
    """The entire country-side implementation of one task type: two pure
    functions."""

    def build_request(self, task: TaskView) -> RequestSpec: ...

    def parse(self, response: Response, task: TaskView) -> TaskResult: ...


@dataclass(frozen=True)
class SourceDefinition:
    """One source of one country, as declared by the country pack.

    ``domain_keys`` maps each domain table to its primary-key column(s).
    The ledger's upsert is UPDATE-then-INSERT keyed on these, so country
    rows may be partial (merge into the existing row) without tripping
    NOT NULL constraints on the insert path.
    """

    name: str
    start_tasks: Callable[[dict[str, Any]], list[TaskSeed]]
    task_types: dict[str, TaskHandler]
    domain_schema: str = ""  # DDL executed once when the ledger opens
    domain_tables: tuple[str, ...] = ()  # for status counting / inspection
    domain_keys: dict[str, tuple[str, ...]] = field(default_factory=dict)
