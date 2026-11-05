"""Opérations de l'analyse des gaps (skill gap-analysis) et de l'alignement sur les valeurs (skill values-alignment)."""

from research_lab.config import Settings
from research_lab.schemas.gap import ACTIVE_GAP_STATUSES, Alignment, AlignmentDraft, Gap, GapDraft
from research_lab.schemas.paper import PaperStatus
from research_lab.storage.repositories import ProjectRepository, next_gap_id, now
from research_lab.validation.gaps import (
    GapCheck,
    alignment_score,
    check_alignment,
    check_gap,
    check_gap_analysis,
    priority_score,
)
from research_lab.workflow.state import ResearchState


class GapError(Exception):
    """Opération refusée : état du projet, gap ou évaluation invalide."""


def _require_gap_analysis(repo: ProjectRepository) -> None:
    state = repo.load_project().state
    if state != ResearchState.GAP_ANALYSIS:
        raise GapError(f"Le projet est à l'état {state} ; cette opération exige {ResearchState.GAP_ANALYSIS}")


def _current(repo: ProjectRepository, gap_id: str) -> Gap:
    gap = next((g for g in repo.load_gaps() if g.gap_id == gap_id), None)
    if gap is None:
        raise GapError(f"{gap_id} n'existe pas dans le projet {repo.project_id}")
    return gap


def _validate(repo: ProjectRepository, settings: Settings, draft: GapDraft, gap_id: str | None) -> None:
    evidence = {e.evidence_id: e for e in repo.load_evidence()}
    searches = repo.searches_by_gap().get(gap_id, []) if gap_id else []
    if errors := check_gap(draft, evidence, searches, settings.policy.min_supporting_papers):
        raise GapError(" ; ".join(errors))


def add_gap(repo: ProjectRepository, settings: Settings, draft: GapDraft, reason: str, actor: str) -> Gap:
    """Crée un gap (version 1). Sans recherche contradictoire, il ne peut être que candidate."""
    _require_gap_analysis(repo)
    _validate(repo, settings, draft, None)
    timestamp = now()
    gap = Gap(
        **draft.model_dump(), gap_id=next_gap_id(repo.db), project_id=repo.project_id, version=1,
        created_at=timestamp, updated_at=timestamp, actor=actor, reason=reason.strip() or "création",
    )
    repo.save_gap_version(gap)
    return gap


def revise_gap(
    repo: ProjectRepository, settings: Settings, gap_id: str, draft: GapDraft, reason: str, actor: str
) -> Gap:
    """Remplace le contenu d'un gap par une nouvelle version ; l'identifiant et l'historique sont conservés."""
    _require_gap_analysis(repo)
    if not reason.strip():
        raise GapError("Une révision exige une raison")
    current = _current(repo, gap_id)
    if draft == GapDraft.model_validate(current.model_dump(include=set(GapDraft.model_fields))):
        raise GapError(f"Aucun changement par rapport à la version {current.version} de {gap_id}")
    _validate(repo, settings, draft, gap_id)
    gap = Gap(
        **draft.model_dump(), gap_id=gap_id, project_id=repo.project_id, version=current.version + 1,
        created_at=current.created_at, updated_at=now(), actor=actor, reason=reason.strip(),
    )
    repo.save_gap_version(gap)
    return gap


def set_alignment(
    repo: ProjectRepository, settings: Settings, gap_id: str, draft: AlignmentDraft, actor: str
) -> Alignment:
    """Évalue la version courante d'un gap actif au regard de research-values.yaml."""
    _require_gap_analysis(repo)
    gap = _current(repo, gap_id)
    if gap.status not in ACTIVE_GAP_STATUSES:
        raise GapError(f"{gap_id} est au statut {gap.status} : seuls les gaps candidate ou supported sont évalués")
    if errors := check_alignment(draft, settings.values):
        raise GapError(" ; ".join(errors))
    score = alignment_score(draft, settings.values)
    alignment = Alignment(
        **draft.model_dump(), gap_id=gap_id, gap_version=gap.version, alignment_score=score,
        priority_score=priority_score(score, gap.evidence_strength, settings.scoring.priority),
        values_hash=settings.values_hash(), actor=actor, at=now(),
    )
    repo.add_alignment(alignment)
    return alignment


def check_gaps(repo: ProjectRepository, settings: Settings) -> GapCheck:
    return check_gap_analysis(
        repo.load_gaps(),
        repo.load_evidence(),
        repo.searches_by_gap(),
        repo.load_alignments(),
        candidate_papers=sum(p.status == PaperStatus.CANDIDATE for p in repo.load_papers()),
        min_supporting_papers=settings.policy.min_supporting_papers,
        values_hash=settings.values_hash(),
    )
