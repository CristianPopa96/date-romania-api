"""HTTP client every collector uses: identifies us, waits between calls, retries with backoff."""

import logging
import time
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

from date_romania.config import get_settings

log = logging.getLogger(__name__)

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class PoliteClient:
    """Wraps httpx with a minimum interval per host and retries on transient failures."""

    def __init__(
        self,
        min_interval: float = 1.0,
        retries: int = 4,
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = httpx.Client(
            headers={"User-Agent": get_settings().http_user_agent},
            timeout=timeout,
            transport=transport,
        )
        self._min_interval = min_interval
        self._retries = retries
        self._sleep = sleep
        self._clock = clock
        self._last_call: dict[str, float] = {}

    def __enter__(self) -> "PoliteClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self._client.close()

    def _wait_for_turn(self, host: str) -> None:
        last = self._last_call.get(host)
        if last is not None:
            remaining = self._min_interval - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last_call[host] = self._clock()

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Send one request; raises httpx.HTTPError once the retries are used up."""
        host = urlsplit(url).netloc
        for attempt in range(self._retries + 1):
            self._wait_for_turn(host)
            try:
                response = self._client.request(method, url, **kwargs)
                if response.status_code not in RETRY_STATUSES:
                    response.raise_for_status()
                    return response
                problem = f"HTTP {response.status_code}"
            except httpx.TransportError as exc:
                problem = repr(exc)
            if attempt == self._retries:
                raise httpx.HTTPError(f"{method} {url} failed after {attempt + 1} tries: {problem}")
            delay = 2.0 * 2**attempt
            log.warning("%s %s: %s, retrying in %.0fs", method, url, problem, delay)
            self._sleep(delay)
        raise AssertionError("unreachable")
