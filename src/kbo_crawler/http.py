"""Small injectable HTTP client with bounded retries and rate limiting."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Mapping
from typing import Any

import requests

from .errors import SourceError


class HttpClient:
    """Requests-backed client used by source adapters.

    The client deliberately exposes only text and JSON operations so tests can
    replace it with a tiny fake implementing the same methods.
    """

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout: float = 20.0,
        requests_per_second: float = 2.0,
        max_attempts: int = 3,
        user_agent: str = "KBO-Statistics-Analysis/0.1",
    ) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_attempts = max(1, max_attempts)
        self.min_interval = (
            0.0 if requests_per_second <= 0 else 1.0 / requests_per_second
        )
        self.default_headers = {"User-Agent": user_agent}
        self._last_request_at = 0.0
        self._rate_lock = threading.Lock()

    def _wait_for_slot(self) -> None:
        with self._rate_lock:
            elapsed = time.monotonic() - self._last_request_at
            delay = self.min_interval - elapsed
            if delay > 0:
                time.sleep(delay)
            self._last_request_at = time.monotonic()

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> requests.Response:
        merged_headers = {**self.default_headers, **dict(headers or {})}
        last_error: Exception | None = None

        for attempt in range(1, self.max_attempts + 1):
            self._wait_for_slot()
            try:
                response = self.session.request(
                    method,
                    url,
                    params=params,
                    data=data,
                    headers=merged_headers,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt == self.max_attempts:
                    break
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue

            if response.status_code == 429 or response.status_code >= 500:
                last_error = SourceError(
                    f"{method.upper()} {url} returned HTTP {response.status_code}"
                )
                if attempt < self.max_attempts:
                    time.sleep(0.5 * (2 ** (attempt - 1)))
                    continue

            if response.status_code >= 400:
                raise SourceError(
                    f"{method.upper()} {url} returned HTTP {response.status_code}"
                )
            return response

        raise SourceError(f"{method.upper()} {url} failed after retries") from last_error

    def get_text(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> str:
        response = self.request("GET", url, params=params, headers=headers)
        return response.text

    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        response = self.request("GET", url, params=params, headers=headers)
        return self._decode_json(response, url)

    def post_json(
        self,
        url: str,
        *,
        data: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        response = self.request("POST", url, data=data, headers=headers)
        return self._decode_json(response, url)

    @staticmethod
    def _decode_json(response: requests.Response, url: str) -> Any:
        content_type = response.headers.get("Content-Type", "").lower()
        body = response.text.lstrip("\ufeff \t\r\n")
        if "html" in content_type or body.startswith(("<!DOCTYPE", "<html", "<!--")):
            raise SourceError(f"{url} returned HTML instead of JSON")
        try:
            return response.json()
        except (requests.JSONDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise SourceError(f"{url} returned invalid JSON") from exc
