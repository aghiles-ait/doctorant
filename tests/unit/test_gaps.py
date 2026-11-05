"""Étape 2c : gaps scientifiques, recherches contradictoires, alignement sur les valeurs."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from test_review import (  # noqa: F401 — fixtures partagées avec l'étape 2b
    _evidence,
    fetcher,
    included,
    repo,
    settings,
    with_fulltext,
)

from research_lab.gaps import GapError, add_gap, check_gaps, revise_gap, set_alignment
from research_lab.providers.base import ProviderResult
from research_lab.review import ReviewError, decide, withdraw_evidence
from research_lab.schemas.evidence import Evidence, EvidenceLocation, EvidenceType
from research_lab.schemas.gap import AlignmentDraft, EvidenceStrength, GapDraft, GapStatus
from research_lab.schemas.paper import PaperMetadata, PaperStatus, Source, SourceHit
from research_lab.schemas.search import SearchQuery
from research_lab.validation.gaps import strength_ceiling
from research_lab.watch import SearchNotAllowed, run_search
from research_lab.workflow.state import ResearchState

VALUES = ["privacy", "freedom", "sovereignty", "governance", "decentralization", "verifiability"]


@dataclass
class FakeProvider:
    """Source académique simulée renvoyant des résultats fixes."""

    hits: list[SourceHit]
    source: Source = Source.OPENALEX

    def search(self, query: SearchQuery) -> ProviderResult:
        return ProviderResult(hits=self.hits, provider_query=query.text, total_available=len(self.hits))


@pytest.fixture
def analysis(with_fulltext, settings):
    """Projet à l'état GAP_ANALYSIS : EV-001 et EV-003 (PAPER-001, texte intégral), EV-002 (PAPER-002, résumé)."""
    _evidence(with_fulltext, settings)
    _evidence(with_fulltext, settings, paper_id="PAPER-002", page=None, evidence_type=EvidenceType.POSITION,
              quote="An abstract about something else entirely", claim="Position des auteurs")
    _evidence(with_fulltext, settings, quote="local autonomy reduced conflicts by 30 percent", page=2,
              claim="L'autonomie locale réduit les conflits")
    (with_fulltext.dir / "literature-review.md").write_text("Responsabilité [PAPER-001, EV-001] [PAPER-002, EV-002].\n")
    with_fulltext.transition(ResearchState.GAP_ANALYSIS, actor="alice", policy=settings.policy)
    return with_fulltext


def _draft(**kwargs) -> GapDraft:
    data = {
        "title": "Responsabilité vérifiable dans la gouvernance décentralisée",
        "description": "Aucun mécanisme évalué ne rend la responsabilité vérifiable.",
        "category": "missing_evaluation",
        "rationale": "EV-001 constate une responsabilité incohérente ; EV-002 ne propose aucune évaluation.",
        "supporting_evidence": ["EV-001", "EV-002"],
        "evidence_strength": "medium",
    } | kwargs
    return GapDraft.model_validate(data)


def _alignment(score: int | None = 4, **overrides) -> AlignmentDraft:
    scores = {v: {"score": score, "justification": f"justification {v}"} for v in VALUES}
    return AlignmentDraft.model_validate({"scores": scores | overrides, "tradeoffs": ["vérifiabilité contre confidentialité"]})


def _contradictory_search(repo, settings, gap_id: str, hits: list[SourceHit] | None = None):
    return run_search(repo, settings, [FakeProvider(hits or [])], SearchQuery(text="verifiable accountability"), gap_id=gap_id)


NEW_HIT = SourceHit(source=Source.OPENALEX, source_id="W9", metadata=PaperMetadata(
    title="Verifiable accountability for decentralized AI", openalex_id="W9",
    abstract="We already provide verifiable accountability for decentralized AI governance systems."))


# --- Force des preuves -----------------------------------------------------------------------


def _ev(paper_id: str, evidence_type: EvidenceType) -> Evidence:
    return Evidence(evidence_id="EV-001", project_id="p", paper_id=paper_id, claim="c", quote="q",
                    location=EvidenceLocation.ABSTRACT, evidence_type=evidence_type, text_sha256="h",
                    created_at=datetime(2026, 11, 3, tzinfo=UTC), actor="a")


def test_strength_ceiling():
    position, result = EvidenceType.POSITION, EvidenceType.EMPIRICAL_RESULT
    assert strength_ceiling([_ev("P1", position), _ev("P1", position)]) == EvidenceStrength.LOW
    assert strength_ceiling([_ev("P1", position), _ev("P2", position)]) == EvidenceStrength.MEDIUM
    assert strength_ceiling([_ev("P1", result)]) == EvidenceStrength.MEDIUM
    assert strength_ceiling([_ev("P1", result), _ev("P1", result)]) == EvidenceStrength.MEDIUM
    assert strength_ceiling([_ev("P1", result), _ev("P2", result)]) == EvidenceStrength.HIGH


