"""Opérations de la conception des solutions (skill solution-architect) : solutions et comparaisons."""

from research_lab.config import Settings
from research_lab.schemas.solution import Comparison, ComparisonDraft, Solution, SolutionDraft
from research_lab.storage.repositories import ProjectRepository, next_solution_id, now
from research_lab.validation.solutions import SolutionCheck, check_comparison, check_solution, check_solution_design
from research_lab.workflow.state import ResearchState


class SolutionError(Exception):
    """Opération refusée : état du projet, solution ou comparaison invalide."""


def _require_design(repo: ProjectRepository) -> None:
    state = repo.load_project().state
    if state != ResearchState.SOLUTION_DESIGN:
        raise SolutionError(f"Le projet est à l'état {state} ; cette opération exige {ResearchState.SOLUTION_DESIGN}")


def _validate(repo: ProjectRepository, draft: SolutionDraft) -> None:
    questions = {q.question_id: q for q in repo.load_questions()}
    evidence = {e.evidence_id: e for e in repo.load_evidence()}
    if errors := check_solution(draft, questions, evidence):
        raise SolutionError(" ; ".join(errors))


def add_solution(repo: ProjectRepository, draft: SolutionDraft, reason: str, actor: str) -> Solution:
    """Crée une solution (version 1) pour une question active."""
    _require_design(repo)
    _validate(repo, draft)
    timestamp = now()
    solution = Solution(
        **draft.model_dump(), solution_id=next_solution_id(repo.db), project_id=repo.project_id, version=1,
        created_at=timestamp, updated_at=timestamp, actor=actor, reason=reason.strip() or "création",
    )
    repo.save_solution_version(solution)
    return solution


def revise_solution(repo: ProjectRepository, solution_id: str, draft: SolutionDraft, reason: str, actor: str) -> Solution:
    """Remplace le contenu d'une solution par une nouvelle version ; la comparaison de sa question devient périmée."""
    _require_design(repo)
    if not reason.strip():
        raise SolutionError("Une révision exige une raison")
    current = next((s for s in repo.load_solutions() if s.solution_id == solution_id), None)
    if current is None:
        raise SolutionError(f"{solution_id} n'existe pas dans le projet {repo.project_id}")
    if draft.question_id != current.question_id:
        raise SolutionError(f"{solution_id} répond à {current.question_id} : créer une nouvelle solution pour une autre question")
    if draft == SolutionDraft.model_validate(current.model_dump(include=set(SolutionDraft.model_fields))):
        raise SolutionError(f"Aucun changement par rapport à la version {current.version} de {solution_id}")
    _validate(repo, draft)
    solution = Solution(
        **draft.model_dump(), solution_id=solution_id, project_id=repo.project_id, version=current.version + 1,
        created_at=current.created_at, updated_at=now(), actor=actor, reason=reason.strip(),
    )
    repo.save_solution_version(solution)
    return solution


def set_comparison(repo: ProjectRepository, draft: ComparisonDraft, actor: str) -> Comparison:
    """Enregistre la comparaison des solutions actives d'une question, en figeant leurs versions."""
    _require_design(repo)
    question = next((q for q in repo.load_questions() if q.question_id == draft.question_id), None)
    if question is None or not question.active:
        raise SolutionError(f"{draft.question_id} n'est pas une question active du projet")
    solutions = repo.load_solutions()
    if errors := check_comparison(draft, solutions):
        raise SolutionError(" ; ".join(errors))
    previous = repo.load_comparisons().get(draft.question_id)
    comparison = Comparison(
        **draft.model_dump(), version=previous.version + 1 if previous else 1,
        solution_versions={s.solution_id: s.version for s in solutions if s.solution_id in draft.assessments},
        actor=actor, at=now(),
    )
    repo.add_comparison(comparison)
    return comparison


def check_solutions(repo: ProjectRepository, settings: Settings) -> SolutionCheck:
    return check_solution_design(
        repo.load_questions(), repo.load_solutions(), repo.load_comparisons(), repo.load_evidence(),
        settings.policy.min_solution_alternatives,
    )
