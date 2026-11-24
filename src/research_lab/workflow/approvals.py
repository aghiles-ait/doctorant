"""Gates 1 et 2 : soumission du dossier par l'agent, décision par un humain (spec §1.3, §6.2).

L'agent peut soumettre ; seul un humain décide. La décision exige un terminal interactif hors
de Claude Code, et une approbation n'est acceptée que si les livrables n'ont pas changé depuis
la soumission.
"""

import os
import sys
from pathlib import Path

from research_lab.config import Settings
from research_lab.gaps import check_gaps
from research_lab.proposal import check_proposal_file
from research_lab.schemas.gate import Gate, GateDecision, GateDecisionType, GateSubmission
from research_lab.schemas.project import StateChange
from research_lab.storage.repositories import ProjectRepository, now, sha256
from research_lab.workflow.state import ResearchState

# Livrables dont l'humain valide le contenu à chaque gate.
GATE_1_ARTIFACTS = ["scope.md", "literature-review.md", "evidence-matrix.json", "gaps.json", "alignment.json"]
GATE_2_ARTIFACTS = [
    "research-questions.json", "solutions.json", "scientific-review.json", "research-proposal.md", "references.bib",
]
GATE_ARTIFACTS = {Gate.GATE_1: GATE_1_ARTIFACTS, Gate.GATE_2: GATE_2_ARTIFACTS}

# État depuis lequel on soumet, état d'attente, et état atteint selon la décision (spec §6.1).
_SUBMIT_FROM = {Gate.GATE_1: ResearchState.GAP_ANALYSIS, Gate.GATE_2: ResearchState.PROPOSAL_DRAFT}
AWAITING = {Gate.GATE_1: ResearchState.AWAITING_GATE_1, Gate.GATE_2: ResearchState.AWAITING_GATE_2}
DECISION_TARGETS = {
    Gate.GATE_1: {GateDecisionType.APPROVE: ResearchState.PROBLEM_FORMULATION,
                  GateDecisionType.REVISE: ResearchState.LITERATURE_SEARCH},
    Gate.GATE_2: {GateDecisionType.APPROVE: ResearchState.COMPLETED,
                  GateDecisionType.REVISE: ResearchState.SOLUTION_DESIGN},
}


class GateError(Exception):
    """Soumission ou décision refusée."""


def human_check_failure() -> str | None:
    """Raison pour laquelle la décision ne peut pas venir d'un humain, ou None.

    Garde-fou contre une approbation par l'agent : Claude Code définit CLAUDECODE dans ses
    commandes, qui ne disposent pas d'un terminal interactif. Ce n'est pas une authentification.
    """
    if os.environ.get("CLAUDECODE"):
        return "commande lancée depuis Claude Code : une décision humaine se prend dans son propre terminal"
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return "pas de terminal interactif : une décision humaine se prend dans son propre terminal"
    return None


def artifact_hashes(project_dir: Path, gate: Gate = Gate.GATE_1) -> dict[str, str]:
    names = GATE_ARTIFACTS[gate]
    return {name: sha256((project_dir / name).read_bytes()) for name in names if (project_dir / name).exists()}


def modified_artifacts(repo: ProjectRepository, submission: GateSubmission) -> list[str]:
    """Livrables modifiés, supprimés ou ajoutés depuis la soumission."""
    current = artifact_hashes(repo.dir, submission.gate)
    names = sorted(set(current) | set(submission.artifacts))
    return [n for n in names if current.get(n) != submission.artifacts.get(n)]


def latest_submission(repo: ProjectRepository, gate: Gate = Gate.GATE_1) -> GateSubmission | None:
    submissions = repo.load_gate_submissions(gate)
    return submissions[-1] if submissions else None


def current_gate(repo: ProjectRepository) -> Gate | None:
    """Gate de la soumission la plus récente (celle qu'affichent `gate status` et `gate verify`).

    Déduite de l'ordre des changements d'état : les horodatages, à la seconde, peuvent être égaux.
    """
    for change in reversed(repo.load_project().history):
        for gate, state in AWAITING.items():
            if change.to_state == state:
                return gate
    return None


