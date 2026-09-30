"""MinerU network-interface channel (framework-pdf-cleaning 2026-09-28).

MinerU (mineru.net) parses complex PDF layouts server-side. The channel
is a three-task chain — submit / poll / fetch — riding the ordinary task
engine: every link is a normal task (params in, TaskResult out), so
resume, retry-with-backoff, the trisection and the ledger all come free.

- ``pdf_m_submit``: local upload path (user ruling 2026-09-29 — file
  bytes go up directly, never a public URL). The engine reads the local
  PDF (``local_doc``) and this framework handler's ``parse`` performs the
  two-request transaction: ``POST /api/v4/file-urls/batch`` for a
  presigned upload slot, then ``PUT`` the bytes to it. Deviation (plan
  Q1, user-approved): two HTTP requests inside one task, atomic on
  retry — a fresh attempt re-applies for a new slot, so the 24h presigned
  URL never has to persist in params.
- ``pdf_m_poll``: one ``GET`` on the batch status. Not-finished states
  raise :class:`TransientError` — the engine's existing backoff reschedules
  the same task ("查询未完成走既有暂态重试").
- ``pdf_m_fetch``: one ``GET`` on the result zip; the handler unzips in
  memory, post-processes the Markdown to plain text (tables → one cell
  per line, markup stripped) and emits the ``CleanedRecord``. The clean
  version carries the backend fingerprint: ``v*100 + fp`` — a server-side
  model upgrade changes fp, which reseeds those docs (determinism
  absorption, plan Q3).

The API token lives in the ``MINERU_API_TOKEN`` environment variable
(``.env``); it travels only in Authorization headers and never enters
params, the ledger, or logs. This module is framework code: the handlers
here may do I/O (that is what "all I/O belongs to the framework" means);
country packs stay pure and only declare the routing table.
"""

from __future__ import annotations

import io
import os
import re
import zipfile

import requests

from adapters.base import (
    CleanDefinition,
    CleanedRecord,
    RequestSpec,
    Response,
    TaskHandler,
    TaskResult,
    TaskSeed,
    TaskView,
)
from runtime.errors import PermanentError, TransientError

__all__ = [
    "FETCH_TYPE",
    "POLL_TYPE",
    "SUBMIT_TYPE",
    "MineruFetchHandler",
    "MineruPollHandler",
    "MineruSubmitHandler",
    "mineru_markdown_to_text",
]

SUBMIT_TYPE = "pdf_m_submit"
POLL_TYPE = "pdf_m_poll"
FETCH_TYPE = "pdf_m_fetch"

MINERU_API = "https://mineru.net/api/v4"
TOKEN_ENV = "MINERU_API_TOKEN"

_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MARKDOWN_EMPH = re.compile(r"(\*{1,3}|`{1,3}|_{1,3})")
_MARKDOWN_TABLE_SEP = re.compile(r"^\|?\s*:?-{3,}.*\|")


def mineru_markdown_to_text(md: str) -> str:
    """MinerU result Markdown → deterministic plain text (contract §0.5):
    table rows degrade to one cell per line (same shape as the HTML
    channel), markup markers are stripped, whitespace folding matches
    :func:`runtime.stages.cleaning.html_to_text`."""
    out: list[str] = []
    for raw in md.splitlines():
        line = raw.rstrip()
        if _MARKDOWN_TABLE_SEP.match(line):
            continue  # |---|---| separator rows
        if line.lstrip().startswith("|") and line.rstrip().endswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            out.extend(cells)
            continue
        line = _MARKDOWN_IMAGE.sub("", line)
        line = _MARKDOWN_LINK.sub(r"\1", line)
        line = _MARKDOWN_EMPH.sub("", line)
        if line.lstrip().startswith(("#", ">",)):
            line = line.lstrip().lstrip("#>").lstrip()
        out.append(line)
    folded: list[str] = []
    for line in out:
        text = re.sub(r"[ \t\u00a0]+", " ", line).strip()
        if text:
            folded.append(text)
    return "\n".join(folded) + "\n" if folded else ""


def _token() -> str:
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        raise PermanentError(
            f"{TOKEN_ENV} is not set. Put it in the repository .env "
            "(see .env.example)."
        )
    return token


# -- daily page budget (opt-in via `clean --api-pages N`) ----------------------
#
# Process-local state wired by the CLI at run start (cli reads today's kv
# counter and hands it here); the ledger persistence happens once at run
# end, also by the CLI. Handlers touch nothing but these functions. Serial
# runs only (the clean command; see plan deviation D4).

_budget_pages: int | None = None
_used_pages = 0
_deferred = 0


def configure_pages(*, budget: int | None, used: int = 0) -> None:
    """(Re)arm the daily budget for one clean run. ``budget=None`` (the
    default) disables accounting entirely — MinerU's soft quota then
    simply degrades priority past 1000 pages/day."""
    global _budget_pages, _used_pages, _deferred
    _budget_pages = budget
    _used_pages = used
    _deferred = 0


def pages_reserved() -> int:
    return _used_pages


def deferred_count() -> int:
    return _deferred


def try_reserve_pages(pages: int) -> bool:
    """Reserve ``pages`` against the run budget; False = over budget, the
    caller defers the document (task completes with ``expected_empty``, a
    fresh seed signal reopens it the next day)."""
    global _used_pages, _deferred
    if _budget_pages is None:
        return True
    if _used_pages + pages > _budget_pages:
        _deferred += 1
        return False
    _used_pages += pages
    return True


# -- chain handlers --------------------------------------------------------------


