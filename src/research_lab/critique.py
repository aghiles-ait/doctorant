"""Opérations de la revue critique (skill scientific-critic, agent scientific-reviewer).

Le reviewer enregistre une revue par tour (chaque passage à SCIENTIFIC_REVIEW) ; le doctorant
répond ensuite aux objections. Le verdict détermine la transition suivante (workflow/transitions.py).
"""

from dataclasses import dataclass, field

from research_lab.config import Settings
from research_lab.schemas.critique import (
    Objection,
    ObjectionResponse,
    ResponseDraft,
    ReviewDraft,
    ScientificReview,
    Verdict,
)
from research_lab.schemas.evidence import Evidence, EvidenceLocation
from research_lab.storage.repositories import (
    FulltextTampered,
    ProjectRepository,
    next_objection_id,
    now,
    read_pages,
    sha256,
)
from research_lab.validation.critique import check_response, check_review, reasoning_evidence, unanswered_objections
from research_lab.validation.evidence import quote_in
from research_lab.workflow.state import ResearchState

# Livrables dont la revue fige l'empreinte : ce qui a été revu reste identifiable.
REVIEWED_ARTIFACTS = [
    "literature-review.md", "evidence-matrix.json", "gaps.json", "research-questions.json", "solutions.json",
]


class CritiqueError(Exception):
    """Revue ou réponse refusée."""


def review_round(repo: ProjectRepository) -> int:
    """Numéro du tour de revue : nombre de passages à l'état SCIENTIFIC_REVIEW."""
    return sum(c.to_state == ResearchState.SCIENTIFIC_REVIEW for c in repo.load_project().history)


def current_review(repo: ProjectRepository) -> ScientificReview | None:
    """Revue du tour en cours, si elle a été enregistrée."""
    reviews = repo.load_reviews()
    return reviews[-1] if reviews and reviews[-1].round == review_round(repo) else None


def _reverify(repo: ProjectRepository, settings: Settings, item: Evidence) -> str | None:
    """Contrôle mécanique : l'extrait figure toujours dans le texte de la publication, inchangé."""
    if item.location == EvidenceLocation.FULL_TEXT:
        try:
            pages, digest = read_pages(repo.db, settings.papers_dir, item.paper_id)
        except (FileNotFoundError, FulltextTampered) as exc:
            return f"{item.evidence_id} : {exc}"
        if digest != item.text_sha256:
            return f"{item.evidence_id} : le texte de {item.paper_id} a changé depuis l'enregistrement de la preuve"
        text = pages[item.page - 1] if item.page and item.page <= len(pages) else ""
    else:
        paper = repo.get_paper(item.paper_id)
        text = paper.abstract or "" if paper else ""
    if not quote_in(item.quote, text):
        return f"{item.evidence_id} : l'extrait n'est plus retrouvé dans {item.paper_id}"
    return None


def _hashes(repo: ProjectRepository) -> dict[str, str]:
    return {n: sha256((repo.dir / n).read_bytes()) for n in REVIEWED_ARTIFACTS if (repo.dir / n).exists()}