def test_draft_rejects_evidence_cited_on_both_sides():
    with pytest.raises(ValueError, match="à la fois favorables et contraires"):
        _draft(contradicting_evidence=["EV-001"])


# --- Création et révision -------------------------------------------------------------------


def test_gap_requires_gap_analysis_state(with_fulltext, settings):
    with pytest.raises(GapError, match="GAP_ANALYSIS"):
        add_gap(with_fulltext, settings, _draft(), "", "alice")


def test_gap_is_recorded_and_exported(analysis, settings):
    gap = add_gap(analysis, settings, _draft(), "Lecture croisée de EV-001 et EV-002", "alice")
    assert (gap.gap_id, gap.version, gap.status, gap.novelty_assessment) == ("GAP-001", 1, "candidate", "unverified")
    [exported] = analysis.gaps_export()
    assert exported["supporting_papers"] == ["PAPER-001", "PAPER-002"]
    assert exported["contradictory_searches"] == []
    assert (analysis.dir / "gaps.json").exists()


@pytest.mark.parametrize(("kwargs", "message"), [
    ({"supporting_evidence": ["EV-404"]}, "EV-404 n'existe pas"),
    ({"evidence_strength": "high"}, "ne permettent que medium"),
    ({"supporting_evidence": ["EV-002"]}, "ne permettent que low"),
    ({"status": "supported"}, "aucune recherche contradictoire"),
    ({"status": "resolved"}, "contradicting_evidence"),
    ({"novelty_assessment": "not_found_in_searches"}, "aucune recherche contradictoire"),
])
def test_unsupported_declarations_are_rejected(analysis, settings, kwargs, message):
    with pytest.raises(GapError, match=message):
        add_gap(analysis, settings, _draft(**kwargs), "", "alice")


def test_withdrawn_evidence_cannot_be_cited(analysis, settings):
    withdraw_evidence(analysis, "EV-002", "contresens")
    with pytest.raises(GapError, match="EV-002 est retirée"):
        add_gap(analysis, settings, _draft(), "", "alice")


def test_revision_keeps_id_and_history(analysis, settings):
    add_gap(analysis, settings, _draft(), "", "alice")
    with pytest.raises(GapError, match="raison"):
        revise_gap(analysis, settings, "GAP-001", _draft(title="Autre"), "", "alice")
    with pytest.raises(GapError, match="Aucun changement"):
        revise_gap(analysis, settings, "GAP-001", _draft(), "relecture", "alice")
    revised = revise_gap(analysis, settings, "GAP-001", _draft(objections=["EV-003 suggère le contraire"]), "objection", "bob")
    assert (revised.gap_id, revised.version, revised.actor) == ("GAP-001", 2, "bob")
    assert [g.version for g in analysis.gap_history("GAP-001")] == [1, 2]
    assert [g.version for g in analysis.load_gaps()] == [2]


def test_gap_history_is_append_only(analysis, settings):
    add_gap(analysis, settings, _draft(), "", "alice")
    for statement in ("UPDATE gap_versions SET status = 'supported'", "DELETE FROM gap_versions",
                      "DELETE FROM gaps", "UPDATE gap_evidence SET role = 'contradicting'"):
        with pytest.raises(sqlite3.IntegrityError):
            analysis.db.conn.execute(statement)


# --- Recherche contradictoire (Q3) -------------------------------------------------------------


def test_search_in_gap_analysis_requires_a_gap(analysis, settings):
    with pytest.raises(SearchNotAllowed, match="préciser le gap"):
        run_search(analysis, settings, [FakeProvider([])], SearchQuery(text="q"))
    with pytest.raises(SearchNotAllowed, match="GAP-404"):
        _contradictory_search(analysis, settings, "GAP-404")


def test_contradictory_search_allows_supported_status(analysis, settings):
    add_gap(analysis, settings, _draft(), "", "alice")
    execution = _contradictory_search(analysis, settings, "GAP-001")
    assert execution.gap_id == "GAP-001"
    gap = revise_gap(analysis, settings, "GAP-001", _draft(status="supported", novelty_assessment="not_found_in_searches"),
                     "rien trouvé par SEARCH-002", "alice")
    assert gap.status == GapStatus.SUPPORTED
    assert analysis.gaps_export()[0]["contradictory_searches"] == [execution.search_id]


def test_supported_requires_several_papers(analysis, settings):
    add_gap(analysis, settings, _draft(supporting_evidence=["EV-001", "EV-003"]), "", "alice")
    _contradictory_search(analysis, settings, "GAP-001")
    with pytest.raises(GapError, match="1 publication"):
        revise_gap(analysis, settings, "GAP-001", _draft(supporting_evidence=["EV-001", "EV-003"], status="supported"),
                   "r", "alice")


