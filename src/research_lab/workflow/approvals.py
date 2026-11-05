"""Gate 1 : soumission du dossier par l'agent, décision par un humain (spec §1.3, §6.2).

L'agent peut soumettre ; seul un humain décide. La décision exige un terminal interactif hors
de Claude Code, et n'est acceptée que si les livrables n'ont pas changé depuis la soumission.
"""

import os
import sys
from pathlib import Path

from research_lab.config import Settings
from research_lab.gaps import check_gaps
from research_lab.schemas.gate import Gate, GateDecision, GateDecisionType, GateSubmission
from research_lab.schemas.project import StateChange
from research_lab.storage.repositories import ProjectRepository, now, sha256
from research_lab.workflow.state import ResearchState

# Livrables dont l'humain valide le contenu à la Gate 1.
GATE_1_ARTIFACTS = ["scope.md", "literature-review.md", "evidence-matrix.json", "gaps.json", "alignment.json"]

_DECISION_TARGETS = {
    GateDecisionType.APPROVE: ResearchState.PROBLEM_FORMULATION,
    GateDecisionType.REVISE: ResearchState.LITERATURE_SEARCH,
}


class GateError(Exception):
    """Soumission ou décision refusée."""


def human_check_failure() -> str | None:
    """Raison pour laquelle la décision ne peut pas venir d'un humain, ou None.

    Garde-fou contre une approbation par l'agent : Claude Code définit CLAUDECODE dans ses
    commandes, qui ne disposent pas d'un terminal interactif. Ce n'est pas une authentification.
    """
    if os.environ.get("CLAUDECODE"):
        return "commande lancée depuis Claude Code : une gate est validée par un humain, dans son propre terminal"
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return "pas de terminal interactif : une gate est validée par un humain, dans son propre terminal"
    return None


def artifact_hashes(project_dir: Path) -> dict[str, str]:
    return {name: sha256((project_dir / name).read_bytes()) for name in GATE_1_ARTIFACTS if (project_dir / name).exists()}


def modified_artifacts(repo: ProjectRepository, submission: GateSubmission) -> list[str]:
    """Livrables modifiés, supprimés ou ajoutés depuis la soumission."""
    current = artifact_hashes(repo.dir)
    names = sorted(set(current) | set(submission.artifacts))
    return [n for n in names if current.get(n) != submission.artifacts.get(n)]


def latest_submission(repo: ProjectRepository) -> GateSubmission | None:
    submissions = repo.load_gate_submissions(Gate.GATE_1)
    return submissions[-1] if submissions else None


def submit_gate_1(repo: ProjectRepository, settings: Settings, actor: str) -> GateSubmission:
    """Fige le dossier (empreintes des livrables, versions des gaps) et met le projet en attente de décision."""
    project = repo.load_project()
    if project.state != ResearchState.GAP_ANALYSIS:
        raise GateError(f"Le projet est à l'état {project.state} ; la soumission exige {ResearchState.GAP_ANALYSIS}")
    check = check_gaps(repo, settings)
    if check.status == "BLOCKED":
        raise GateError("`gap check` est BLOCKED : " + " ; ".join(check.errors))
    repo.export()  # les empreintes portent sur des exports à jour
    if missing := [n for n in GATE_1_ARTIFACTS if not (repo.dir / n).exists()]:
        raise GateError(f"Livrables absents : {', '.join(missing)}")

    previous = latest_submission(repo)
    timestamp = now()
    submission = GateSubmission(
        project_id=repo.project_id,
        gate=Gate.GATE_1,
        round=previous.round + 1 if previous else 1,
        submitted_at=timestamp,
        actor=actor,
        artifacts=artifact_hashes(repo.dir),
        gap_versions={g.gap_id: g.version for g in repo.load_gaps() if g.active},
        check_status=check.status,
        check_warnings=check.warnings,
    )
    change = StateChange(from_state=project.state, to_state=ResearchState.AWAITING_GATE_1, at=timestamp, actor=actor)
    repo.record_gate_submission(submission, change)
    return submission


def decide_gate_1(
    repo: ProjectRepository,
    decision: GateDecisionType,
    comment: str,
    approver: str,
    selected_gaps: list[str] | None = None,
) -> GateDecision:
    """Enregistre la décision humaine et applique la transition correspondante, en une transaction.

    approve : les gaps retenus (au moins un, parmi ceux soumis) passent à la formulation du problème ;
    revise  : retour à la recherche bibliographique ; gaps, preuves et corpus sont conservés.
    """
    if reason := human_check_failure():
        raise GateError(reason)
    project = repo.load_project()
    if project.state != ResearchState.AWAITING_GATE_1:
        raise GateError(f"Le projet est à l'état {project.state}, il n'attend pas la Gate 1")
    submission = latest_submission(repo)
    if submission is None:
        raise GateError("Aucune soumission enregistrée")
    if not comment.strip():
        raise GateError("La décision exige un commentaire (justification, ou instructions pour la révision)")

    selected = list(dict.fromkeys(selected_gaps or []))
    if unknown := [g for g in selected if g not in submission.gap_versions]:
        raise GateError(f"Gaps absents du dossier soumis : {', '.join(unknown)}")
    modified = modified_artifacts(repo, submission)
    if decision == GateDecisionType.APPROVE and modified:
        raise GateError(
            f"Livrables modifiés depuis la soumission : {', '.join(modified)}. "
            "Ce qui serait approuvé n'est plus ce qui a été soumis : restaurer les fichiers ou demander une révision"
        )

    timestamp = now()
    try:
        record = GateDecision(
            project_id=repo.project_id, gate=Gate.GATE_1, round=submission.round, decision=decision,
            approver=approver, at=timestamp, comment=comment.strip(),
            selected_gaps={g: submission.gap_versions[g] for g in selected},
            artifacts_verified=not modified, modified_artifacts=modified,
        )
    except ValueError as exc:
        raise GateError(str(exc)) from exc
    change = StateChange(
        from_state=project.state, to_state=_DECISION_TARGETS[decision], at=timestamp, actor=approver
    )
    repo.record_gate_decision(record, change)
    return record
