"""Règles déterministes de la revue critique (skill scientific-critic, spec §8).

Le code ne juge pas la pertinence d'une objection ; il vérifie que ce qu'elle vise existe, que le
reviewer a relu un nombre suffisant de preuves de la chaîne de raisonnement, que le verdict est
cohérent avec les objections, et qu'une réponse « révisé » correspond à une révision réelle.
"""

from research_lab.schemas.critique import (
    ANSWER_REQUIRED,
    Objection,
    ObjectionResponse,
    ResponseAction,
    ResponseDraft,
    ReviewDraft,
    ScientificReview,
)
from research_lab.schemas.evidence import Evidence
from research_lab.schemas.gap import Gap
from research_lab.schemas.question import ResearchQuestion
from research_lab.schemas.solution import Solution


def reasoning_evidence(
    gaps: list[Gap], approved_gaps: dict[str, int], questions: list[ResearchQuestion], solutions: list[Solution]
) -> set[str]:
    """Preuves sur lesquelles repose le raisonnement revu : gaps retenus, hypothèses et solutions actives."""
    cited = {e for g in gaps if g.gap_id in approved_gaps for e in [*g.supporting_evidence, *g.contradicting_evidence]}
    cited |= {e for q in questions if q.active for h in q.hypotheses for e in h.evidence}
    cited |= {e for s in solutions if s.active for e in s.evidence}
    return cited


def check_review(
    draft: ReviewDraft,
    *,
    gaps: list[Gap],
    questions: list[ResearchQuestion],
    solutions: list[Solution],
    evidence: dict[str, Evidence],
    paper_ids: set[str],
    chain: set[str],
    min_verified: int,
) -> list[str]:
    """Erreurs d'une revue au regard du projet : cibles existantes, vérifications suffisantes."""
    errors = []
    known = {g.gap_id for g in gaps} | {s.solution_id for s in solutions} | set(evidence) | paper_ids
    known |= {q.question_id for q in questions}
    known |= {f"{q.question_id}/{h.hypothesis_id}" for q in questions for h in q.hypotheses}
    for number, objection in enumerate(draft.objections, start=1):
        if unknown := [t for t in objection.targets if t not in known]:
            errors.append(f"objection {number} : cibles inconnues dans ce projet : {', '.join(unknown)}")
    for verification in draft.verifications:
        if verification.evidence_id not in chain:
            errors.append(f"{verification.evidence_id} : ne fait pas partie du raisonnement revu (gaps retenus, hypothèses, solutions)")
    required = min(min_verified, len(chain))
    verified = {v.evidence_id for v in draft.verifications} & chain
    if len(verified) < required:
        errors.append(f"{len(verified)} preuve(s) du raisonnement relue(s), minimum {required}")
    return errors


def check_response(
    draft: ResponseDraft,
    objection: Objection,
    review: ScientificReview,
    questions: list[ResearchQuestion],
    solutions: list[Solution],
) -> list[str]:
    """Une réponse « revised » exige qu'une question ou solution visée ait changé de version depuis la revue."""
    if draft.action != ResponseAction.REVISED:
        return []
    current = {q.question_id: q.version for q in questions} | {s.solution_id: s.version for s in solutions}
    reviewed = review.question_versions | review.solution_versions
    revisable = {t.split("/")[0] for t in objection.targets if t.startswith(("RQ-", "SOL-"))}
    if not revisable:
        return [f"{objection.objection_id} ne vise ni question ni solution : répondre rebutted ou accepted_limitation"]
    if not any(current.get(t, 0) > reviewed.get(t, 0) for t in revisable):
        return [f"{objection.objection_id} : aucune de {', '.join(sorted(revisable))} n'a été révisée depuis la revue"]
    return []


def unanswered_objections(review: ScientificReview | None, responses: dict[str, ObjectionResponse]) -> list[str]:
    """Objections critiques et majeures de la revue sans réponse."""
    if review is None:
        return []
    return [o.objection_id for o in review.objections if o.severity in ANSWER_REQUIRED and o.objection_id not in responses]
