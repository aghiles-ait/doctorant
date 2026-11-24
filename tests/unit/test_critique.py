"""Étape 3c : revue critique indépendante, objections, réponses et transitions selon le verdict."""

import json
import sqlite3

import pytest
from pydantic import ValidationError
from test_gaps import _alignment, _contradictory_search, _draft, analysis  # noqa: F401 — fixtures partagées
from test_gate import human, ready, submitted  # noqa: F401
from test_questions import _hypothesis, _question, formulation  # noqa: F401
from test_review import _evidence, fetcher, included, repo, settings, with_fulltext  # noqa: F401
from test_solutions import _comparison, _solution, _two_solutions, design  # noqa: F401

from research_lab.critique import CritiqueError, check_critique, respond, submit_review
from research_lab.schemas.critique import ResponseDraft, ReviewDraft
from research_lab.solutions import revise_solution, set_comparison
from research_lab.storage.repositories import pages_path
from research_lab.workflow.state import ResearchState
from research_lab.workflow.transitions import TransitionError

S = ResearchState


@pytest.fixture
def reviewing(design, settings):
    """Deux solutions comparées pour RQ-001 ; état SCIENTIFIC_REVIEW, tour 1. Raisonnement : EV-001, EV-002."""
    _two_solutions(design)
    set_comparison(design, _comparison(), "agent")
    design.transition(S.SCIENTIFIC_REVIEW, actor="agent", policy=settings.policy)
    return design


MAJOR = {"severity": "major", "targets": ["SOL-002"], "statement": "Coût des preuves non évalué",
         "rationale": "Aucune preuve ne mesure ce coût."}
CRITICAL = MAJOR | {"severity": "critical", "targets": ["SOL-001"], "statement": "Le registre ne prouve rien"}


def _review(verdict="ACCEPTABLE", objections=(MAJOR,), verifications=None) -> ReviewDraft:
    return ReviewDraft.model_validate({
        "verdict": verdict,
        "summary": "Raisonnement cohérent, coût sous-estimé.",
        "objections": list(objections),
        "verifications": verifications or [
            {"evidence_id": "EV-001", "result": "supports", "note": "Extrait conforme."},
            {"evidence_id": "EV-002", "result": "partially_supports", "note": "Position, pas un résultat."},
        ],
    })


def _move(repo, settings, target):
    return repo.transition(target, actor="agent", policy=settings.policy)


def test_review_requires_scientific_review_state(design, settings):
    with pytest.raises(CritiqueError, match="SCIENTIFIC_REVIEW"):
        submit_review(design, settings, _review(), "scientific-reviewer")


def test_acceptable_review_leads_to_proposal_once_answered(reviewing, settings):
    review = submit_review(reviewing, settings, _review(), "scientific-reviewer")
    assert (review.round, review.objections[0].objection_id) == (1, "OBJ-001")
    assert review.solution_versions == {"SOL-001": 1, "SOL-002": 1} and "solutions.json" in review.reviewed_artifacts
    [exported] = json.loads((reviewing.dir / "scientific-review.json").read_text())
    assert exported["objections"][0]["response"] is None

    with pytest.raises(CritiqueError, match="déjà sa revue"):
        submit_review(reviewing, settings, _review(), "scientific-reviewer")
    with pytest.raises(TransitionError, match="ACCEPTABLE : passer à PROPOSAL_DRAFT"):
        _move(reviewing, settings, S.SOLUTION_DESIGN)
    with pytest.raises(TransitionError, match="sans réponse.*OBJ-001"):
        _move(reviewing, settings, S.PROPOSAL_DRAFT)
    assert check_critique(reviewing).status == "BLOCKED"

    respond(reviewing, "OBJ-001", ResponseDraft(action="accepted_limitation", response="Reporté dans les limites."), "agent")
    assert check_critique(reviewing).next_state == S.PROPOSAL_DRAFT
    assert _move(reviewing, settings, S.PROPOSAL_DRAFT).state == S.PROPOSAL_DRAFT


@pytest.mark.parametrize(("data", "message"), [
    ({"objections": [CRITICAL]}, "ACCEPTABLE incompatible avec une objection critique"),
    ({"verdict": "MAJOR_REVISION", "objections": [MAJOR | {"severity": "minor"}]}, "au moins une objection critique ou majeure"),
    ({"verifications": [{"evidence_id": "EV-001", "result": "does_not_support", "note": "n"}]}, "non probantes.*EV-001"),
    ({"verifications": [{"evidence_id": "EV-001", "result": "supports", "note": "n"}] * 2}, "plusieurs fois"),
    ({"objections": [MAJOR | {"targets": ["SOL-1"]}]}, "String should match pattern"),
])
def test_review_draft_must_be_consistent(data, message):
    with pytest.raises(ValidationError, match=message):
        _review(**data)


