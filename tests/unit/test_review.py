"""Étape 2b : tri, texte intégral, preuves vérifiées, contrôle de l'état de l'art, transitions."""

import sqlite3
from datetime import UTC, date, datetime

import httpx
import pytest
import respx
from conftest import make_pdf

from research_lab.config import load_settings
from research_lab.corpus import merge_hits
from research_lab.fulltext import FulltextFetcher
from research_lab.review import ReviewError, add_evidence, decide, fetch_fulltexts, withdraw_evidence
from research_lab.schemas.evidence import EvidenceType, FulltextStatus
from research_lab.schemas.paper import PaperMetadata, PaperStatus, Source, SourceHit
from research_lab.schemas.search import SearchExecution, SearchQuery, SearchStatus
from research_lab.storage.database import Database
from research_lab.storage.repositories import (
    FulltextTampered,
    ProjectRepository,
    load_all_papers,
    load_fulltext,
    pages_path,
)
from research_lab.validation.evidence import find_quote_pages, match_key, quote_in
from research_lab.validation.outputs import check_literature_review
from research_lab.workflow.state import ResearchState
from research_lab.workflow.transitions import TransitionError

T0 = datetime(2026, 11, 3, tzinfo=UTC)
ARXIV_PDF = "https://export.arxiv.org/pdf/2510.03368"
PAGE_1 = "Adaptive governance\nOur assessment reveals inconsistent accoun-\ntability in risk oversight across business units."
PAGE_2 = "Results\nCentral coordination balanced with local autonomy reduced conflicts by 30 percent."
ABSTRACT = "We propose the ARGO framework that balances central coordination with local autonomy."


# --- Comparaison des extraits ----------------------------------------------------------


def test_match_key_tolerates_pdf_artefacts():
    assert match_key("Respon-\nsible ﬁnal J´er´emy") == match_key("Responsible final Jérémy")
    assert match_key("decision-\nmaking") == match_key("decision-making")


def test_quote_matching():
    assert quote_in("inconsistent accountability in risk oversight", PAGE_1)
    assert not quote_in("consistent accountability everywhere", PAGE_1)
    assert find_quote_pages("local autonomy reduced conflicts", [PAGE_1, PAGE_2]) == [2]


# --- Projet de test à l'état LITERATURE_REVIEW ------------------------------------------


@pytest.fixture
def settings(lab_root):
    return load_settings(lab_root)


@pytest.fixture
def repo(settings) -> ProjectRepository:
    repo = ProjectRepository(Database(settings.db_path), settings.projects_dir, "alpha")
    repo.create("Decentralized AI governance", actor="alice")
    policy = settings.policy.model_copy(update={"min_corpus_size": 0})
    repo.transition(ResearchState.SCOPING, actor="alice", policy=policy)
    repo.scope_file.write_text("# Scope\nGouvernance décentralisée de l'IA.\n")
    repo.transition(ResearchState.LITERATURE_SEARCH, actor="alice", policy=policy)
    hits = [
        SourceHit(source=Source.ARXIV, source_id="2510.03368", metadata=PaperMetadata(
            title="Adaptive RAI Governance", arxiv_id="2510.03368", abstract=ABSTRACT, published=date(2025, 10, 3))),
        SourceHit(source=Source.OPENALEX, source_id="W1", metadata=PaperMetadata(
            title="Closed access paper", openalex_id="W1", abstract="An abstract about something else entirely.")),
        SourceHit(source=Source.OPENALEX, source_id="W2", metadata=PaperMetadata(title="Off topic", openalex_id="W2")),
    ]
    papers = load_all_papers(repo.db)
    report = merge_hits(papers, hits, "SEARCH-001", "q", T0)
    repo.record_search(
        SearchExecution(search_id="SEARCH-001", project_id="alpha", query=SearchQuery(text="q"),
                        sources=[Source.ARXIV, Source.OPENALEX], started_at=T0, finished_at=T0,
                        status=SearchStatus.COMPLETED, results=[], tool_version="0", config_hash="h"),
        [p for p in papers if p.paper_id in report.touched_paper_ids],
    )
    repo.transition(ResearchState.LITERATURE_REVIEW, actor="alice", policy=policy)
    return repo


@pytest.fixture
def fetcher(settings):
    return FulltextFetcher(settings, sleep=lambda _: None)


@pytest.fixture
def included(repo):
    decide(repo, "PAPER-001", PaperStatus.INCLUDED, "Cadre de gouvernance décentralisée", "alice")
    decide(repo, "PAPER-002", PaperStatus.INCLUDED, "Pertinent", "alice")
    decide(repo, "PAPER-003", PaperStatus.EXCLUDED, "Hors sujet", "alice")
    return repo


