"""Appels réels aux APIs. Lancer avec : pytest -m network"""

from datetime import date

import pytest

from research_lab.config import load_settings
from research_lab.providers import build_providers
from research_lab.schemas.paper import Source
from research_lab.schemas.search import SearchQuery

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
