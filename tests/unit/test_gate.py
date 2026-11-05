"""Étape 2d : Gate 1 — soumission par l'agent, décision humaine, intégrité des livrables."""

import sqlite3

import pytest
from test_gaps import _alignment, _contradictory_search, _draft, analysis  # noqa: F401 — fixtures partagées
from test_review import _evidence, fetcher, included, repo, settings, with_fulltext  # noqa: F401

from research_lab.gaps import add_gap, revise_gap, set_alignment
from research_lab.schemas.gate import GateDecisionType
from research_lab.workflow import approvals
from research_lab.workflow.approvals import GATE_1_ARTIFACTS, GateError, decide_gate_1, submit_gate_1
from research_lab.workflow.state import ResearchState
from research_lab.workflow.transitions import TransitionError

APPROVE, REVISE = GateDecisionType.APPROVE, GateDecisionType.REVISE


@pytest.fixture
def human(monkeypatch):
    """Simule un humain dans son terminal (les tests n'ont ni TTY ni l'environnement d'un humain)."""
    monkeypatch.setattr(approvals, "human_check_failure", lambda: None)


@pytest.fixture
def ready(analysis, settings):
    """GAP-001 supported et évalué, GAP-002 candidate et évalué : `gap check` OK."""
    add_gap(analysis, settings, _draft(), "", "alice")
    _contradictory_search(analysis, settings, "GAP-001")
    revise_gap(analysis, settings, "GAP-001", _draft(status="supported"), "recherche contradictoire faite", "alice")
    add_gap(analysis, settings, _draft(title="Second gap", supporting_evidence=["EV-003"]), "", "alice")
    for gap_id in ("GAP-001", "GAP-002"):
        set_alignment(analysis, settings, gap_id, _alignment(), "alice")
    return analysis


@pytest.fixture
def submitted(ready, settings):
    submit_gate_1(ready, settings, "agent")
    return ready


# --- Soumission ---------------------------------------------------------------------------------


def test_gate_transitions_bypass_is_refused(ready, settings):
    with pytest.raises(TransitionError, match="gate submit"):
        ready.transition(ResearchState.AWAITING_GATE_1, actor="alice", policy=settings.policy)


def test_submission_requires_clean_gap_check(analysis, settings):
    with pytest.raises(GateError, match="BLOCKED.*aucun gap"):
        submit_gate_1(analysis, settings, "agent")
    assert analysis.load_project().state == ResearchState.GAP_ANALYSIS


def test_submission_freezes_artifacts_and_waits(ready, settings):
    submission = submit_gate_1(ready, settings, "agent")
    assert (submission.round, submission.check_status) == (1, "OK")
    assert sorted(submission.artifacts) == sorted(GATE_1_ARTIFACTS)
    assert submission.gap_versions == {"GAP-001": 2, "GAP-002": 1}
    assert ready.load_project().state == ResearchState.AWAITING_GATE_1
    assert (ready.dir / "gate-1.json").exists()
    with pytest.raises(GateError, match="GAP_ANALYSIS"):
        submit_gate_1(ready, settings, "agent")


# --- Seul un humain décide -------------------------------------------------------------------------


def test_agent_cannot_decide(submitted, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    with pytest.raises(GateError, match="Claude Code"):
        decide_gate_1(submitted, APPROVE, "ok", "alice", ["GAP-001"])
    monkeypatch.delenv("CLAUDECODE")
    with pytest.raises(GateError, match="terminal interactif"):  # pytest capture l'entrée standard
        decide_gate_1(submitted, APPROVE, "ok", "alice", ["GAP-001"])
    assert submitted.load_project().state == ResearchState.AWAITING_GATE_1


# --- Décision --------------------------------------------------------------------------------------


def test_approve_selects_submitted_gap_versions(submitted, human):
    decision = decide_gate_1(submitted, APPROVE, "Le plus solide", "alice", ["GAP-001"])
    assert decision.selected_gaps == {"GAP-001": 2}
    assert decision.artifacts_verified
    project = submitted.load_project()
    assert project.state == ResearchState.PROBLEM_FORMULATION
    assert (project.history[-1].from_state, project.history[-1].actor) == (ResearchState.AWAITING_GATE_1, "alice")
    with pytest.raises(GateError, match="n'attend pas"):
        decide_gate_1(submitted, REVISE, "encore", "alice")


@pytest.mark.parametrize(("gaps", "comment", "message"), [
    ([], "ok", "au moins un gap"),
    (["GAP-404"], "ok", "absents du dossier"),
    (["GAP-001"], "  ", "commentaire"),
])
def test_invalid_approval_is_refused(submitted, human, gaps, comment, message):
    with pytest.raises(GateError, match=message):
        decide_gate_1(submitted, APPROVE, comment, "alice", gaps)
    assert submitted.load_project().state == ResearchState.AWAITING_GATE_1


def test_modified_artifact_blocks_approval_not_revision(submitted, human):
    review = submitted.dir / "literature-review.md"
    review.write_text(review.read_text() + "Ajout après soumission.\n")
    with pytest.raises(GateError, match="literature-review.md"):
        decide_gate_1(submitted, APPROVE, "ok", "alice", ["GAP-001"])
    decision = decide_gate_1(submitted, REVISE, "Revoir l'état de l'art", "alice")
    assert decision.modified_artifacts == ["literature-review.md"] and not decision.artifacts_verified


def test_revise_returns_to_search_and_keeps_work(submitted, settings, human):
    decide_gate_1(submitted, REVISE, "Chercher des travaux sur la vérification formelle", "alice")
    assert submitted.load_project().state == ResearchState.LITERATURE_SEARCH
    assert [g.gap_id for g in submitted.load_gaps()] == ["GAP-001", "GAP-002"]
    assert len(submitted.load_evidence()) == 3

    # Second tour : les étapes déjà faites restent valides, une nouvelle soumission est possible.
    policy = settings.policy.model_copy(update={"min_corpus_size": 0})
    submitted.transition(ResearchState.LITERATURE_REVIEW, actor="alice", policy=policy)
    submitted.transition(ResearchState.GAP_ANALYSIS, actor="alice", policy=policy)
    assert submit_gate_1(submitted, settings, "agent").round == 2
    rounds = submitted.gate_export(approvals.Gate.GATE_1)
    assert [(r["round"], r["decision"] and r["decision"]["decision"]) for r in rounds] == [(1, "revise"), (2, None)]


def test_gate_records_are_immutable(submitted, human):
    decide_gate_1(submitted, APPROVE, "ok", "alice", ["GAP-001"])
    for statement in ("UPDATE gate_decisions SET approver = 'agent'", "DELETE FROM gate_decisions",
                      "UPDATE gate_submissions SET actor = 'x'", "DELETE FROM gate_submissions"):
        with pytest.raises(sqlite3.IntegrityError):
            submitted.db.conn.execute(statement)
