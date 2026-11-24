"""Étape 3b : solutions conceptuelles, alternatives et comparaison par question."""

import json
import sqlite3

import pytest
from pydantic import ValidationError
from test_gaps import _alignment, _contradictory_search, _draft, analysis  # noqa: F401 — fixtures partagées
from test_gate import human, ready, submitted  # noqa: F401
from test_questions import _hypothesis, _question, formulation  # noqa: F401
from test_review import _evidence, fetcher, included, repo, settings, with_fulltext  # noqa: F401

from research_lab.questions import add_question
from research_lab.schemas.solution import ComparisonDraft, SolutionDraft
from research_lab.solutions import SolutionError, add_solution, check_solutions, revise_solution, set_comparison
from research_lab.workflow.state import ResearchState
from research_lab.workflow.transitions import TransitionError

CRITERIA = ["vérifiabilité", "coût"]


@pytest.fixture
def design(formulation, settings):
    """RQ-001 (hypothèses H1 et H2) sur GAP-001 ; état SOLUTION_DESIGN."""
    add_question(formulation, _question(hypotheses=[_hypothesis(), _hypothesis(hypothesis_id="H2")]), "", "agent")
    formulation.transition(ResearchState.SOLUTION_DESIGN, actor="agent", policy=settings.policy)
    return formulation


def _solution(**kwargs) -> SolutionDraft:
    data = {
        "title": "Registre public des décisions",
        "question_id": "RQ-001",
        "summary": "Chaque décision est inscrite dans un registre public signé.",
        "architecture": "Registre en ajout seul, signatures des décideurs, vérificateurs indépendants.",
        "addressed_hypotheses": ["H1"],
        "evaluation_plan": "Mesurer le taux de décisions attribuables sur trois organisations.",
        "tradeoffs": ["Transparence contre confidentialité des votants"],
        "risks": ["Registre ignoré par les participants"],
        "evidence": ["EV-001"],
    } | kwargs
    return SolutionDraft.model_validate(data)


def _comparison(solutions=("SOL-001", "SOL-002"), **kwargs) -> ComparisonDraft:
    data = {
        "question_id": "RQ-001",
        "criteria": CRITERIA,
        "assessments": {s: {c: f"{s} sur {c}" for c in CRITERIA} for s in solutions},
        "recommendation": "SOL-001",
        "justification": "SOL-001 est plus simple à vérifier.",
    } | kwargs
    return ComparisonDraft.model_validate(data)


def _two_solutions(repo):
    add_solution(repo, _solution(), "", "agent")
    add_solution(repo, _solution(title="Preuves à divulgation nulle", addressed_hypotheses=["H1", "H2"],
                                 evidence=["EV-002"]), "", "agent")


def test_solutions_require_solution_design(formulation):
    with pytest.raises(SolutionError, match="SOLUTION_DESIGN"):
        add_solution(formulation, _solution(), "", "agent")


def test_add_solution_is_exported(design):
    solution = add_solution(design, _solution(), "", "agent")
    assert (solution.solution_id, solution.version) == ("SOL-001", 1)
    [row] = json.loads((design.dir / "solutions.json").read_text())
    assert row["question_id"] == "RQ-001" and row["comparison"] is None
    assert row["solutions"][0]["cited_papers"] == ["PAPER-001"]


@pytest.mark.parametrize(("change", "message"), [
    ({"question_id": "RQ-404"}, "RQ-404 n'existe pas"),
    ({"addressed_hypotheses": ["H9"]}, "hypothèses absentes de RQ-001 : H9"),
    ({"evidence": ["EV-999"]}, "EV-999 n'existe pas"),
])
def test_solution_is_checked_against_project(design, change, message):
    with pytest.raises(SolutionError, match=message):
        add_solution(design, _solution(**change), "", "agent")


@pytest.mark.parametrize(("change", "message"), [
    ({"tradeoffs": []}, "at least 1 item"),
    ({"risks": []}, "at least 1 item"),
    ({"evaluation_plan": " "}, "at least 1 character"),
    ({"addressed_hypotheses": ["H1", "H1"]}, "plusieurs fois"),
])
def test_solution_draft_requires_tradeoffs_risks_and_plan(change, message):
    with pytest.raises(ValidationError, match=message):
        _solution(**change)


