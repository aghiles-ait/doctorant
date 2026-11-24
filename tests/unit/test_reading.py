"""Leçons de l'agent researcher : lecture vérifiable, recherches plafonnées, recherches contradictoires vides."""

from datetime import UTC, datetime

import pytest
from test_gaps import KNOWN_HIT, _contradictory_search, _draft, analysis  # noqa: F401 — fixtures partagées
from test_review import _evidence, fetched, fetcher, included, repo, settings, with_fulltext  # noqa: F401

from research_lab.corpus import CorpusStatus, capped_searches, check_corpus
from research_lab.gaps import GapError, add_gap, revise_gap
from research_lab.reading import (
    check_reading,
    coverage,
    format_ranges,
    parse_page_range,
    references_start,
    select_pages,
)
from research_lab.review import ReviewError
from research_lab.schemas.paper import Source
from research_lab.schemas.search import SearchExecution, SearchQuery, SearchStatus, SourceResult, SourceStatus
from research_lab.storage.repositories import read_pages
from research_lab.validation.gaps import useful_searches
from research_lab.workflow.state import ResearchState
from research_lab.workflow.transitions import TransitionError

T0 = datetime(2026, 11, 24, tzinfo=UTC)


# --- Couverture de lecture -------------------------------------------------------------


def test_references_start_ignores_early_mentions():
    pages = ["Contents\nReferences", "Intro", "Method", "Results", "Conclusion\n7 References\n[1] A.", "[2] B."]
    assert references_start(pages) == 5
    assert references_start(["Intro", "Body"]) is None
    assert references_start(["Intro", "Body", "VIII. REFERENCES", "[1] x"]) == 3


def test_coverage_requires_main_text_up_to_references():
    pages = ["Title", "Method", "Results", "References\n[1] A.", "Appendix A"]
    c = coverage("PAPER-001", pages, {1, 2})
    assert (c.main_end, c.references_from, c.unread_main, c.complete) == (4, 4, [3, 4], False)
    assert "2/4 pages du texte principal lues (non lues : 3-4)" in c.summary()
    assert coverage("PAPER-001", pages, {1, 2, 3, 4}).complete  # annexes facultatives
    errors = check_reading([c], "p")
    assert errors and "--pages 3-4" in errors[0]


def test_format_and_parse_ranges():
    assert format_ranges([1, 2, 3, 5, 7, 8]) == "1-3, 5, 7-8"
    assert parse_page_range("3-99", 10) == (3, 10)
    assert parse_page_range("4", 10) == (4, 4)
    for bad in ("0", "5-3", "x", "11"):
        with pytest.raises(ValueError):
            parse_page_range(bad, 10)


def test_select_pages_respects_the_size_cap():
    pages = ["a" * 6000, "b" * 6000, "c" * 6000]
    assert select_pages(pages, 1, 3, 15000) == [1, 2]
    assert select_pages(["x" * 20000], 1, 1, 15000) == [1]  # une page seule est toujours affichée


def test_evidence_requires_the_page_to_have_been_shown(fetched, settings):
    with pytest.raises(ReviewError, match="jamais affichée"):
        _evidence(fetched, settings)
    _, digest = read_pages(fetched.db, settings.papers_dir, "PAPER-001")
    fetched.record_page_reads("PAPER-001", [1], digest)
    assert _evidence(fetched, settings).evidence_id == "EV-001"


def test_transition_to_gap_analysis_requires_full_reading(fetched, settings):
    _, digest = read_pages(fetched.db, settings.papers_dir, "PAPER-001")
    fetched.record_page_reads("PAPER-001", [1], digest)
    _evidence(fetched, settings)
    (fetched.dir / "literature-review.md").write_text("Responsabilité [PAPER-001, EV-001].\n")
    assert fetched.reading_coverage()["PAPER-001"].unread_main == [2]
    with pytest.raises(TransitionError, match="lecture incomplète : PAPER-001"):
        fetched.transition(ResearchState.GAP_ANALYSIS, actor="alice", policy=settings.policy)
    lenient = settings.policy.model_copy(update={"require_full_reading": False})
    fetched.transition(ResearchState.GAP_ANALYSIS, actor="alice", policy=lenient)


def test_reads_are_recorded_once_per_page(with_fulltext, settings):
    _, digest = read_pages(with_fulltext.db, settings.papers_dir, "PAPER-001")
    with_fulltext.record_page_reads("PAPER-001", [1, 1, 2], digest)
    assert with_fulltext.pages_read("PAPER-001", digest) == {1, 2}
    assert with_fulltext.pages_read("PAPER-001", "sha256:autre-extraction") == set()


# --- Recherches plafonnées -------------------------------------------------------------


def _execution(search_id, text, hits, total, gap_id=None):
    return SearchExecution(
        search_id=search_id, project_id="p", gap_id=gap_id, query=SearchQuery(text=text), sources=[Source.ARXIV],
        started_at=T0, finished_at=T0, status=SearchStatus.COMPLETED, tool_version="0", config_hash="h",
        results=[SourceResult(source=Source.ARXIV, status=SourceStatus.OK, hits=hits, total_available=total)],
    )


def test_capped_searches_must_be_completed_or_reported():
    log = [_execution("SEARCH-001", "dao", 25, 97), _execution("SEARCH-002", "governance", 25, 1537),
           _execution("SEARCH-003", "agents", 10, 10), _execution("SEARCH-004", "x", 0, 50, gap_id="GAP-001")]
    to_complete, too_broad = capped_searches(log, 300)
    assert len(to_complete) == 1 and "SEARCH-001" in to_complete[0] and "--max-results 97" in to_complete[0]
    assert len(too_broad) == 1 and "SEARCH-002" in too_broad[0]
    assert check_corpus([], log, 0, 300).status == CorpusStatus.NEEDS_MORE_RESEARCH
    assert check_corpus([], log, 0).status == CorpusStatus.OK  # sans politique : ancien comportement
    # La même requête relancée sans plafond lève l'obligation.
    rerun = [*log, _execution("SEARCH-005", "dao", 97, 97)]
    assert capped_searches(rerun, 300)[0] == []
    assert check_corpus([], rerun, 0, 300).status == CorpusStatus.OK


# --- Recherches contradictoires vides ----------------------------------------------------


def test_contradictory_search_without_results_does_not_count(analysis, settings):
    add_gap(analysis, settings, _draft(), "", "alice")
    _contradictory_search(analysis, settings, "GAP-001", hits=[])
    assert useful_searches(analysis.searches_by_gap()["GAP-001"]) == []
    supported = _draft(status="supported", novelty_assessment="not_found_in_searches")
    with pytest.raises(GapError, match="ayant ramené des résultats"):
        revise_gap(analysis, settings, "GAP-001", supported, "rien trouvé", "alice")
    _contradictory_search(analysis, settings, "GAP-001", hits=[KNOWN_HIT])
    assert revise_gap(analysis, settings, "GAP-001", supported, "seulement PAPER-002", "alice").status == "supported"