class MineruSubmitHandler(TaskHandler):
    """POST for an upload slot + PUT the local file's bytes (one atomic
    transaction; a retry re-applies for a fresh slot)."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def build_request(self, task: TaskView) -> RequestSpec:
        # Local read through the engine's local_doc machinery: the handler
        # never touches the filesystem or the ledger itself.
        return RequestSpec(local_doc=str(task.params["doc_id"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        doc_id = str(task.params["doc_id"])
        headers = {"Authorization": f"Bearer {_token()}"}
        try:
            r1 = self._session.post(
                f"{MINERU_API}/file-urls/batch",
                json={"files": [{"name": f"{doc_id}.pdf"}]},
                headers=headers,
                timeout=60,
            )
        except requests.RequestException as exc:
            raise TransientError(f"MinerU submit POST failed: {exc}") from exc
        if r1.status_code != 200:
            self._classify(r1.status_code, r1.text[:200], "submit POST")
        payload = r1.json()
        if payload.get("code") not in (0, 200, None):
            raise PermanentError(f"MinerU submit rejected: {payload}")
        data = payload.get("data") or {}
        batch_id = data.get("batch_id")
        urls = data.get("file_urls") or []
        if not batch_id or not urls:
            raise PermanentError(f"MinerU submit response missing batch data: {payload}")
        try:
            r2 = self._session.put(urls[0], data=response.content, timeout=300)
        except requests.RequestException as exc:
            raise TransientError(f"MinerU upload PUT failed: {exc}") from exc
        if r2.status_code != 200:
            # A rejected PUT (expired/invalid slot, OSS hiccup) is retried as
            # a whole: the next attempt re-applies for a fresh slot.
            raise TransientError(
                f"MinerU upload PUT returned {r2.status_code} for batch {batch_id}"
            )
        return TaskResult(
            next_tasks=[
                TaskSeed(
                    type=POLL_TYPE,
                    params={
                        "doc_id": doc_id,
                        "v": task.params["v"],
                        "kind": task.params["kind"],
                        "batch_id": str(batch_id),
                    },
                )
            ]
        )

    def _classify(self, status: int, body: str, what: str) -> None:
        if status == 429 or status >= 500:
            raise TransientError(f"MinerU {what}: HTTP {status} {body}")
        raise PermanentError(f"MinerU {what}: HTTP {status} {body}")


class MineruPollHandler(TaskHandler):
    """One GET on the batch status. Not-finished → TransientError (the
    engine reschedules with backoff); failed → PermanentError with the
    server's err_msg; done → derive the fetch task."""

    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=f"{MINERU_API}/extract-results/batch/{task.params['batch_id']}",
            key_header=TOKEN_ENV,
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        payload = response.json()
        results = (payload.get("data") or {}).get("extract_result") or []
        if not results:
            raise TransientError(
                f"MinerU batch {task.params['batch_id']}: no result rows yet"
            )
        row = results[0]
        state = str(row.get("state", ""))
        if state == "done":
            zip_url = row.get("full_zip_url")
            if not zip_url:
                raise PermanentError(f"MinerU batch done but no zip url: {row}")
            return TaskResult(
                next_tasks=[
                    TaskSeed(
                        type=FETCH_TYPE,
                        params={
                            "doc_id": task.params["doc_id"],
                            "v": task.params["v"],
                            "kind": task.params["kind"],
                            "zip_url": str(zip_url),
                        },
                    )
                ]
            )
        if state == "failed":
            raise PermanentError(
                f"MinerU batch {task.params['batch_id']} failed: {row.get('err_msg')}"
            )
        # waiting-file / pending / running / converting
        raise TransientError(
            f"MinerU batch {task.params['batch_id']} state={state!r}"
        )


class MineruFetchHandler(TaskHandler):
    """One GET on the result zip; unzip in memory, post-process the
    Markdown, emit the CleanedRecord with version ``v*100 + fp``."""

    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=str(task.params["zip_url"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        try:
            archive = zipfile.ZipFile(io.BytesIO(response.content))
        except zipfile.BadZipFile as exc:
            raise TransientError(f"MinerU result zip is corrupt: {exc}") from exc
        names = sorted(archive.namelist())
        md_names = [n for n in names if n.lower().endswith(".md")]
        if not md_names:
            raise PermanentError(
                f"MinerU result zip has no markdown member: {names[:10]}"
            )
        md = archive.read("full.md" if "full.md" in names else md_names[0]).decode(
            "utf-8", errors="replace"
        )
        text = mineru_markdown_to_text(md)
        fp = _backend_fingerprint(names)
        version = int(task.params["v"]) * 100 + fp
        return TaskResult(
            cleaned=[
                CleanedRecord(
                    doc_id=str(task.params["doc_id"]),
                    version=version,
                    content=text.encode("utf-8"),
                )
            ]
        )


def _backend_fingerprint(zip_names: list[str]) -> int:
    """Two-digit backend fingerprint folded into the clean version (plan
    Q3): a server-side model upgrade must change the version so affected
    docs get re-cleaned. Real MinerU zips carry model/version metadata —
    extraction awaits a token (plan deviation D2); until then the
    fingerprint is a stable 0 (same v → byte-identical reruns still
    hold)."""
    return 0


def chain_handlers(
    definition: CleanDefinition, *, submit_session: requests.Session | None = None
) -> dict[str, TaskHandler]:
    """The complete handler set one PDF-clean declaration needs: the
    router under the declared task type plus the three chain types.
    Country packs merge this into ``task_types`` — one import, four
    registrations, zero chain plumbing. ``submit_session`` injects the
    HTTP session the submit handler talks through (tests; production uses
    the default real session)."""
    from runtime.stages.pdf_clean import PdfCleanHandler

    return {
        definition.task_type: PdfCleanHandler(definition),
        SUBMIT_TYPE: MineruSubmitHandler(session=submit_session),
        POLL_TYPE: MineruPollHandler(),
        FETCH_TYPE: MineruFetchHandler(),
    }