@pytest.fixture
def with_fulltext(included, settings, fetcher):
    with respx.mock:
        respx.get(ARXIV_PDF).mock(return_value=httpx.Response(200, content=make_pdf([PAGE_1, PAGE_2])))
        respx.get("https://api.openalex.org/works/W1").mock(
            return_value=httpx.Response(200, json={"best_oa_location": None, "locations": []}))
        list(fetch_fulltexts(included, settings, fetcher))
    return included


def _evidence(repo, settings, **kwargs):
    args = {"paper_id": "PAPER-001", "claim": "La responsabilité est incohérente", "evidence_type": EvidenceType.EMPIRICAL_RESULT,
            "quote": "inconsistent accountability in risk oversight", "page": 1, "actor": "alice"} | kwargs
    return add_evidence(repo, settings, **args)


# --- Tri ---------------------------------------------------------------------------------


def test_screening_updates_status_and_keeps_history(included):
    included_ids = [p.paper_id for p in included.load_papers() if p.status == PaperStatus.INCLUDED]
    assert included_ids == ["PAPER-001", "PAPER-002"]
    decide(included, "PAPER-003", PaperStatus.INCLUDED, "Relecture : finalement pertinent", "alice")
    history = [(d.paper_id, d.decision) for d in included.load_decisions()]
    assert history[-2:] == [("PAPER-003", PaperStatus.EXCLUDED), ("PAPER-003", PaperStatus.INCLUDED)]


def test_screening_requires_literature_review_state(settings):
    repo = ProjectRepository(Database(settings.db_path), settings.projects_dir, "beta")
    repo.create("x", actor="alice")
    with pytest.raises(ReviewError, match="LITERATURE_REVIEW"):
        decide(repo, "PAPER-001", PaperStatus.INCLUDED, "r", "alice")


def test_cannot_exclude_paper_with_active_evidence(with_fulltext, settings):
    _evidence(with_fulltext, settings)
    with pytest.raises(ReviewError, match="EV-001"):
        decide(with_fulltext, "PAPER-001", PaperStatus.EXCLUDED, "changement d'avis", "alice")


# --- Texte intégral ------------------------------------------------------------------------


def test_fetch_extracts_pages_and_records_unavailable(with_fulltext, settings):
    available = load_fulltext(with_fulltext.db, "PAPER-001")
    assert available.status == FulltextStatus.AVAILABLE and available.page_count == 2
    assert available.pdf_url == ARXIV_PDF
    assert pages_path(settings.papers_dir, "PAPER-001").exists()
    assert load_fulltext(with_fulltext.db, "PAPER-002").status == FulltextStatus.UNAVAILABLE
    assert load_fulltext(with_fulltext.db, "PAPER-003") is None  # exclu : jamais téléchargé


@respx.mock
def test_openalex_open_access_pdf_is_used(included, settings, fetcher):
    respx.get("https://api.openalex.org/works/W1").mock(return_value=httpx.Response(200, json={
        "best_oa_location": {"is_oa": True, "pdf_url": "https://repo.example.org/paper.pdf"}, "locations": []}))
    respx.get("https://repo.example.org/paper.pdf").mock(return_value=httpx.Response(200, content=make_pdf([PAGE_2])))
    [record] = fetch_fulltexts(included, settings, fetcher, ["PAPER-002"])
    assert record.status == FulltextStatus.AVAILABLE
    assert record.pdf_url == "https://repo.example.org/paper.pdf"


@respx.mock
def test_html_instead_of_pdf_is_a_failure(included, settings, fetcher):
    respx.get(ARXIV_PDF).mock(return_value=httpx.Response(200, text="<html>Login</html>", headers={"content-type": "text/html"}))
    [record] = fetch_fulltexts(included, settings, fetcher, ["PAPER-001"])
    assert record.status == FulltextStatus.FAILED
    assert "pas un PDF" in record.error


@respx.mock
def test_available_text_is_not_downloaded_again(with_fulltext, settings, fetcher):
    route = respx.get(ARXIV_PDF)
    [record] = fetch_fulltexts(with_fulltext, settings, fetcher, ["PAPER-001"])
    assert record.status == FulltextStatus.AVAILABLE
    assert route.call_count == 0


def test_available_text_is_frozen_in_database(with_fulltext):
    with pytest.raises(sqlite3.IntegrityError):
        with_fulltext.db.conn.execute("UPDATE fulltexts SET page_count = 99 WHERE paper_id = 'PAPER-001'")


# --- Preuves ---------------------------------------------------------------------------------


def test_verified_quote_becomes_evidence(with_fulltext, settings):
    evidence = _evidence(with_fulltext, settings)
    assert evidence.evidence_id == "EV-001"
    assert evidence.text_sha256.startswith("sha256:")
    matrix = with_fulltext.evidence_matrix()
    assert [row["paper_id"] for row in matrix] == ["PAPER-001", "PAPER-002"]
    assert matrix[0]["evidence"][0]["evidence_id"] == "EV-001"


