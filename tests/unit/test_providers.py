"""Connecteurs : analyse de réponses réelles enregistrées (tests/fixtures) et client HTTP."""

import json
from datetime import date

import httpx
import pytest
import respx

from research_lab.config import ProviderConfig, RetryConfig
from research_lab.providers.arxiv import ArxivProvider, build_search_query, parse_feed
from research_lab.providers.base import ProviderError
from research_lab.providers.openalex import OpenAlexProvider, build_filter, parse_work, rebuild_abstract
from research_lab.schemas.search import SearchQuery

ARXIV_URL = "https://export.arxiv.org/api/query"
OPENALEX_URL = "https://api.openalex.org"
NO_RETRY_DELAY = RetryConfig(max_attempts=3, backoff_seconds=0)


def _arxiv(page_size: int = 100) -> ArxivProvider:
    return ArxivProvider(ProviderConfig(base_url=ARXIV_URL, page_size=page_size), NO_RETRY_DELAY, sleep=lambda _: None)


def _openalex() -> OpenAlexProvider:
    return OpenAlexProvider(ProviderConfig(base_url=OPENALEX_URL), NO_RETRY_DELAY, sleep=lambda _: None)


# --- arXiv -------------------------------------------------------------------


def test_arxiv_query_syntax():
    query = SearchQuery(text='"AI governance" decentralized', date_from=date(2024, 1, 1), date_to=date(2025, 12, 31))
    assert build_search_query(query) == (
        'all:"AI governance" AND all:decentralized AND submittedDate:[202401010000 TO 202512312359]'
    )


def test_arxiv_query_rejects_unbalanced_quotes():
    with pytest.raises(ValueError):
        build_search_query(SearchQuery(text='"unclosed phrase'))


def test_parse_recorded_arxiv_feed(fixture_text):
    hits, total, warnings = parse_feed(fixture_text("arxiv_search.xml"))
    assert total == 199
    assert warnings == []
    assert [h.source_id for h in hits] == ["2504.15676", "2505.04136"]
    first = hits[0].metadata
    assert first.title.startswith("Trustworthy Decentralized Autonomous Machines")
    assert first.authors[:2] == ["Fernando Castillo", "Oscar Castillo"]
    assert first.published == date(2025, 4, 22)
    assert first.doi == "10.1109/icbc64466.2025.11185065"
    assert first.url == "https://arxiv.org/abs/2504.15676"
    assert "\n" not in first.abstract


def test_arxiv_error_entry_raises():
    feed = """<feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <id>http://arxiv.org/api/errors#incorrect_id_format</id><title>Error</title>
      <summary>incorrect id format</summary></entry></feed>"""
    with pytest.raises(ProviderError, match="incorrect id format"):
        parse_feed(feed)


@respx.mock
def test_arxiv_paginates_until_max_results(fixture_text):
    route = respx.get(ARXIV_URL).mock(return_value=httpx.Response(200, text=fixture_text("arxiv_search.xml")))
    result = _arxiv(page_size=2).search(SearchQuery(text="decentralized governance", max_results=4))
    assert route.call_count == 2
    assert [c.request.url.params["start"] for c in route.calls] == ["0", "2"]
    assert len(result.hits) == 4
    assert result.total_available == 199


# --- OpenAlex ----------------------------------------------------------------


def test_openalex_filter():
    query = SearchQuery(text="AI governance, privacy", date_from=date(2024, 1, 1))
    assert build_filter(query) == "title_and_abstract.search:AI governance  privacy,from_publication_date:2024-01-01"


def test_rebuild_abstract():
    assert rebuild_abstract({"world": [1], "Hello": [0], "again": [3], "hello": [2]}) == "Hello world hello again"
    assert rebuild_abstract(None) is None


def test_parse_recorded_openalex_works(fixture_text):
    works = json.loads(fixture_text("openalex_search.json"))["results"]
    hits = [parse_work(w)[0] for w in works]
    assert [h.source_id for h in hits] == ["W7128368514", "W4414632071", "W7208821528"]
    conference = hits[1].metadata
    # L'identifiant arXiv est déduit des localisations : c'est ce qui permet la déduplication.
    assert conference.arxiv_id == "2504.15676"
    assert conference.doi == "10.1109/icbc64466.2025.11185065"
    assert conference.venue == "IEEE International Conference on Blockchain and Cryptocurrency (ICBC)"
    assert conference.work_type == "conference-paper"
    assert hits[0].metadata.arxiv_id is None


def test_openalex_invalid_doi_is_dropped_with_warning():
    hit, warnings = parse_work({"id": "https://openalex.org/W1", "display_name": "T", "doi": "https://doi.org/garbage"})
    assert hit.metadata.doi is None
    assert "DOI invalide" in warnings[0]


@respx.mock
def test_openalex_follows_cursor_and_sends_credentials(fixture_text, monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "secret-key")
    page = json.loads(fixture_text("openalex_search.json"))
    first = {**page, "meta": {**page["meta"], "next_cursor": "abc"}}
    last = {**page, "meta": {**page["meta"], "next_cursor": None}}
    route = respx.get(f"{OPENALEX_URL}/works").mock(side_effect=[httpx.Response(200, json=first), httpx.Response(200, json=last)])
    result = _openalex().search(SearchQuery(text="decentralized autonomous machines", max_results=10))
    assert [c.request.url.params["cursor"] for c in route.calls] == ["*", "abc"]
    assert route.calls[0].request.url.params["api_key"] == "secret-key"
    assert len(result.hits) == 6


# --- Client HTTP -------------------------------------------------------------


@respx.mock
def test_transient_errors_are_retried(fixture_text):
    route = respx.get(ARXIV_URL).mock(
        side_effect=[httpx.Response(503), httpx.ConnectError("down"), httpx.Response(200, text=fixture_text("arxiv_search.xml"))]
    )
    result = _arxiv().search(SearchQuery(text="x", max_results=2))
    assert route.call_count == 3
    assert len(result.hits) == 2


@respx.mock
def test_persistent_errors_raise_after_max_attempts():
    route = respx.get(ARXIV_URL).mock(return_value=httpx.Response(503))
    with pytest.raises(ProviderError, match="3 tentatives"):
        _arxiv().search(SearchQuery(text="x"))
    assert route.call_count == 3


@respx.mock
def test_client_errors_are_not_retried():
    route = respx.get(ARXIV_URL).mock(return_value=httpx.Response(400))
    with pytest.raises(ProviderError, match="HTTP 400"):
        _arxiv().search(SearchQuery(text="x"))
    assert route.call_count == 1
