"""Appels réels aux APIs. Lancer avec : pytest -m network"""

from datetime import date

import pytest

from research_lab.config import load_settings
from research_lab.fulltext import FulltextFetcher
from research_lab.providers import build_providers
from research_lab.schemas.evidence import FulltextStatus
from research_lab.schemas.paper import Paper, Source
from research_lab.schemas.search import SearchQuery
from research_lab.validation.evidence import find_quote_pages

pytestmark = pytest.mark.network

QUERY = SearchQuery(text="decentralized governance", date_from=date(2024, 1, 1), date_to=date(2025, 12, 31), max_results=5)


@pytest.mark.parametrize("source", [Source.ARXIV, Source.OPENALEX])
def test_live_search_returns_identified_papers(source):
    [provider] = build_providers(load_settings(), [source])
    result = provider.search(QUERY)
    assert result.total_available and result.total_available > 0
    assert 0 < len(result.hits) <= 5
    for hit in result.hits:
        assert hit.metadata.has_identifier()
        assert hit.metadata.title
        if hit.metadata.published:
            assert date(2024, 1, 1) <= hit.metadata.published <= date(2025, 12, 31)


def test_live_arxiv_fulltext_and_quote_lookup():
    """Vrai PDF arXiv : texte extrait page par page, extrait du résumé retrouvé page 1."""
    paper = Paper(
        paper_id="PAPER-001", title="An Adaptive Responsible AI Governance Framework for Decentralized Organizations",
        arxiv_id="2510.03368",
        provenance=[{"source": "arxiv", "source_id": "2510.03368", "search_id": "SEARCH-001", "query": "q",
                     "retrieved_at": "2026-11-03T00:00:00Z"}],
    )
    outcome = FulltextFetcher(load_settings()).fetch(paper)
    assert outcome.record.status == FulltextStatus.AVAILABLE, outcome.record.error
    assert outcome.record.page_count > 5
    # Dans le PDF, « Respon-sible » est coupé en fin de ligne : la comparaison doit le tolérer.
    assert find_quote_pages("assessment challenges of Responsible AI (RAI) governance efforts", outcome.pages) == [1]
