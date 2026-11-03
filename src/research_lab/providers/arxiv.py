"""Connecteur arXiv (API Atom : https://info.arxiv.org/help/api/user-manual.html)."""

import shlex
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import date, datetime

from research_lab.config import ProviderConfig, RetryConfig
from research_lab.providers.base import HttpClient, ProviderError, ProviderResult
from research_lab.schemas.paper import PaperMetadata, Source, SourceHit
from research_lab.schemas.search import SearchQuery
from research_lab.validation.references import normalize_arxiv_id, normalize_doi

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}


def build_search_query(query: SearchQuery) -> str:
    """Traduit une requête par mots-clés en syntaxe arXiv.

    Chaque mot (ou "expression entre guillemets") devient un terme `all:` combiné par AND.
    """
    terms = []
    for token in shlex.split(query.text):
        terms.append(f'all:"{token}"' if " " in token else f"all:{token}")
    search = " AND ".join(terms)
    if query.date_from or query.date_to:
        start = (query.date_from or date(1991, 1, 1)).strftime("%Y%m%d") + "0000"
        end = (query.date_to or date.today()).strftime("%Y%m%d") + "2359"
        search += f" AND submittedDate:[{start} TO {end}]"
    return search


def _text(element: ET.Element, path: str) -> str | None:
    found = element.find(path, _NS)
    if found is None or found.text is None:
        return None
    return " ".join(found.text.split())


def parse_feed(xml: str) -> tuple[list[SourceHit], int | None, list[str]]:
    """Analyse un flux Atom arXiv. Renvoie (résultats, total disponible, avertissements)."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ProviderError(f"Réponse arXiv illisible : {exc}") from exc

    total_text = _text(root, "opensearch:totalResults")
    total = int(total_text) if total_text else None
    hits: list[SourceHit] = []
    warnings: list[str] = []

    for entry in root.findall("atom:entry", _NS):
        entry_id = _text(entry, "atom:id") or ""
        # arXiv signale les requêtes invalides par une entrée « Error ».
        if _text(entry, "atom:title") == "Error":
            raise ProviderError(f"Erreur arXiv : {_text(entry, 'atom:summary')}")
        arxiv_id = normalize_arxiv_id(entry_id)
        title = _text(entry, "atom:title")
        if not arxiv_id or not title:
            warnings.append(f"Entrée arXiv ignorée (identifiant ou titre manquant) : {entry_id!r}")
            continue
        raw_doi = _text(entry, "arxiv:doi")
        doi = normalize_doi(raw_doi)
        if raw_doi and not doi:
            warnings.append(f"arXiv {arxiv_id} : DOI invalide ignoré ({raw_doi!r})")
        published = _text(entry, "atom:published")
        metadata = PaperMetadata(
            title=title,
            authors=[name for a in entry.findall("atom:author", _NS) if (name := _text(a, "atom:name"))],
            abstract=_text(entry, "atom:summary"),
            published=datetime.fromisoformat(published).date() if published else None,
            venue=_text(entry, "arxiv:journal_ref"),
            work_type="preprint",
            doi=doi,
            arxiv_id=arxiv_id,
            url=f"https://arxiv.org/abs/{arxiv_id}",
        )
        hits.append(SourceHit(source=Source.ARXIV, source_id=arxiv_id, metadata=metadata))
    return hits, total, warnings


class ArxivProvider:
    source = Source.ARXIV

    def __init__(self, config: ProviderConfig, retry: RetryConfig, sleep: Callable[[float], None] = time.sleep) -> None:
        self._config = config
        self._http = HttpClient(config, retry, sleep=sleep)

    def search(self, query: SearchQuery) -> ProviderResult:
        search_query = build_search_query(query)
        hits: list[SourceHit] = []
        warnings: list[str] = []
        total: int | None = None
        start = 0
        while len(hits) < query.max_results:
            page_size = min(self._config.page_size, query.max_results - len(hits))
            response = self._http.get(
                self._config.base_url,
                params={
                    "search_query": search_query,
                    "start": start,
                    "max_results": page_size,
                    "sortBy": "relevance",
                    "sortOrder": "descending",
                },
            )
            page, total, page_warnings = parse_feed(response.text)
            hits.extend(page)
            warnings.extend(page_warnings)
            start += page_size
            if len(page) < page_size or (total is not None and start >= total):
                break
        return ProviderResult(hits=hits[: query.max_results], provider_query=search_query, total_available=total, warnings=warnings)
