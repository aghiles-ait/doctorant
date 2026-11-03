"""Connecteur OpenAlex (https://docs.openalex.org/api-entities/works)."""

import os
import time
from collections.abc import Callable
from datetime import date

from research_lab.config import ProviderConfig, RetryConfig
from research_lab.providers.base import HttpClient, ProviderError, ProviderResult
from research_lab.schemas.paper import PaperMetadata, Source, SourceHit
from research_lab.schemas.search import SearchQuery
from research_lab.validation.references import (
    arxiv_id_from_doi,
    normalize_arxiv_id,
    normalize_doi,
    normalize_openalex_id,
)

_SELECT = "id,doi,display_name,publication_date,authorships,abstract_inverted_index,primary_location,locations,type"


def build_filter(query: SearchQuery) -> str:
    """Recherche dans le titre et le résumé (et non le texte intégral), bornée par dates."""
    parts = [f"title_and_abstract.search:{query.text.replace(',', ' ')}"]
    if query.date_from:
        parts.append(f"from_publication_date:{query.date_from.isoformat()}")
    if query.date_to:
        parts.append(f"to_publication_date:{query.date_to.isoformat()}")
    return ",".join(parts)


def rebuild_abstract(inverted_index: dict[str, list[int]] | None) -> str | None:
    """OpenAlex fournit le résumé sous forme d'index inversé mot -> positions."""
    if not inverted_index:
        return None
    positions = sorted((pos, word) for word, indexes in inverted_index.items() for pos in indexes)
    return " ".join(word for _, word in positions)


def _arxiv_id(work: dict, doi: str | None) -> str | None:
    if arxiv_id := arxiv_id_from_doi(doi):
        return arxiv_id
    for location in work.get("locations") or []:
        for key in ("landing_page_url", "pdf_url"):
            url = location.get(key) or ""
            if "arxiv.org/" in url and (arxiv_id := normalize_arxiv_id(url)):
                return arxiv_id
            if (arxiv_id := arxiv_id_from_doi(normalize_doi(url))) is not None:
                return arxiv_id
    return None


def parse_work(work: dict) -> tuple[SourceHit | None, list[str]]:
    openalex_id = normalize_openalex_id(work.get("id"))
    title = (work.get("display_name") or "").strip()
    if not openalex_id or not title:
        return None, [f"Œuvre OpenAlex ignorée (identifiant ou titre manquant) : {work.get('id')!r}"]
    warnings: list[str] = []
    raw_doi = work.get("doi")
    doi = normalize_doi(raw_doi)
    if raw_doi and not doi:
        warnings.append(f"OpenAlex {openalex_id} : DOI invalide ignoré ({raw_doi!r})")
    primary = work.get("primary_location") or {}
    published = work.get("publication_date")
    metadata = PaperMetadata(
        title=" ".join(title.split()),
        authors=[
            name
            for authorship in work.get("authorships") or []
            if (name := (authorship.get("author") or {}).get("display_name"))
        ],
        abstract=rebuild_abstract(work.get("abstract_inverted_index")),
        published=date.fromisoformat(published) if published else None,
        venue=(primary.get("source") or {}).get("display_name"),
        work_type=work.get("type"),
        doi=doi,
        arxiv_id=_arxiv_id(work, doi),
        openalex_id=openalex_id,
        url=primary.get("landing_page_url") or f"https://openalex.org/{openalex_id}",
    )
    return SourceHit(source=Source.OPENALEX, source_id=openalex_id, metadata=metadata), warnings


class OpenAlexProvider:
    source = Source.OPENALEX

    def __init__(self, config: ProviderConfig, retry: RetryConfig, sleep: Callable[[float], None] = time.sleep) -> None:
        self._config = config
        auth = {}
        if api_key := os.environ.get("OPENALEX_API_KEY"):
            auth["api_key"] = api_key
        if mailto := os.environ.get("OPENALEX_MAILTO"):
            auth["mailto"] = mailto
        self._http = HttpClient(config, retry, sleep=sleep, params=auth)

    def search(self, query: SearchQuery) -> ProviderResult:
        filter_ = build_filter(query)
        hits: list[SourceHit] = []
        warnings: list[str] = []
        total: int | None = None
        cursor = "*"
        while cursor and len(hits) < query.max_results:
            response = self._http.get(
                f"{self._config.base_url}/works",
                params={
                    "filter": filter_,
                    "select": _SELECT,
                    "per-page": min(self._config.page_size, query.max_results - len(hits)),
                    "cursor": cursor,
                },
            )
            try:
                payload = response.json()
                meta, results = payload["meta"], payload["results"]
            except (ValueError, KeyError, TypeError) as exc:
                raise ProviderError(f"Réponse OpenAlex inattendue : {exc}") from exc
            total = meta.get("count")
            cursor = meta.get("next_cursor")
            for work in results:
                hit, work_warnings = parse_work(work)
                warnings.extend(work_warnings)
                if hit:
                    hits.append(hit)
            if not results:
                break
        return ProviderResult(hits=hits[: query.max_results], provider_query=filter_, total_available=total, warnings=warnings)
