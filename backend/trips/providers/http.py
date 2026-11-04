"""Shared outbound HTTP client with timeouts, bounded retries and per-host pacing.

All third-party calls go through ``request_json`` so every provider gets the same safety rules:

- strict connect/read timeouts (a slow upstream can't hang a worker);
- retries only on transient failures (timeouts, connection errors, 429, 5xx), with exponential
  backoff, honouring a short ``Retry-After``;
- a minimum interval between request starts per host, to respect public-API fair-use policies;
- a single typed ``UpstreamError`` so the API layer can map failures to a clean 502.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(connect=5.0, read=25.0, write=10.0, pool=5.0)
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RETRY_AFTER_S = 3.0


class UpstreamError(Exception):
    """A third-party request failed after retries (or returned unusable data)."""

    def __init__(self, service: str, message: str, status: int | None = None):
        super().__init__(f"{service}: {message}")
        self.service = service
        self.status = status


class HostPacer:
    """Ensures at least ``min_interval`` seconds between request *starts* to one host."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_allowed: dict[str, float] = {}

    def wait(self, host: str, min_interval: float) -> None:
        if min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next_allowed.get(host, 0.0))
            self._next_allowed[host] = start + min_interval
        delay = start - now
        if delay > 0:
            time.sleep(delay)


_pacer = HostPacer()
_client: httpx.Client | None = None
_client_lock = threading.Lock()


def get_client() -> httpx.Client:
    """Process-wide pooled client (thread-safe; httpx.Client may be shared across threads)."""
    global _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(
                timeout=TIMEOUT,
                headers={"User-Agent": settings.TRIPS["USER_AGENT"], "Accept": "application/json"},
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                follow_redirects=False,
            )
        return _client


def request_json(
    method: str,
    url: str,
    *,
    service: str,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    retries: int = 2,
    min_interval: float = 0.0,
) -> Any:
    """Perform a request and return the decoded JSON body, or raise ``UpstreamError``."""
    host = httpx.URL(url).host
    last_error = "unknown error"
    last_status: int | None = None
    for attempt in range(retries + 1):
        _pacer.wait(host, min_interval)
        try:
            resp = get_client().request(method, url, params=params, data=data)
        except httpx.TimeoutException:
            last_error, last_status = "timed out", None
        except httpx.TransportError as exc:
            last_error, last_status = f"connection error ({type(exc).__name__})", None
        else:
            if resp.status_code < 400:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise UpstreamError(service, "invalid JSON response", resp.status_code) from exc
            last_status = resp.status_code
            last_error = f"HTTP {resp.status_code}"
            if resp.status_code not in RETRY_STATUSES:
                # 4xx (other than 429) won't succeed on retry; let the provider interpret it.
                raise UpstreamError(service, _error_detail(resp), resp.status_code)
            if attempt < retries:
                time.sleep(_retry_after(resp) or 0.5 * 2**attempt)
                continue
        if attempt < retries:
            time.sleep(0.5 * 2**attempt)
        logger.warning("%s request failed (attempt %d): %s", service, attempt + 1, last_error)
    raise UpstreamError(service, last_error, last_status)


def _retry_after(resp: httpx.Response) -> float | None:
    try:
        return min(float(resp.headers.get("Retry-After", "")), MAX_RETRY_AFTER_S)
    except ValueError:
        return None


def _error_detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return f"HTTP {resp.status_code}"
    if isinstance(body, dict):
        for key in ("message", "reason", "error"):
            if isinstance(body.get(key), str):
                return f"HTTP {resp.status_code}: {body[key][:200]}"
    return f"HTTP {resp.status_code}"