def test_fabricated_quote_is_rejected(with_fulltext, settings):
    with pytest.raises(ReviewError, match="ni ailleurs dans le texte"):
        _evidence(with_fulltext, settings, quote="governance was fully verifiable on chain")


def test_wrong_page_is_rejected_with_hint(with_fulltext, settings):
    with pytest.raises(ReviewError, match=r"page\(s\) 2"):
        _evidence(with_fulltext, settings, quote="local autonomy reduced conflicts by 30 percent", page=1)


def test_short_quote_is_rejected(with_fulltext, settings):
    with pytest.raises(ReviewError, match="trop court"):
        _evidence(with_fulltext, settings, quote="risk oversight")


def test_abstract_evidence_when_no_fulltext(with_fulltext, settings):
    with pytest.raises(ReviewError, match="sans --page"):
        _evidence(with_fulltext, settings, paper_id="PAPER-002", quote="An abstract about something else entirely")
    evidence = _evidence(with_fulltext, settings, paper_id="PAPER-002", page=None,
                         quote="An abstract about something else entirely")
    assert evidence.location == "abstract" and evidence.page is None


def test_evidence_requires_included_paper(with_fulltext, settings):
    with pytest.raises(ReviewError, match="n'est pas inclus"):
        _evidence(with_fulltext, settings, paper_id="PAPER-003", page=None, quote="whatever text that is long enough")


def test_tampered_text_is_detected(with_fulltext, settings):
    path = pages_path(settings.papers_dir, "PAPER-001")
    path.write_text(path.read_text().replace("Results", "Invented results"))
    with pytest.raises(FulltextTampered):
        _evidence(with_fulltext, settings)


def test_evidence_is_immutable_but_can_be_withdrawn(with_fulltext, settings):
    _evidence(with_fulltext, settings)
    with pytest.raises(sqlite3.IntegrityError):
        with_fulltext.db.conn.execute("UPDATE evidence SET quote = 'changed' WHERE evidence_id = 'EV-001'")
    withdraw_evidence(with_fulltext, "EV-001", "Contresens sur le passage")
    with pytest.raises(ReviewError, match="déjà retiré"):
        withdraw_evidence(with_fulltext, "EV-001", "encore")
    assert with_fulltext.evidence_matrix()[0]["evidence"] == []


# --- Contrôle de literature-review.md -----------------------------------------------------------


def test_review_check(with_fulltext, settings):
    _evidence(with_fulltext, settings)
    papers, evidence = with_fulltext.load_papers(), with_fulltext.load_evidence()

    ok = check_literature_review("Responsabilité incohérente [PAPER-001, EV-001].", papers, evidence)
    assert ok.errors == []
    assert "PAPER-002 inclus mais jamais cité" in ok.warnings

    bad = check_literature_review("Voir [PAPER-003], [PAPER-404] et [EV-999].", papers, evidence)
    assert bad.errors == [
        "PAPER-003 cité mais pas inclus (statut excluded)",
        "PAPER-404 cité mais absent du corpus du projet",
        "EV-999 cité mais n'existe pas dans ce projet",
    ]
    assert check_literature_review(None, papers, evidence).errors == ["literature-review.md est absent ou vide"]


# --- Transitions ---------------------------------------------------------------------------------


def test_review_cannot_start_below_minimum_corpus(settings):
    repo = ProjectRepository(Database(settings.db_path), settings.projects_dir, "gamma")
    repo.create("x", actor="alice")
    repo.transition(ResearchState.SCOPING, actor="alice", policy=settings.policy)
    repo.scope_file.write_text("scope")
    repo.transition(ResearchState.LITERATURE_SEARCH, actor="alice", policy=settings.policy)
    with pytest.raises(TransitionError, match="NEEDS_MORE_RESEARCH"):
        repo.transition(ResearchState.LITERATURE_REVIEW, actor="alice", policy=settings.policy)


def test_gap_analysis_requires_complete_review(repo, settings, fetcher):
    with pytest.raises(TransitionError) as refused:
        repo.transition(ResearchState.GAP_ANALYSIS, actor="alice", policy=settings.policy)
    message = str(refused.value)
    assert "3 publications ne sont pas encore triées" in message
    assert "aucune preuve enregistrée" in message
    assert "literature-review.md est absent ou vide" in message


def test_gap_analysis_after_complete_review(with_fulltext, settings):
    _evidence(with_fulltext, settings)
    (with_fulltext.dir / "literature-review.md").write_text("# État de l'art\nResponsabilité [PAPER-001, EV-001].\n")
    project = with_fulltext.transition(ResearchState.GAP_ANALYSIS, actor="alice", policy=settings.policy)
    assert project.state == ResearchState.GAP_ANALYSIS