def _submit(
    repo: ProjectRepository, gate: Gate, actor: str, check_status: str, warnings: list[str], **versions: dict[str, int]
) -> GateSubmission:
    repo.export()  # les empreintes portent sur des exports à jour
    if missing := [n for n in GATE_ARTIFACTS[gate] if not (repo.dir / n).exists()]:
        raise GateError(f"Livrables absents : {', '.join(missing)}")
    previous = latest_submission(repo, gate)
    timestamp = now()
    submission = GateSubmission(
        project_id=repo.project_id, gate=gate, round=previous.round + 1 if previous else 1, submitted_at=timestamp,
        actor=actor, artifacts=artifact_hashes(repo.dir, gate), check_status=check_status, check_warnings=warnings,
        **versions,
    )
    change = StateChange(from_state=_SUBMIT_FROM[gate], to_state=AWAITING[gate], at=timestamp, actor=actor)
    repo.record_gate_submission(submission, change)
    return submission


def _require_state(repo: ProjectRepository, gate: Gate) -> None:
    state = repo.load_project().state
    if state != _SUBMIT_FROM[gate]:
        raise GateError(f"Le projet est à l'état {state} ; la soumission à la {gate} exige {_SUBMIT_FROM[gate]}")


def submit_gate_1(repo: ProjectRepository, settings: Settings, actor: str) -> GateSubmission:
    """Fige le dossier (empreintes des livrables, versions des gaps) et met le projet en attente de décision."""
    _require_state(repo, Gate.GATE_1)
    check = check_gaps(repo, settings)
    if check.status == "BLOCKED":
        raise GateError("`gap check` est BLOCKED : " + " ; ".join(check.errors))
    return _submit(
        repo, Gate.GATE_1, actor, check.status, check.warnings,
        gap_versions={g.gap_id: g.version for g in repo.load_gaps() if g.active},
    )


def submit_gate_2(repo: ProjectRepository, actor: str) -> GateSubmission:
    """Fige le Research Proposal et les livrables qu'il présente, puis attend la décision humaine."""
    _require_state(repo, Gate.GATE_2)
    check = check_proposal_file(repo)
    if check.status == "BLOCKED":
        raise GateError("`proposal check` est BLOCKED : " + " ; ".join(check.errors))
    return _submit(
        repo, Gate.GATE_2, actor, check.status, check.warnings,
        question_versions={q.question_id: q.version for q in repo.load_questions() if q.active},
        solution_versions={s.solution_id: s.version for s in repo.load_solutions() if s.active},
    )


def _decide(
    repo: ProjectRepository,
    gate: Gate,
    decision: GateDecisionType,
    comment: str,
    approver: str,
    selected_gaps: list[str],
) -> GateDecision:
    """Enregistre la décision humaine et applique la transition correspondante, en une transaction."""
    if reason := human_check_failure():
        raise GateError(reason)
    project = repo.load_project()
    if project.state != AWAITING[gate]:
        raise GateError(f"Le projet est à l'état {project.state}, il n'attend pas la {gate}")
    submission = latest_submission(repo, gate)
    if submission is None:
        raise GateError("Aucune soumission enregistrée")
    if not comment.strip():
        raise GateError("La décision exige un commentaire (justification, ou instructions pour la révision)")

    selected = list(dict.fromkeys(selected_gaps))
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
            project_id=repo.project_id, gate=gate, round=submission.round, decision=decision,
            approver=approver, at=timestamp, comment=comment.strip(),
            selected_gaps={g: submission.gap_versions[g] for g in selected},
            artifacts_verified=not modified, modified_artifacts=modified,
        )
    except ValueError as exc:
        raise GateError(str(exc)) from exc
    target = DECISION_TARGETS[gate][decision]
    repo.record_gate_decision(record, StateChange(from_state=project.state, to_state=target, at=timestamp, actor=approver))
    return record


def decide_gate_1(
    repo: ProjectRepository,
    decision: GateDecisionType,
    comment: str,
    approver: str,
    selected_gaps: list[str] | None = None,
) -> GateDecision:
    """approve : les gaps retenus (au moins un, parmi ceux soumis) passent à la formulation du problème ;
    revise  : retour à la recherche bibliographique ; gaps, preuves et corpus sont conservés."""
    return _decide(repo, Gate.GATE_1, decision, comment, approver, selected_gaps or [])


def decide_gate_2(repo: ProjectRepository, decision: GateDecisionType, comment: str, approver: str) -> GateDecision:
    """approve : Research Proposal accepté, projet terminé ;
    revise  : retour à la conception des solutions, avec les instructions du commentaire."""
    return _decide(repo, Gate.GATE_2, decision, comment, approver, [])