def submit_review(repo: ProjectRepository, settings: Settings, draft: ReviewDraft, reviewer: str) -> ScientificReview:
    """Enregistre la revue du tour en cours ; elle est immuable."""
    project = repo.load_project()
    if project.state != ResearchState.SCIENTIFIC_REVIEW:
        raise CritiqueError(f"Le projet est à l'état {project.state} ; la revue exige {ResearchState.SCIENTIFIC_REVIEW}")
    round_number = review_round(repo)
    if current_review(repo) is not None:
        raise CritiqueError(f"Le tour de revue {round_number} a déjà sa revue ; une revue ne se modifie pas")

    gaps, questions, solutions = repo.load_gaps(), repo.load_questions(), repo.load_solutions()
    evidence = {e.evidence_id: e for e in repo.load_evidence()}
    chain = reasoning_evidence(gaps, repo.approved_gaps(), questions, solutions)
    errors = check_review(
        draft, gaps=gaps, questions=questions, solutions=solutions, evidence=evidence,
        paper_ids=repo.paper_ids(), chain=chain, min_verified=settings.policy.min_verified_evidence,
    )
    for verification in draft.verifications:
        item = evidence.get(verification.evidence_id)
        if item is None or not item.active:
            errors.append(f"{verification.evidence_id} n'est pas une preuve active du projet")
        elif error := _reverify(repo, settings, item):
            errors.append(error)
    if errors:
        raise CritiqueError(" ; ".join(errors))

    repo.export()  # les empreintes portent sur des exports à jour
    first = int(next_objection_id(repo.db).split("-")[1])
    review = ScientificReview(
        project_id=repo.project_id, round=round_number, verdict=draft.verdict, summary=draft.summary,
        objections=[
            Objection(**o.model_dump(), objection_id=f"OBJ-{first + i:03d}", round=round_number)
            for i, o in enumerate(draft.objections)
        ],
        verifications=draft.verifications, reviewer=reviewer, at=now(), reviewed_artifacts=_hashes(repo),
        question_versions={q.question_id: q.version for q in questions if q.active},
        solution_versions={s.solution_id: s.version for s in solutions if s.active},
    )
    repo.record_review(review)
    return review


def respond(repo: ProjectRepository, objection_id: str, draft: ResponseDraft, actor: str) -> ObjectionResponse:
    """Réponse du doctorant à une objection ; une nouvelle réponse remplace la précédente (historique conservé)."""
    state = repo.load_project().state
    if state not in (ResearchState.SOLUTION_DESIGN, ResearchState.SCIENTIFIC_REVIEW):
        raise CritiqueError(f"Le projet est à l'état {state} ; répondre aux objections exige SOLUTION_DESIGN ou SCIENTIFIC_REVIEW")
    found = next(((r, o) for r in repo.load_reviews() for o in r.objections if o.objection_id == objection_id), None)
    if found is None:
        raise CritiqueError(f"{objection_id} n'existe pas dans le projet {repo.project_id}")
    review, objection = found
    if errors := check_response(draft, objection, review, repo.load_questions(), repo.load_solutions()):
        raise CritiqueError(" ; ".join(errors))
    response = ObjectionResponse(**draft.model_dump(), objection_id=objection_id, actor=actor, at=now())
    repo.add_response(response)
    return response


@dataclass
class CritiqueCheck:
    status: str = "OK"  # OK ou BLOCKED
    round: int = 0
    verdict: Verdict | None = None
    next_state: ResearchState | None = None
    errors: list[str] = field(default_factory=list)


def check_critique(repo: ProjectRepository) -> CritiqueCheck:
    """Où en est la revue : verdict du tour, objections sans réponse, étape suivante."""
    state = repo.load_project().state
    reviews = repo.load_reviews()
    latest = reviews[-1] if reviews else None
    check = CritiqueCheck(round=review_round(repo), verdict=latest.verdict if latest else None)
    unanswered = unanswered_objections(latest, repo.load_responses())
    if state == ResearchState.SCIENTIFIC_REVIEW:
        review = current_review(repo)
        if review is None:
            check.errors.append(f"tour {check.round} : en attente de la revue (agent scientific-reviewer)")
        elif review.verdict == Verdict.ACCEPTABLE:
            check.next_state = ResearchState.PROPOSAL_DRAFT
        else:
            check.next_state = ResearchState.SOLUTION_DESIGN
            unanswered = []  # les réponses se donnent après le retour à la conception
    elif state == ResearchState.SOLUTION_DESIGN:
        check.next_state = ResearchState.SCIENTIFIC_REVIEW
    if unanswered:
        check.errors.append(f"objections critiques ou majeures sans réponse : {', '.join(unanswered)}")
    if check.errors:
        check.status = "BLOCKED"
    return check
