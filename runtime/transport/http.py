"""HTTP transport: throttle, seconds-scale retries, key injection.

Boundary (decision record 2026-08-20): this layer absorbs single-request
jitter (connection resets, 429, 5xx, timeouts) with short exponential
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
    """GET-oriented HTTP transport with per-request retry and politeness."""

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
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": self.DEFAULT_USER_AGENT})

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
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            time.sleep(random.uniform(*self.delay_range))
            try:
                response = self.session.get(
                    url,
                    params=params or None,
                    headers=spec.headers or None,
                    timeout=self.timeout,
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
            if response.status_code == 429 or response.status_code >= 500:
                last_error = TransientError(
                    f"HTTP {response.status_code} for {url} (attempt {attempt})"
                )
                time.sleep(min(60.0, 2.0**attempt))
                continue
            raise PermanentError(f"HTTP {response.status_code} for {url}")
        raise TransientError(f"Transport retries exhausted for {url}: {last_error}")
