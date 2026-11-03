"""Interface commune des connecteurs et client HTTP avec relances."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from research_lab import __version__
from research_lab.config import ProviderConfig, RetryConfig
from research_lab.schemas.paper import Source, SourceHit
from research_lab.schemas.search import SearchQuery

USER_AGENT = f"ai-research-doctorant/{__version__}"
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class ProviderError(Exception):
    """Échec d'une source après épuisement des relances."""


@dataclass
class ProviderResult:
    hits: list[SourceHit]
    provider_query: str
    total_available: int | None
    warnings: list[str] = field(default_factory=list)


class Provider(Protocol):
    source: Source

    def search(self, query: SearchQuery) -> ProviderResult: ...


class HttpClient:
    """Client HTTP qui respecte un intervalle minimal entre requêtes et relance les erreurs transitoires."""

    def __init__(
        self,
        config: ProviderConfig,
        retry: RetryConfig,
        sleep: Callable[[float], None] = time.sleep,
        params: dict[str, str] | None = None,
    ) -> None:
        self._config = config
        self._retry = retry
        self._sleep = sleep
        self._last_request: float | None = None
        self._client = httpx.Client(
            timeout=config.timeout_seconds,
            headers={"User-Agent": USER_AGENT},
            params=params or {},
            follow_redirects=True,
        )

    def get(self, url: str, params: dict[str, str | int]) -> httpx.Response:
        last_error = ""
        for attempt in range(1, self._retry.max_attempts + 1):
            self._throttle()
            try:
                response = self._client.get(url, params=params)
            except httpx.TransportError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code not in _RETRYABLE_STATUS:
                    if response.is_error:
                        raise ProviderError(f"HTTP {response.status_code} sur {response.url}")
                    return response
                last_error = f"HTTP {response.status_code} sur {response.url}"
            if attempt < self._retry.max_attempts:
                self._sleep(self._retry.backoff_seconds * 2 ** (attempt - 1))
        raise ProviderError(f"Échec après {self._retry.max_attempts} tentatives : {last_error}")

    def _throttle(self) -> None:
        now = time.monotonic()
        if self._last_request is not None:
            wait = self._config.min_interval_seconds - (now - self._last_request)
            if wait > 0:
                self._sleep(wait)
        self._last_request = time.monotonic()
