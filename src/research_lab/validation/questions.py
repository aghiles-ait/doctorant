"""Règles déterministes de la formulation du problème (skill problem-formulation, spec Q4).

Le code ne juge pas si une hypothèse est pertinente ni réellement réfutable ; il vérifie que la
question répond aux gaps retenus par l'humain à la Gate 1, que chaque hypothèse déclare une
prédiction, un critère de réfutation distinct, une méthode de test et des métriques, et que les
preuves citées existent.
"""

from dataclasses import dataclass, field

from research_lab.schemas.evidence import Evidence
from research_lab.schemas.question import QuestionDraft, ResearchQuestion


def check_question(draft: QuestionDraft, approved_gaps: dict[str, int], evidence: dict[str, Evidence]) -> list[str]:
    """Erreurs d'une question au regard des gaps retenus à la Gate 1 et des preuves du projet."""
    errors = []
    retained = ", ".join(sorted(approved_gaps)) or "aucun"
    for gap_id in draft.gap_ids:
        if gap_id not in approved_gaps:
            errors.append(f"{gap_id} n'a pas été retenu à la Gate 1 (gaps retenus : {retained})")
    for hypothesis in draft.hypotheses:
        for evidence_id in hypothesis.evidence:
            item = evidence.get(evidence_id)
            if item is None:
                errors.append(f"{hypothesis.hypothesis_id} : {evidence_id} n'existe pas dans ce projet")
            elif not item.active:
                errors.append(f"{hypothesis.hypothesis_id} : {evidence_id} est retirée ({item.withdrawn_reason})")
    return errors


@dataclass
class QuestionCheck:
    status: str = "OK"  # OK ou BLOCKED
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check_problem_formulation(
    questions: list[ResearchQuestion], approved_gaps: dict[str, int], evidence: list[Evidence]
) -> QuestionCheck:
    """Contrôle les questions actives avant la conception des solutions."""
    check = QuestionCheck()
    by_id = {e.evidence_id: e for e in evidence}
    if not approved_gaps:
        check.errors.append("aucun gap retenu à la Gate 1")
    active = [q for q in questions if q.active]
    if not active:
        check.errors.append("aucune question de recherche active")
    for question in active:
        check.errors.extend(f"{question.question_id} : {e}" for e in check_question(question, approved_gaps, by_id))
    covered = {gap_id for q in active for gap_id in q.gap_ids}
    if missing := sorted(set(approved_gaps) - covered):
        check.errors.append(f"gaps retenus à la Gate 1 sans question : {', '.join(missing)}")
    if check.errors:
        check.status = "BLOCKED"
    return check
