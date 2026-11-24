"""Étape 3e : Gate 2 — soumission du Research Proposal par l'agent, décision humaine."""

import json

import pytest
from test_critique import MAJOR, _review, reviewing  # noqa: F401 — fixtures partagées
from test_gaps import _alignment, _contradictory_search, _draft, analysis  # noqa: F401
from test_gate import human, ready, submitted  # noqa: F401
from test_proposal import _write, drafting  # noqa: F401
from test_questions import _hypothesis, _question, formulation  # noqa: F401
from test_review import _evidence, fetcher, included, repo, settings, with_fulltext  # noqa: F401
from test_solutions import _comparison, _solution, _two_solutions, design  # noqa: F401

from research_lab.critique import submit_review
from research_lab.proposal import write_references
from research_lab.schemas.gate import Gate, GateDecisionType
from research_lab.workflow import approvals
from research_lab.workflow.approvals import GATE_2_ARTIFACTS, GateError, current_gate, submit_gate_2
from research_lab.workflow.state import ResearchState
from research_lab.workflow.transitions import TransitionError

APPROVE, REVISE = GateDecisionType.APPROVE, GateDecisionType.REVISE
decide = approvals.decide_gate_2
# Contrôle réel, conservé avant que la fixture `human` (approbation de la Gate 1) ne le remplace.
REAL_HUMAN_CHECK = approvals.human_check_failure


@pytest.fixture
def final(drafting):
    """Proposal complet, references.bib à jour : `proposal check` OK, état PROPOSAL_DRAFT."""
    _write(drafting)
    write_references(drafting)
    return drafting


@pytest.fixture
def awaiting(final):
    submit_gate_2(final, "agent")
    return final


def test_gate_2_transitions_bypass_is_refused(final, settings):
    with pytest.raises(TransitionError, match="Gate 2 : `research-lab gate submit`"):
        final.transition(ResearchState.AWAITING_GATE_2, actor="agent", policy=settings.policy)


def test_submission_requires_clean_proposal_check(drafting):
    with pytest.raises(GateError, match="proposal check.*BLOCKED"):
        submit_gate_2(drafting, "agent")
    assert drafting.load_project().state == ResearchState.PROPOSAL_DRAFT


def test_submission_freezes_proposal(final):
    submission = submit_gate_2(final, "agent")
    assert (submission.gate, submission.round, submission.check_status) == (Gate.GATE_2, 1, "OK")
    assert sorted(submission.artifacts) == sorted(GATE_2_ARTIFACTS)
    assert submission.question_versions == {"RQ-001": 1}
    assert submission.solution_versions == {"SOL-001": 1, "SOL-002": 1}
    assert final.load_project().state == ResearchState.AWAITING_GATE_2
    assert current_gate(final) == Gate.GATE_2
    assert (final.dir / "gate-2.json").exists() and (final.dir / "gate-1.json").exists()


def test_agent_cannot_decide(awaiting, monkeypatch):
    monkeypatch.setattr(approvals, "human_check_failure", REAL_HUMAN_CHECK)
    monkeypatch.setenv("CLAUDECODE", "1")
    with pytest.raises(GateError, match="Claude Code"):
        decide(awaiting, APPROVE, "ok", "alice")
    monkeypatch.delenv("CLAUDECODE")
    with pytest.raises(GateError, match="terminal interactif"):  # pytest capture l'entrée standard
        decide(awaiting, APPROVE, "ok", "alice")
    assert awaiting.load_project().state == ResearchState.AWAITING_GATE_2


def test_approve_completes_project(awaiting, human):
    decision = decide(awaiting, APPROVE, "Proposal accepté", "alice")
    assert decision.gate == Gate.GATE_2 and decision.selected_gaps == {} and decision.artifacts_verified
    assert awaiting.load_project().state == ResearchState.COMPLETED
    [round_1] = json.loads((awaiting.dir / "gate-2.json").read_text())
    assert round_1["decision"]["decision"] == "approve"
    with pytest.raises(GateError, match="n'attend pas la gate_2"):
        decide(awaiting, REVISE, "encore", "alice")


def test_modified_proposal_blocks_approval_not_revision(awaiting, human):
    proposal = awaiting.dir / "research-proposal.md"
    proposal.write_text(proposal.read_text() + "Ajout après soumission.\n")
    with pytest.raises(GateError, match="research-proposal.md"):
        decide(awaiting, APPROVE, "ok", "alice")
    decision = decide(awaiting, REVISE, "Préciser le protocole", "alice")
    assert decision.modified_artifacts == ["research-proposal.md"]


def test_revise_returns_to_solution_design_with_fresh_review_rounds(awaiting, settings, human):
    decide(awaiting, REVISE, "Comparer aussi une solution sans chaîne de blocs", "alice")
    assert awaiting.load_project().state == ResearchState.SOLUTION_DESIGN
    policy = settings.policy.model_copy(update={"max_review_rounds": 1})  # un tour déjà fait avant la Gate 2
    awaiting.transition(ResearchState.SCIENTIFIC_REVIEW, actor="agent", policy=policy)
    assert submit_review(awaiting, settings, _review(objections=[]), "scientific-reviewer").round == 2
    awaiting.transition(ResearchState.PROPOSAL_DRAFT, actor="agent", policy=policy)
    assert submit_gate_2(awaiting, "agent").round == 2