def test_papers_found_by_contradictory_search_are_screened(analysis, settings):
    add_gap(analysis, settings, _draft(), "", "alice")
    execution = _contradictory_search(analysis, settings, "GAP-001", [NEW_HIT])
    [new_paper] = execution.new_paper_ids
    assert check_gaps(analysis, settings).errors[0] == "1 publications trouvées par les recherches contradictoires restent à trier"
    with pytest.raises(ReviewError, match="déjà trié"):
        decide(analysis, "PAPER-003", PaperStatus.INCLUDED, "relecture", "alice")
    decide(analysis, new_paper, PaperStatus.INCLUDED, "Comble peut-être GAP-001", "alice")

    contrary = _evidence(analysis, settings, paper_id=new_paper, page=None, evidence_type=EvidenceType.METHOD,
                         quote="We already provide verifiable accountability", claim="Mécanisme existant")
    gap = revise_gap(analysis, settings, "GAP-001",
                     _draft(contradicting_evidence=[contrary.evidence_id], novelty_assessment="partially_addressed"),
                     "travaux existants trouvés", "alice")
    assert gap.novelty_assessment == "partially_addressed"
    assert analysis.gaps_export()[0]["contradicting_papers"] == [new_paper]


# --- Alignement sur les valeurs -------------------------------------------------------------------


def test_alignment_scores_and_ranking(analysis, settings):
    add_gap(analysis, settings, _draft(), "", "alice")
    alignment = set_alignment(analysis, settings, "GAP-001", _alignment(4, privacy={"score": None, "justification": "sans objet"}), "alice")
    assert alignment.alignment_score == 0.8  # 4/5 sur les cinq valeurs applicables
    assert alignment.priority_score == 0.65  # 0.5 × 0.8 + 0.5 × 0.5 (medium)
    assert alignment.values_hash == settings.values_hash()
    [row] = analysis.alignment_export()
    assert (row["rank"], row["gap_id"], row["stale"]) == (1, "GAP-001", False)


@pytest.mark.parametrize(("draft", "message"), [
    (AlignmentDraft(scores={}, tradeoffs=[]), "valeurs non évaluées"),
    (_alignment(4, ethics={"score": 3, "justification": "x"}), "valeurs inconnues"),
    (_alignment(4, privacy={"score": 7, "justification": "x"}), "hors de l'échelle"),
    (_alignment(4, privacy={"score": 2, "justification": " "}), "justification obligatoire"),
    (_alignment(None), "aucune valeur applicable"),
])
def test_invalid_alignment_is_rejected(analysis, settings, draft, message):
    add_gap(analysis, settings, _draft(), "", "alice")
    with pytest.raises(GapError, match=message):
        set_alignment(analysis, settings, "GAP-001", draft, "alice")


def test_withdrawn_gap_is_not_evaluated(analysis, settings):
    add_gap(analysis, settings, _draft(), "", "alice")
    revise_gap(analysis, settings, "GAP-001", _draft(status="withdrawn"), "hors périmètre", "alice")
    with pytest.raises(GapError, match="withdrawn"):
        set_alignment(analysis, settings, "GAP-001", _alignment(), "alice")
    assert analysis.alignment_export() == []


# --- Contrôle d'ensemble -------------------------------------------------------------------------


def test_gap_check(analysis, settings):
    assert check_gaps(analysis, settings).errors == ["aucun gap enregistré"]

    add_gap(analysis, settings, _draft(), "", "alice")
    assert check_gaps(analysis, settings).errors == ["GAP-001 : pas d'évaluation au regard des valeurs (`alignment set`)"]

    set_alignment(analysis, settings, "GAP-001", _alignment(), "alice")
    result = check_gaps(analysis, settings)
    assert result.status == "NEEDS_MORE_RESEARCH"  # aucun gap supported
    assert "GAP-001 : aucune recherche contradictoire (Q3), nouveauté non vérifiée" in result.warnings

    _contradictory_search(analysis, settings, "GAP-001")
    revise_gap(analysis, settings, "GAP-001", _draft(status="supported"), "recherche contradictoire faite", "alice")
    assert "évaluation périmée" in check_gaps(analysis, settings).errors[0]
    set_alignment(analysis, settings, "GAP-001", _alignment(), "alice")
    assert check_gaps(analysis, settings).status == "OK"

    # Une preuve retirée après coup invalide le gap qui la cite.
    withdraw_evidence(analysis, "EV-002", "contresens")
    errors = check_gaps(analysis, settings).errors
    assert "GAP-001 : EV-002 est retirée (contresens)" in errors
    assert any("1 publication(s), minimum 2" in e for e in errors)


def test_changed_values_make_alignment_stale(analysis, settings):
    add_gap(analysis, settings, _draft(), "", "alice")
    set_alignment(analysis, settings, "GAP-001", _alignment(), "alice")
    reweighted = settings.model_copy(update={"values": settings.values.model_copy(deep=True)})
    reweighted.values.values["privacy"].weight = 2.0
    assert "d'autres valeurs" in check_gaps(analysis, reweighted).errors[0]
