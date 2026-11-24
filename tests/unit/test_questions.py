"""Étape 3a : questions de recherche et hypothèses falsifiables, rattachées aux gaps retenus à la Gate 1."""

import json
import sqlite3

import pytest
from pydantic import ValidationError
from test_gaps import _alignment, _contradictory_search, _draft, analysis  # noqa: F401 — fixtures partagées
from test_gate import human, ready, submitted  # noqa: F401
from test_review import _evidence, fetcher, included, repo, settings, with_fulltext  # noqa: F401

from research_lab.questions import QuestionError, add_question, check_questions, revise_question
from research_lab.schemas.gate import GateDecisionType
from research_lab.schemas.question import QuestionDraft
from research_lab.workflow.approvals import decide_gate_1
from research_lab.workflow.state import ResearchState
from research_lab.workflow.transitions import TransitionError


@pytest.fixture
def formulation(submitted, human):
    """Gate 1 approuvée : GAP-001 (version 2) retenu, GAP-002 écarté ; état PROBLEM_FORMULATION."""
    decide_gate_1(submitted, GateDecisionType.APPROVE, "GAP-001 retenu", "alice", ["GAP-001"])
    return submitted


def _hypothesis(**kwargs) -> dict:
    return {
        "hypothesis_id": "H1",
        "statement": "Un registre public des décisions rend la responsabilité vérifiable.",
        "prediction": "Plus de 90 % des décisions sont attribuées à un responsable identifiable.",
        "refutation_criterion": "Moins de 50 % des décisions sont attribuables dans l'étude de cas.",
        "test_method": "Étude de cas sur trois organisations décentralisées",
        "metrics": ["taux de décisions attribuables"],
        "evidence": ["EV-001"],
    } | kwargs


def _question(**kwargs) -> QuestionDraft:
    data = {
        "question": "Un registre public suffit-il à rendre la responsabilité vérifiable ?",
        "gap_ids": ["GAP-001"],
        "rationale": "GAP-001 : aucun mécanisme évalué ; la question porte sur le plus simple.",
        "hypotheses": [_hypothesis()],
    } | kwargs
    return QuestionDraft.model_validate(data)


def _transition(repo, settings):
    return repo.transition(ResearchState.SOLUTION_DESIGN, actor="alice", policy=settings.policy)


def test_questions_require_problem_formulation(submitted):
    with pytest.raises(QuestionError, match="PROBLEM_FORMULATION"):
        add_question(submitted, _question(), "", "agent")


def test_add_question_is_exported(formulation):
    question = add_question(formulation, _question(), "", "agent")
    assert (question.question_id, question.version, question.reason) == ("RQ-001", 1, "création")
    [exported] = json.loads((formulation.dir / "research-questions.json").read_text())
    assert exported["question_id"] == "RQ-001" and exported["cited_papers"] == ["PAPER-001"]
    assert check_questions(formulation).status == "OK"


@pytest.mark.parametrize("gap_id", ["GAP-002", "GAP-404"])
def test_question_must_address_a_retained_gap(formulation, gap_id):
    with pytest.raises(QuestionError, match=f"{gap_id} n'a pas été retenu.*GAP-001"):
        add_question(formulation, _question(gap_ids=[gap_id]), "", "agent")


def test_hypothesis_evidence_must_exist_and_be_active(formulation):
    with pytest.raises(QuestionError, match="H1 : EV-999 n'existe pas"):
        add_question(formulation, _question(hypotheses=[_hypothesis(evidence=["EV-999"])]), "", "agent")
    formulation.withdraw_evidence("EV-003", "extrait mal choisi")
    with pytest.raises(QuestionError, match="EV-003 est retirée"):
        add_question(formulation, _question(hypotheses=[_hypothesis(evidence=["EV-003"])]), "", "agent")


@pytest.mark.parametrize(("change", "message"), [
    ({"hypotheses": []}, "at least 1 item"),
    ({"hypotheses": [_hypothesis(refutation_criterion=" plus de 90 % des décisions sont attribuées à un "
                                 "responsable identifiable. ")]}, "répète la prédiction"),
    ({"hypotheses": [_hypothesis(refutation_criterion="   ")]}, "at least 1 character"),
    ({"hypotheses": [_hypothesis(metrics=[])]}, "at least 1 item"),
    ({"hypotheses": [_hypothesis(evidence=[])]}, "at least 1 item"),
    ({"hypotheses": [_hypothesis(evidence=["EV-001", "EV-001"])]}, "plusieurs fois"),
    ({"hypotheses": [_hypothesis(), _hypothesis()]}, "en double"),
    ({"gap_ids": ["GAP-001", "GAP-001"]}, "plusieurs fois"),
])
def test_hypotheses_must_be_falsifiable(change, message):
    with pytest.raises(ValidationError, match=message):
        _question(**change)


def test_revise_question_keeps_history(formulation):
    add_question(formulation, _question(), "", "agent")
    with pytest.raises(QuestionError, match="raison"):
        revise_question(formulation, "RQ-001", _question(question="Autre ?"), " ", "agent")
    with pytest.raises(QuestionError, match="Aucun changement"):
        revise_question(formulation, "RQ-001", _question(), "rien", "agent")
    revised = revise_question(formulation, "RQ-001", _question(constraints=["sans tiers de confiance"]), "contrainte", "agent")
    assert revised.version == 2 and revised.created_at <= revised.updated_at
    assert [q.version for q in formulation.question_history("RQ-001")] == [1, 2]


def test_transition_requires_a_question_per_retained_gap(submitted, settings, human):
    decide_gate_1(submitted, GateDecisionType.APPROVE, "Les deux", "alice", ["GAP-001", "GAP-002"])
    with pytest.raises(TransitionError, match="aucune question de recherche active"):
        _transition(submitted, settings)
    add_question(submitted, _question(), "", "agent")
    with pytest.raises(TransitionError, match="sans question : GAP-002"):
        _transition(submitted, settings)
    add_question(submitted, _question(question="Second ?", gap_ids=["GAP-002"]), "", "agent")
    assert _transition(submitted, settings).state == ResearchState.SOLUTION_DESIGN


def test_withdrawn_question_no_longer_covers_its_gap(formulation, settings):
    add_question(formulation, _question(), "", "agent")
    revise_question(formulation, "RQ-001", _question(status="withdrawn"), "reformulée", "agent")
    check = check_questions(formulation)
    assert check.status == "BLOCKED" and "sans question : GAP-001" in check.errors[-1]
    with pytest.raises(TransitionError):
        _transition(formulation, settings)


def test_question_history_is_immutable(formulation):
    add_question(formulation, _question(), "", "agent")
    for statement in ("UPDATE question_versions SET actor = 'x'", "DELETE FROM question_versions",
                      "DELETE FROM question_evidence", "DELETE FROM research_questions"):
        with pytest.raises(sqlite3.IntegrityError):
            formulation.db.conn.execute(statement)
