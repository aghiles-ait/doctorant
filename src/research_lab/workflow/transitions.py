"""Transitions du workflow, contrôlées par le programme (spec §6).

Chaque transition autorisée a une précondition qui examine l'état vérifiable du projet
(`ProjectFacts`). Les transitions des gates passent par workflow/approvals.py ; les autres
transitions non listées lèvent une erreur explicite.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from research_lab.workflow.state import ResearchState as S


class TransitionError(Exception):
    pass


@dataclass(frozen=True)
class ProjectFacts:
    project_dir: Path
    corpus_status: str  # OK, NEEDS_MORE_RESEARCH ou BLOCKED (research-lab corpus check)
    candidate_count: int
    included_count: int
    without_fulltext_attempt: list[str]
    active_evidence_count: int
    review_errors: list[str]  # contrôle des citations de literature-review.md
    question_errors: list[str]  # contrôle des questions de recherche (research-lab question check)
    solution_errors: list[str]  # contrôle des solutions et de leur comparaison (research-lab solution check)
    review_rounds: int  # passages à SCIENTIFIC_REVIEW depuis la dernière révision demandée à la Gate 2
    max_review_rounds: int
    current_review_verdict: str | None  # verdict de la revue du tour en cours, s'il y en a une
    unanswered_objections: list[str]  # objections critiques ou majeures de la dernière revue, sans réponse


def _scope_written(facts: ProjectFacts) -> str | None:
    scope = facts.project_dir / "scope.md"
    if not scope.exists() or not scope.read_text(encoding="utf-8").strip():
        return "scope.md est absent ou vide : le périmètre doit être défini avant la recherche"
    return None


def _corpus_ready(facts: ProjectFacts) -> str | None:
    if facts.corpus_status != "OK":
        return f"le corpus doit être au statut OK (actuellement {facts.corpus_status}, voir `research-lab corpus check`)"
    return None


def _review_complete(facts: ProjectFacts) -> str | None:
    problems = []
    if facts.candidate_count:
        problems.append(f"{facts.candidate_count} publications ne sont pas encore triées")
    if not facts.included_count:
        problems.append("aucune publication incluse")
    if facts.without_fulltext_attempt:
        problems.append(f"texte intégral jamais recherché pour {', '.join(facts.without_fulltext_attempt)}")
    if not facts.active_evidence_count:
        problems.append("aucune preuve enregistrée")
    problems.extend(f"literature-review.md : {e}" for e in facts.review_errors)
    return " ; ".join(problems) or None


def _questions_ready(facts: ProjectFacts) -> str | None:
    if facts.question_errors:
        return "questions de recherche : " + " ; ".join(facts.question_errors)
    return None


def _ready_for_review(facts: ProjectFacts) -> str | None:
    """Questions et solutions contrôlées, objections de la revue précédente traitées, tours non épuisés."""
    problems = [f"questions de recherche : {e}" for e in facts.question_errors]
    problems += [f"solutions : {e}" for e in facts.solution_errors]
    if facts.unanswered_objections:
        problems.append(f"objections sans réponse (`critique respond`) : {', '.join(facts.unanswered_objections)}")
    if facts.review_rounds >= facts.max_review_rounds:
        problems.append(
            f"{facts.review_rounds} tours de revue effectués (maximum {facts.max_review_rounds}) : "
            "en référer à l'humain"
        )
    return " ; ".join(problems) or None


def _review_accepted(facts: ProjectFacts) -> str | None:
    if facts.current_review_verdict is None:
        return "aucune revue pour ce tour (`critique submit`, par l'agent scientific-reviewer)"
    if facts.current_review_verdict != "ACCEPTABLE":
        return f"verdict {facts.current_review_verdict} : retour à SOLUTION_DESIGN"
    if facts.unanswered_objections:
        return f"objections sans réponse (`critique respond`) : {', '.join(facts.unanswered_objections)}"
    return None


def _review_rejected(facts: ProjectFacts) -> str | None:
    if facts.current_review_verdict is None:
        return "aucune revue pour ce tour (`critique submit`, par l'agent scientific-reviewer)"
    if facts.current_review_verdict == "ACCEPTABLE":
        return "verdict ACCEPTABLE : passer à PROPOSAL_DRAFT"
    return None


# (origine, destination) -> précondition renvoyant un message d'erreur ou None
_TRANSITIONS: dict[tuple[S, S], Callable[[ProjectFacts], str | None]] = {
    (S.NEW, S.SCOPING): lambda _: None,
    (S.SCOPING, S.LITERATURE_SEARCH): _scope_written,
    (S.LITERATURE_SEARCH, S.LITERATURE_REVIEW): _corpus_ready,
    (S.LITERATURE_REVIEW, S.GAP_ANALYSIS): _review_complete,
    (S.PROBLEM_FORMULATION, S.SOLUTION_DESIGN): _questions_ready,
    (S.SOLUTION_DESIGN, S.SCIENTIFIC_REVIEW): _ready_for_review,
    (S.SCIENTIFIC_REVIEW, S.PROPOSAL_DRAFT): _review_accepted,
    (S.SCIENTIFIC_REVIEW, S.SOLUTION_DESIGN): _review_rejected,
}


# Transitions des gates : elles ne passent jamais par `project transition`, mais par la soumission
# et la décision humaine (workflow/approvals.py), qui enregistrent aussi le dossier et la décision.
GATE_TRANSITIONS: dict[tuple[S, S], str] = {
    (S.GAP_ANALYSIS, S.AWAITING_GATE_1): "Gate 1 : research-lab gate submit",
    (S.AWAITING_GATE_1, S.PROBLEM_FORMULATION): "Gate 1 : research-lab gate approve (humain, terminal interactif)",
    (S.AWAITING_GATE_1, S.LITERATURE_SEARCH): "Gate 1 : research-lab gate revise (humain, terminal interactif)",
    (S.PROPOSAL_DRAFT, S.AWAITING_GATE_2): "Gate 2 : research-lab gate submit",
    (S.AWAITING_GATE_2, S.COMPLETED): "Gate 2 : research-lab gate approve (humain, terminal interactif)",
    (S.AWAITING_GATE_2, S.SOLUTION_DESIGN): "Gate 2 : research-lab gate revise (humain, terminal interactif)",
}


def check_transition(current: S, target: S, facts: ProjectFacts) -> None:
    if command := GATE_TRANSITIONS.get((current, target)):
        raise TransitionError(f"Transition {current} → {target} réservée à la {command.replace(' : ', ' : `')}`")
    precondition = _TRANSITIONS.get((current, target))
    if precondition is None:
        raise TransitionError(f"Transition {current} → {target} non autorisée (ou pas encore implémentée)")
    if (error := precondition(facts)) is not None:
        raise TransitionError(error)