def test_revise_solution(design):
    add_solution(design, _solution(), "", "agent")
    with pytest.raises(SolutionError, match="Aucun changement"):
        revise_solution(design, "SOL-001", _solution(), "rien", "agent")
    with pytest.raises(SolutionError, match="nouvelle solution pour une autre question"):
        revise_solution(design, "SOL-001", _solution(question_id="RQ-002"), "autre", "agent")
    revised = revise_solution(design, "SOL-001", _solution(risks=["Coût de signature"]), "risque", "agent")
    assert revised.version == 2 and [s.version for s in design.solution_history("SOL-001")] == [1, 2]


@pytest.mark.parametrize(("comparison", "message"), [
    (lambda: _comparison(solutions=("SOL-001",)), "solutions non évaluées : SOL-002"),
    (lambda: _comparison(solutions=("SOL-001", "SOL-002", "SOL-009")), "inconnues.*SOL-009"),
    (lambda: _comparison(assessments={"SOL-001": {"coût": "c"}, "SOL-002": {c: "x" for c in CRITERIA}}),
     "SOL-001 : critères non évalués : vérifiabilité"),
    (lambda: _comparison(recommendation="SOL-009"), "recommandation SOL-009"),
])
def test_comparison_must_cover_all_alternatives_and_criteria(design, comparison, message):
    _two_solutions(design)
    with pytest.raises(SolutionError, match=message):
        set_comparison(design, comparison(), "agent")


def test_comparison_needs_two_alternatives_and_two_criteria(design):
    add_solution(design, _solution(), "", "agent")
    with pytest.raises(SolutionError, match="au moins deux solutions"):
        set_comparison(design, _comparison(solutions=("SOL-001",)), "agent")
    with pytest.raises(ValidationError, match="at least 2 items"):
        _comparison(criteria=["coût"])


def test_transition_requires_compared_alternatives(design, settings):
    add_solution(design, _solution(), "", "agent")
    check = check_solutions(design, settings)
    assert check.status == "BLOCKED" and "1 solution(s) active(s), minimum 2" in check.errors[0]
    assert "H2" in check.warnings[0]  # hypothèse testée par aucune solution

    add_solution(design, _solution(title="Preuves à divulgation nulle", addressed_hypotheses=["H2"]), "", "agent")
    with pytest.raises(TransitionError, match="non comparées"):
        design.transition(ResearchState.SCIENTIFIC_REVIEW, actor="agent", policy=settings.policy)
    comparison = set_comparison(design, _comparison(), "agent")
    assert comparison.solution_versions == {"SOL-001": 1, "SOL-002": 1}
    assert check_solutions(design, settings).status == "OK"
    assert design.transition(ResearchState.SCIENTIFIC_REVIEW, actor="agent", policy=settings.policy).state \
        == ResearchState.SCIENTIFIC_REVIEW


def test_revision_makes_comparison_stale(design, settings):
    _two_solutions(design)
    set_comparison(design, _comparison(), "agent")
    revise_solution(design, "SOL-002", _solution(title="ZK", risks=["Coût des preuves"]), "risque", "agent")
    assert "comparaison périmée" in check_solutions(design, settings).errors[0]
    assert json.loads((design.dir / "solutions.json").read_text())[0]["comparison_stale"] is True
    assert set_comparison(design, _comparison(), "agent").version == 2
    assert check_solutions(design, settings).status == "OK"


def test_withdrawn_solution_no_longer_counts(design, settings):
    _two_solutions(design)
    set_comparison(design, _comparison(), "agent")
    revise_solution(design, "SOL-002", _solution(title="ZK", status="withdrawn"), "irréaliste", "agent")
    errors = check_solutions(design, settings).errors
    assert any("minimum 2" in e for e in errors) and any("périmée" in e for e in errors)


def test_solution_history_is_immutable(design):
    _two_solutions(design)
    set_comparison(design, _comparison(), "agent")
    for statement in ("UPDATE solution_versions SET actor = 'x'", "DELETE FROM solution_evidence",
                      "DELETE FROM solutions", "UPDATE solution_comparisons SET actor = 'x'"):
        with pytest.raises(sqlite3.IntegrityError):
            design.db.conn.execute(statement)
