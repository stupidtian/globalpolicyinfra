"""HTTP transport: throttle, seconds-scale retries, key injection.

Boundary (decision record 2026-08-20): this layer absorbs single-request
jitter (connection resets, 429, 5xx, timeouts, WAF-challenge and temporary-ban
status codes 202/437/438 observed on government sites) with short exponential
backoff; once its budget is spent it raises :class:`TransientError` and the
engine decides when the task is retried.

Key injection (section 6.3): the API key never travels in task params or the
ledger — the country's ``build_request`` names the environment variable
(``key_env``) and the query-parameter slot (``key_param``), and the value is
read here, at the last moment.
"""

from __future__ import annotations

import os
import random
import threading
import time
from typing import Any, Protocol

import requests

from adapters.base import RequestSpec, Response
from runtime.errors import PermanentError, TransientError

__all__ = ["HttpTransport", "Transport"]


class Transport(Protocol):
    """What the engine needs from any transport (http or browser)."""

    def fetch(self, spec: Any) -> Response: ...  # pragma: no cover - protocol


class HttpTransport:
    """GET-oriented HTTP transport with per-request retry and politeness.

    Concurrency (framework-concurrency rulings 1.3/1.5): the politeness
    delay is a **global** rate gate shared by every worker thread, and each
    thread gets its own :class:`requests.Session` (cookies never cross
    workers). With a single worker both behaviors are exactly today's.
    """

    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        *,
        delay_range: tuple[float, float] = (0.5, 1.0),
        max_retries: int = 3,
        timeout: float = 30.0,
        session: requests.Session | None = None,
    ) -> None:
        self.delay_range = delay_range
        self.max_retries = max_retries
        self.timeout = timeout
        self._injected_session = session
        if session is not None:
            session.headers.update({"User-Agent": self.DEFAULT_USER_AGENT})
        self._local = threading.local()
        self._pace_lock = threading.Lock()
        self._next_slot = 0.0

    def session(self) -> requests.Session:
        """The calling thread's session. An explicitly injected session is
        shared as-is (single worker / tests); otherwise each thread creates
        its own — requests.Session is not thread-safe and cookie state must
        not cross workers (ruling 1.5)."""
        if self._injected_session is not None:
            return self._injected_session
        existing = getattr(self._local, "session", None)
        if existing is None:
            existing = requests.Session()
            existing.headers.update({"User-Agent": self.DEFAULT_USER_AGENT})
            self._local.session = existing
        return existing

    def acquire_pace_slot(self) -> float:
        """Global rate gate (token-bucket semantics, capacity 1, random
        refill): returns the number of seconds the caller must sleep
        before issuing its request.

        Request starts are globally spaced ``uniform(MIN, MAX)`` — with one
        worker that is exactly today's per-request sleep; with N workers the
        total rate stays ``1 / mean(interval)`` and never multiplies with
        the worker count (ruling 1.3)."""
        with self._pace_lock:
            now = time.monotonic()
            wait = max(0.0, self._next_slot - now) + random.uniform(*self.delay_range)
            self._next_slot = now + wait
        return wait

    def fetch(self, spec: RequestSpec) -> Response:
        """Execute one RequestSpec → Response, classifying terminal failure
        into the error trisection."""
        params: dict[str, Any] = dict(spec.params or {})
        if spec.key_env and spec.key_param:
            key = os.environ.get(spec.key_env, "").strip()
            if not key:
                raise PermanentError(
                    f"{spec.key_env} is not set. Put it in the repository .env "
                    "(see .env.example)."
                )
            params[spec.key_param] = key

        url = spec.url
        session = self.session()
        method = (spec.method or "GET").upper()
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            time.sleep(self.acquire_pace_slot())
            try:
                if method == "GET":
                    response = session.get(
                        url,
                        params=params or None,
                        headers=spec.headers or None,
                        timeout=self.timeout,
                    )
                elif method == "POST":
                    # json_body=None keeps a bodyless POST; a dict is sent as
                    # the JSON body (first consumer: DNK retsinformation's
                    # documentHtml endpoint, 2026-09-16).
                    response = session.post(
                        url,
                        params=params or None,
                        json=spec.json_body,
                        headers=spec.headers or None,
                        timeout=self.timeout,
                    )
                else:
                    raise PermanentError(
                        f"Unsupported transport method {method!r} for {url}"
                    )
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(min(30.0, 2.0**attempt))
                continue
            if response.status_code == 200:
                return Response(content=response.content, status_code=200)
            if response.status_code in (404, 410):
                if spec.accept_not_found:
                    # The source declared not-found as data (e.g. a
                    # date-addressed API answering "nothing published that
                    # day"); the country's parse decides what it means.
                    return Response(
                        content=response.content, status_code=response.status_code
                    )
                raise PermanentError(f"HTTP {response.status_code} for {url}")
            if response.status_code in (202, 429, 437, 438) or response.status_code >= 500:
                # 429/5xx: classic overload. 202/437/438 are site-state, not
                # task truth (observed on legislation.gov.uk, 2026-09): 202 with
                # ``x-amzn-waf-action: challenge`` is an AWS WAF fingerprint
                # challenge; 437/438 are app-level temporary ban / rate cap.
                # All can lift on their own, so they retry like any transient.
                last_error = TransientError(
                    f"HTTP {response.status_code} for {url} (attempt {attempt})"
                )
                time.sleep(min(60.0, 2.0**attempt))
                continue
            raise PermanentError(f"HTTP {response.status_code} for {url}")
        raise TransientError(f"Transport retries exhausted for {url}: {last_error}")
