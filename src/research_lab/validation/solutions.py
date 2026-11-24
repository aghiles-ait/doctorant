"""Règles déterministes de la conception des solutions (skill solution-architect).

Le code ne juge pas si une solution est bonne ; il vérifie qu'elle répond à une question active,
qu'elle cite des hypothèses de cette question et des preuves existantes, que chaque question a
plusieurs alternatives et que leur comparaison couvre toutes les alternatives sur tous les critères.
"""

from dataclasses import dataclass, field

from research_lab.schemas.evidence import Evidence
from research_lab.schemas.question import ResearchQuestion
from research_lab.schemas.solution import Comparison, ComparisonDraft, Solution, SolutionDraft


def check_solution(
    draft: SolutionDraft, questions: dict[str, ResearchQuestion], evidence: dict[str, Evidence]
) -> list[str]:
    """Erreurs d'une solution au regard des questions et des preuves du projet."""
    errors = []
    question = questions.get(draft.question_id)
    if question is None:
        errors.append(f"{draft.question_id} n'existe pas dans ce projet")
    elif not question.active:
        errors.append(f"{draft.question_id} est retirée")
    else:
        known = {h.hypothesis_id for h in question.hypotheses}
        if unknown := [h for h in draft.addressed_hypotheses if h not in known]:
            errors.append(f"hypothèses absentes de {draft.question_id} : {', '.join(unknown)}")
    for evidence_id in draft.evidence:
        item = evidence.get(evidence_id)
        if item is None:
            errors.append(f"{evidence_id} n'existe pas dans ce projet")
        elif not item.active:
            errors.append(f"{evidence_id} est retirée ({item.withdrawn_reason})")
    return errors


def check_comparison(draft: ComparisonDraft, solutions: list[Solution]) -> list[str]:
    """Erreurs d'une comparaison au regard des solutions actives de sa question."""
    errors = []
    active = {s.solution_id for s in solutions if s.active and s.question_id == draft.question_id}
    if len(active) < 2:
        errors.append(f"{draft.question_id} : une comparaison porte sur au moins deux solutions actives")
    if missing := sorted(active - set(draft.assessments)):
        errors.append(f"solutions non évaluées : {', '.join(missing)}")
    if unknown := sorted(set(draft.assessments) - active):
        errors.append(f"solutions inconnues ou retirées, ou d'une autre question : {', '.join(unknown)}")
    for solution_id, assessment in sorted(draft.assessments.items()):
        if missing := [c for c in draft.criteria if c not in assessment]:
            errors.append(f"{solution_id} : critères non évalués : {', '.join(missing)}")
        if extra := sorted(set(assessment) - set(draft.criteria)):
            errors.append(f"{solution_id} : critères inconnus : {', '.join(extra)}")
    if draft.recommendation and draft.recommendation not in active:
        errors.append(f"recommandation {draft.recommendation} : pas une solution active de {draft.question_id}")
    return errors


@dataclass
class SolutionCheck:
    status: str = "OK"  # OK ou BLOCKED
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check_solution_design(
    questions: list[ResearchQuestion],
    solutions: list[Solution],
    comparisons: dict[str, Comparison],
    evidence: list[Evidence],
    min_alternatives: int,
) -> SolutionCheck:
    """Contrôle les solutions avant la revue critique."""
    check = SolutionCheck()
    by_question = {q.question_id: q for q in questions}
    by_evidence = {e.evidence_id: e for e in evidence}
    active_questions = [q for q in questions if q.active]
    if not active_questions:
        check.errors.append("aucune question de recherche active")

    for solution in solutions:
        if solution.active:
            check.errors.extend(
                f"{solution.solution_id} : {e}" for e in check_solution(solution, by_question, by_evidence)
            )

    for question in active_questions:
        alternatives = [s for s in solutions if s.active and s.question_id == question.question_id]
        if len(alternatives) < min_alternatives:
            check.errors.append(
                f"{question.question_id} : {len(alternatives)} solution(s) active(s), "
                f"minimum {min_alternatives} alternatives à comparer"
            )
        comparison = comparisons.get(question.question_id)
        if comparison is None:
            check.errors.append(f"{question.question_id} : solutions non comparées (`solution compare`)")
        elif comparison.solution_versions != {s.solution_id: s.version for s in alternatives}:
            check.errors.append(f"{question.question_id} : comparaison périmée (solutions ajoutées, révisées ou retirées depuis)")
        addressed = {h for s in alternatives for h in s.addressed_hypotheses}
        if untested := [h.hypothesis_id for h in question.hypotheses if h.hypothesis_id not in addressed]:
            check.warnings.append(f"{question.question_id} : hypothèses testées par aucune solution : {', '.join(untested)}")

    if check.errors:
        check.status = "BLOCKED"
    return check