@pytest.mark.parametrize(("review", "message"), [
    (lambda: _review(objections=[MAJOR | {"targets": ["GAP-404", "RQ-001/H9"]}]), "cibles inconnues.*GAP-404, RQ-001/H9"),
    (lambda: _review(verifications=[{"evidence_id": "EV-001", "result": "supports", "note": "n"},
                                    {"evidence_id": "EV-003", "result": "supports", "note": "n"}]),
     "EV-003 : ne fait pas partie du raisonnement"),
    (lambda: _review(verifications=[{"evidence_id": "EV-001", "result": "supports", "note": "n"}]),
     "1 preuve\\(s\\) du raisonnement relue\\(s\\), minimum 2"),
])
def test_review_is_checked_against_project(reviewing, settings, review, message):
    with pytest.raises(CritiqueError, match=message):
        submit_review(reviewing, settings, review(), "scientific-reviewer")


def test_verified_evidence_is_rechecked_in_the_text(reviewing, settings):
    pages = pages_path(settings.papers_dir, "PAPER-001")
    pages.write_text(pages.read_text().replace("a", "o"))
    with pytest.raises(CritiqueError, match="EV-001 : .*modifié"):
        submit_review(reviewing, settings, _review(), "scientific-reviewer")


def test_major_revision_loop(reviewing, settings):
    submit_review(reviewing, settings, _review("MAJOR_REVISION", objections=[CRITICAL]), "scientific-reviewer")
    with pytest.raises(TransitionError, match="MAJOR_REVISION : retour à SOLUTION_DESIGN"):
        _move(reviewing, settings, S.PROPOSAL_DRAFT)
    assert check_critique(reviewing).next_state == S.SOLUTION_DESIGN
    _move(reviewing, settings, S.SOLUTION_DESIGN)

    with pytest.raises(TransitionError, match="sans réponse.*OBJ-001"):
        _move(reviewing, settings, S.SCIENTIFIC_REVIEW)
    revised = ResponseDraft(action="revised", response="Le registre est désormais signé et horodaté.")
    with pytest.raises(CritiqueError, match="SOL-001 n'a été révisée"):
        respond(reviewing, "OBJ-001", revised, "agent")
    revise_solution(reviewing, "SOL-001", _solution(risks=["Horodatage falsifiable"]), "objection OBJ-001", "agent")
    set_comparison(reviewing, _comparison(), "agent")
    respond(reviewing, "OBJ-001", revised, "agent")

    assert _move(reviewing, settings, S.SCIENTIFIC_REVIEW).state == S.SCIENTIFIC_REVIEW
    second = submit_review(reviewing, settings, _review(objections=[]), "scientific-reviewer")
    assert second.round == 2 and second.solution_versions["SOL-001"] == 2
    assert [r["round"] for r in json.loads((reviewing.dir / "scientific-review.json").read_text())] == [1, 2]


def test_revised_requires_a_question_or_solution_target(reviewing, settings):
    objection = MAJOR | {"targets": ["EV-002"], "statement": "Une position citée comme résultat"}
    submit_review(reviewing, settings, _review("INSUFFICIENT_EVIDENCE", objections=[objection]), "scientific-reviewer")
    with pytest.raises(CritiqueError, match="ne vise ni question ni solution"):
        respond(reviewing, "OBJ-001", ResponseDraft(action="revised", response="corrigé"), "agent")
    respond(reviewing, "OBJ-001", ResponseDraft(action="rebutted", response="EV-002 n'est pas cité comme résultat."), "agent")


def test_review_rounds_are_limited(reviewing, settings):
    policy = settings.policy.model_copy(update={"max_review_rounds": 1})
    submit_review(reviewing, settings, _review("MAJOR_REVISION"), "scientific-reviewer")
    reviewing.transition(S.SOLUTION_DESIGN, actor="agent", policy=policy)
    respond(reviewing, "OBJ-001", ResponseDraft(action="rebutted", response="Coût borné par EV-002."), "agent")
    with pytest.raises(TransitionError, match="en référer à l'humain"):
        reviewing.transition(S.SCIENTIFIC_REVIEW, actor="agent", policy=policy)


def test_review_records_are_immutable(reviewing, settings):
    submit_review(reviewing, settings, _review(), "scientific-reviewer")
    respond(reviewing, "OBJ-001", ResponseDraft(action="rebutted", response="r"), "agent")
    for statement in ("UPDATE scientific_reviews SET verdict = 'ACCEPTABLE'", "DELETE FROM scientific_reviews",
                      "UPDATE objections SET severity = 'minor'", "DELETE FROM objection_responses"):
        with pytest.raises(sqlite3.IntegrityError):
            reviewing.db.conn.execute(statement)
