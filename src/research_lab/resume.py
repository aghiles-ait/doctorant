"""Reprise d'un projet interrompu (spec §6 : reprendre au dernier état validé, sans tout relancer).

Tout est relu dans la base : état, dernière décision humaine, ce qui bloque l'étape suivante. Le rapport dit
à l'agent quoi faire ensuite ; il ne modifie rien, sauf les exports périmés si on le demande (`--repair`).
"""

from dataclasses import dataclass, field
from datetime import datetime

from research_lab.config import Settings
from research_lab.critique import check_critique
from research_lab.gaps import check_gaps
from research_lab.proposal import check_proposal_file
from research_lab.schemas.gate import Gate
from research_lab.storage.repositories import ProjectRepository
from research_lab.workflow.approvals import AWAITING
from research_lab.workflow.state import ResearchState as S
from research_lab.workflow.transitions import TransitionError, check_transition

# Étape du doctorant (doctorant.md), skill ou acteur à solliciter, et action attendue à chaque état.
_STEPS: dict[S, tuple[str, str]] = {
    S.NEW: ("step 1", "`project transition <id> SCOPING`"),
    S.SCOPING: ("step 1", "rédiger scope.md, puis `project transition <id> LITERATURE_SEARCH`"),
    S.LITERATURE_SEARCH: ("step 2 — skill scientific-watch", "rechercher jusqu'à `corpus check` OK"),
    S.LITERATURE_REVIEW: ("step 3 — skill literature-review", "trier, lire, extraire les preuves, `review check`"),
    S.GAP_ANALYSIS: (
        "steps 4-5 — skills gap-analysis, values-alignment", "gaps, recherches contradictoires, alignement, `gate submit`"
    ),
    S.AWAITING_GATE_1: ("Gate 1", "attendre la décision humaine (`gate approve` / `gate revise`, terminal humain)"),
    S.PROBLEM_FORMULATION: ("step 6 — skill problem-formulation", "questions et hypothèses, `question check`"),
    S.SOLUTION_DESIGN: ("step 7 — skill solution-architect", "solutions, comparaison, réponses aux objections"),
    S.SCIENTIFIC_REVIEW: ("step 8 — agent scientific-reviewer", "revue indépendante, puis transition selon le verdict"),
    S.PROPOSAL_DRAFT: ("step 9 — skill research-writer", "research-proposal.md, `proposal check`, `gate submit`"),
    S.AWAITING_GATE_2: ("Gate 2", "attendre la décision humaine (`gate approve` / `gate revise`, terminal humain)"),
    S.COMPLETED: ("terminé", "rien à faire"),
}

# Transitions suivantes contrôlées par `project transition` (les soumissions aux gates sont traitées à part).
_NEXT: dict[S, list[S]] = {
    S.NEW: [S.SCOPING],
    S.SCOPING: [S.LITERATURE_SEARCH],
    S.LITERATURE_SEARCH: [S.LITERATURE_REVIEW],
    S.LITERATURE_REVIEW: [S.GAP_ANALYSIS],
    S.PROBLEM_FORMULATION: [S.SOLUTION_DESIGN],
    S.SOLUTION_DESIGN: [S.SCIENTIFIC_REVIEW],
    S.SCIENTIFIC_REVIEW: [S.PROPOSAL_DRAFT, S.SOLUTION_DESIGN],
}

_LABELS = {Gate.GATE_1: "Gate 1", Gate.GATE_2: "Gate 2"}


@dataclass
class ResumeReport:
    project_id: str
    state: S
    since: datetime | None
    step: str
    action: str
    waiting_for_human: bool
    last_change_forced: bool = False
    human_instructions: str | None = None  # commentaire de la dernière décision de gate qui a mené ici
    next_steps: dict[str, list[str]] = field(default_factory=dict)  # étape suivante -> ce qui la bloque ([] : possible)
    stale_exports: list[str] = field(default_factory=list)


def _gate_submission_blockers(repo: ProjectRepository, settings: Settings, state: S) -> list[str]:
    if state == S.GAP_ANALYSIS:
        check = check_gaps(repo, settings)
    else:
        check = check_proposal_file(repo)
    return list(check.errors) if check.status == "BLOCKED" else []


def resume_report(repo: ProjectRepository, settings: Settings) -> ResumeReport:
    project = repo.load_project()
    state = project.state
    last = project.history[-1] if project.history else None
    step, action = _STEPS[state]
    report = ResumeReport(
        project_id=project.project_id, state=state, since=last.at if last else None, step=step, action=action,
        waiting_for_human=state in AWAITING.values(), last_change_forced=bool(last and last.forced),
        stale_exports=repo.stale_exports(),
    )

    # Arrivé ici par une décision de gate : ses instructions orientent la reprise.
    for gate, awaiting in AWAITING.items():
        if last and last.from_state == awaiting and (decisions := repo.load_gate_decisions(gate)):
            report.human_instructions = f"{_LABELS[gate]} {decisions[-1].decision} : {decisions[-1].comment}"

    if state in (S.GAP_ANALYSIS, S.PROPOSAL_DRAFT):
        gate = Gate.GATE_1 if state == S.GAP_ANALYSIS else Gate.GATE_2
        report.next_steps[f"`gate submit` ({_LABELS[gate]})"] = _gate_submission_blockers(repo, settings, state)
    if targets := _NEXT.get(state):
        facts = repo.facts(settings.policy)
        for target in targets:
            try:
                check_transition(state, target, facts)
                report.next_steps[str(target)] = []
            except TransitionError as exc:
                report.next_steps[str(target)] = [str(exc)]
    if state == S.SCIENTIFIC_REVIEW:
        critique = check_critique(repo)
        if critique.next_state is None:
            report.next_steps = {"revue (agent scientific-reviewer)": critique.errors}
    return report
