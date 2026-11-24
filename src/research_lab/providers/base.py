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


def parse_retry_after(value: str | None) -> float | None:
    """Délai `Retry-After` en secondes (la forme date HTTP est ignorée : on retombe sur les délais configurés)."""
    try:
        seconds = float(value) if value is not None else None
    except ValueError:
        return None
    return seconds if seconds is not None and seconds >= 0 else None


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
        attempts: list[str] = []
        for attempt in range(1, self._retry.max_attempts + 1):
            self._throttle()
            retry_after = None
            try:
                response = self._client.get(url, params=params)
            except httpx.TransportError as exc:
                attempts.append(f"{type(exc).__name__}: {exc}")
            else:
                if response.status_code not in _RETRYABLE_STATUS:
                    if response.is_error:
                        raise ProviderError(f"HTTP {response.status_code} sur {response.url}")
                    return response
                attempts.append(f"HTTP {response.status_code} sur {response.url}")
                retry_after = parse_retry_after(response.headers.get("retry-after"))
            if attempt < self._retry.max_attempts:
                self._sleep(self._retry.delay(attempt, retry_after))
        detail = " ; ".join(f"{i}) {a}" for i, a in enumerate(attempts, start=1))
        raise ProviderError(f"Échec après {self._retry.max_attempts} tentatives : {detail}")

    def _throttle(self) -> None:
        now = time.monotonic()
        if self._last_request is not None:
            wait = self._config.min_interval_seconds - (now - self._last_request)
            if wait > 0:
                self._sleep(wait)
        self._last_request = time.monotonic()
