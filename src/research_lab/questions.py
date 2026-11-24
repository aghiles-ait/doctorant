"""Opérations de la formulation du problème (skill problem-formulation) : questions et hypothèses."""

from research_lab.schemas.question import QuestionDraft, ResearchQuestion
from research_lab.storage.repositories import ProjectRepository, next_question_id, now
from research_lab.validation.questions import QuestionCheck, check_problem_formulation, check_question
from research_lab.workflow.state import ResearchState


class QuestionError(Exception):
    """Opération refusée : état du projet ou question invalide."""


# Les questions se formulent en PROBLEM_FORMULATION ; elles restent révisables pendant la conception des
# solutions, pour répondre aux objections de la revue critique qui portent sur les hypothèses.
_QUESTION_STATES = (ResearchState.PROBLEM_FORMULATION, ResearchState.SOLUTION_DESIGN)


def _require_formulation(repo: ProjectRepository) -> None:
    state = repo.load_project().state
    if state not in _QUESTION_STATES:
        raise QuestionError(f"Le projet est à l'état {state} ; cette opération exige {' ou '.join(_QUESTION_STATES)}")


def _validate(repo: ProjectRepository, draft: QuestionDraft) -> None:
    evidence = {e.evidence_id: e for e in repo.load_evidence()}
    if errors := check_question(draft, repo.approved_gaps(), evidence):
        raise QuestionError(" ; ".join(errors))


def add_question(repo: ProjectRepository, draft: QuestionDraft, reason: str, actor: str) -> ResearchQuestion:
    """Crée une question (version 1) rattachée à des gaps retenus à la Gate 1."""
    _require_formulation(repo)
    _validate(repo, draft)
    timestamp = now()
    question = ResearchQuestion(
        **draft.model_dump(), question_id=next_question_id(repo.db), project_id=repo.project_id, version=1,
        created_at=timestamp, updated_at=timestamp, actor=actor, reason=reason.strip() or "création",
    )
    repo.save_question_version(question)
    return question


def revise_question(
    repo: ProjectRepository, question_id: str, draft: QuestionDraft, reason: str, actor: str
) -> ResearchQuestion:
    """Remplace le contenu d'une question par une nouvelle version ; l'identifiant et l'historique sont conservés."""
    _require_formulation(repo)
    if not reason.strip():
        raise QuestionError("Une révision exige une raison")
    current = next((q for q in repo.load_questions() if q.question_id == question_id), None)
    if current is None:
        raise QuestionError(f"{question_id} n'existe pas dans le projet {repo.project_id}")
    if draft == QuestionDraft.model_validate(current.model_dump(include=set(QuestionDraft.model_fields))):
        raise QuestionError(f"Aucun changement par rapport à la version {current.version} de {question_id}")
    _validate(repo, draft)
    question = ResearchQuestion(
        **draft.model_dump(), question_id=question_id, project_id=repo.project_id, version=current.version + 1,
        created_at=current.created_at, updated_at=now(), actor=actor, reason=reason.strip(),
    )
    repo.save_question_version(question)
    return question


def check_questions(repo: ProjectRepository) -> QuestionCheck:
    return check_problem_formulation(repo.load_questions(), repo.approved_gaps(), repo.load_evidence())
