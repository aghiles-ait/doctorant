from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from research_lab.corpus import CorpusStatus, check_corpus, merge_hits
from research_lab.schemas.paper import Paper, PaperMetadata, Provenance, Source, SourceHit
from research_lab.schemas.search import SearchExecution, SearchQuery, SearchStatus

T0 = datetime(2026, 10, 26, tzinfo=UTC)


def _hit(source: Source, source_id: str, **meta) -> SourceHit:
    return SourceHit(source=source, source_id=source_id, metadata=PaperMetadata(**meta))


ARXIV_HIT = _hit(Source.ARXIV, "2504.15676", title="Trustworthy DAMs", arxiv_id="2504.15676", published=date(2025, 4, 22),
                 abstract="Preprint abstract")
OPENALEX_HIT = _hit(Source.OPENALEX, "W4414632071", title="Trustworthy DAMs", arxiv_id="2504.15676",
                    openalex_id="W4414632071", doi="10.1109/icbc64466.2025.11185065", venue="ICBC",
                    abstract="Published abstract")
OTHER_HIT = _hit(Source.OPENALEX, "W1", title="Another paper", openalex_id="W1")


def test_cross_source_duplicates_are_merged_and_enriched():
    papers: list[Paper] = []
    report = merge_hits(papers, [ARXIV_HIT, OPENALEX_HIT, OTHER_HIT], "SEARCH-001", "q", T0)
    assert report.new_paper_ids == ["PAPER-001", "PAPER-002"]
    merged = papers[0]
    assert {p.source for p in merged.provenance} == {Source.ARXIV, Source.OPENALEX}
    assert merged.doi == "10.1109/icbc64466.2025.11185065"  # complété par OpenAlex
    assert merged.abstract == "Preprint abstract"  # la première source fait foi
    assert merged.venue == "ICBC"


def test_rerun_keeps_ids_and_adds_provenance():
    papers: list[Paper] = []
    merge_hits(papers, [ARXIV_HIT, OTHER_HIT], "SEARCH-001", "q", T0)
    report = merge_hits(papers, [OTHER_HIT, OPENALEX_HIT], "SEARCH-002", "q", T0)
    assert report.new_paper_ids == []
    assert report.matched_paper_ids == ["PAPER-002", "PAPER-001"]
    assert [p.paper_id for p in papers] == ["PAPER-001", "PAPER-002"]
    assert [p.search_id for p in papers[1].provenance] == ["SEARCH-001", "SEARCH-002"]


def test_new_ids_continue_after_highest_existing():
    papers: list[Paper] = []
    merge_hits(papers, [ARXIV_HIT, OTHER_HIT], "SEARCH-001", "q", T0)
    papers.pop(0)  # PAPER-001 retiré : son identifiant ne doit pas être réattribué
    merge_hits(papers, [_hit(Source.OPENALEX, "W2", title="Third", openalex_id="W2")], "SEARCH-002", "q", T0)
    assert [p.paper_id for p in papers] == ["PAPER-002", "PAPER-003"]


def test_paper_without_identifier_or_provenance_is_rejected():
    prov = Provenance(source=Source.ARXIV, source_id="x", search_id="SEARCH-001", query="q", retrieved_at=T0)
    with pytest.raises(ValidationError, match="aucun identifiant externe"):
        Paper(paper_id="PAPER-001", title="T", provenance=[prov])
    with pytest.raises(ValidationError):
        Paper(paper_id="PAPER-001", title="T", doi="10.1000/x", provenance=[])


def _log(*search_ids: str) -> list[SearchExecution]:
    return [
        SearchExecution(
            search_id=sid, project_id="p", query=SearchQuery(text="q"), sources=[Source.ARXIV], started_at=T0,
            finished_at=T0, status=SearchStatus.COMPLETED, results=[], tool_version="0", config_hash="h",
        )
        for sid in search_ids
    ]


def test_check_corpus_statuses():
    papers: list[Paper] = []
    merge_hits(papers, [ARXIV_HIT, OTHER_HIT], "SEARCH-001", "q", T0)
    assert check_corpus(papers, _log("SEARCH-001"), min_corpus_size=2).status == CorpusStatus.OK
    assert check_corpus(papers, _log("SEARCH-001"), min_corpus_size=3).status == CorpusStatus.NEEDS_MORE_RESEARCH

    orphan = check_corpus(papers, _log(), min_corpus_size=0)
    assert orphan.status == CorpusStatus.BLOCKED
    assert "absente de search-log.json" in orphan.errors[0]


def test_check_corpus_detects_duplicate_identifiers():
    papers: list[Paper] = []
    merge_hits(papers, [ARXIV_HIT, OTHER_HIT], "SEARCH-001", "q", T0)
    papers[1].arxiv_id = papers[0].arxiv_id
    result = check_corpus(papers, _log("SEARCH-001"), min_corpus_size=0)
    assert result.status == CorpusStatus.BLOCKED
    assert any("Doublon arxiv_id" in e for e in result.errors)
