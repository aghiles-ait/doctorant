"""Règles déterministes de l'analyse des gaps (spec §4.2) et de l'alignement sur les valeurs (spec §5).

Le code ne juge pas si un gap est pertinent ; il vérifie que ce que l'agent déclare est
cohérent avec ce qui est enregistré : preuves existantes, nombre de publications,
recherches contradictoires effectuées, évaluation complète au regard des valeurs.
"""

from dataclasses import dataclass, field

from research_lab.config import PriorityConfig, ValuesConfig
from research_lab.schemas.evidence import Evidence, EvidenceType
from research_lab.schemas.gap import (
    STRENGTH_ORDER,
    Alignment,
    AlignmentDraft,
    EvidenceStrength,
    Gap,
    GapDraft,
    GapStatus,
    NoveltyAssessment,
)
from research_lab.schemas.search import SearchExecution, SearchStatus

# Résultats établis (mesurés ou démontrés), par opposition aux positions, méthodes ou définitions.
_ESTABLISHED = (EvidenceType.EMPIRICAL_RESULT, EvidenceType.THEORETICAL_RESULT)


def strength_ceiling(supporting: list[Evidence]) -> EvidenceStrength:
    """Force maximale qu'un ensemble de preuves favorables permet de déclarer.

    high   : résultats établis issus d'au moins deux publications ;
    medium : un résultat établi, ou des preuves issues d'au moins deux publications ;
    low    : sinon (une seule publication, sans résultat établi).
    """
    papers = {e.paper_id for e in supporting}
    established = {e.paper_id for e in supporting if e.evidence_type in _ESTABLISHED}
    if len(established) >= 2:
        return EvidenceStrength.HIGH
    if established or len(papers) >= 2:
        return EvidenceStrength.MEDIUM
    return EvidenceStrength.LOW


def useful_searches(searches: list[SearchExecution]) -> list[SearchExecution]:
    """Recherches contradictoires dont les résultats ont été fusionnés dans le corpus."""
    return [s for s in searches if s.status != SearchStatus.FAILED]


def check_gap(
    draft: GapDraft, evidence: dict[str, Evidence], searches: list[SearchExecution], min_supporting_papers: int
) -> list[str]:
    """Erreurs d'un gap au regard des preuves du projet et des recherches contradictoires qui le concernent."""
    errors = []
    for evidence_id in [*draft.supporting_evidence, *draft.contradicting_evidence]:
        item = evidence.get(evidence_id)
        if item is None:
            errors.append(f"{evidence_id} n'existe pas dans ce projet")
        elif not item.active:
            errors.append(f"{evidence_id} est retirée ({item.withdrawn_reason})")
    supporting = [evidence[e] for e in draft.supporting_evidence if e in evidence and evidence[e].active]
    contradicting = [evidence[e] for e in draft.contradicting_evidence if e in evidence and evidence[e].active]
    searched = bool(useful_searches(searches))

    ceiling = strength_ceiling(supporting)
    if STRENGTH_ORDER.index(draft.evidence_strength) > STRENGTH_ORDER.index(ceiling):
        errors.append(
            f"force des preuves {draft.evidence_strength} déclarée, mais les preuves citées ne permettent "
            f"que {ceiling} (high : résultats établis de deux publications ; medium : un résultat établi "
            "ou deux publications)"
        )

    if draft.status == GapStatus.SUPPORTED:
        papers = {e.paper_id for e in supporting}
        if len(papers) < min_supporting_papers:
            errors.append(
                f"statut supported : preuves issues de {len(papers)} publication(s), "
                f"minimum {min_supporting_papers} ; rester candidate"
            )
        if not searched:
            errors.append("statut supported : aucune recherche contradictoire (`watch search --for-gap`)")
    if draft.status == GapStatus.RESOLVED and not contradicting:
        errors.append("statut resolved : citer les preuves des travaux qui comblent le gap (contradicting_evidence)")

    if draft.novelty_assessment == NoveltyAssessment.NOT_FOUND_IN_SEARCHES:
        if not searched:
            errors.append("nouveauté not_found_in_searches : aucune recherche contradictoire effectuée")
        if contradicting:
            errors.append("nouveauté not_found_in_searches incompatible avec des preuves contraires : partially_addressed")
    if draft.novelty_assessment == NoveltyAssessment.PARTIALLY_ADDRESSED and not contradicting:
        errors.append("nouveauté partially_addressed : citer les preuves des travaux concernés (contradicting_evidence)")
    return errors


# --- Alignement sur les valeurs -----------------------------------------------------------


def check_alignment(draft: AlignmentDraft, values: ValuesConfig) -> list[str]:
    errors = []
    expected, given = set(values.values), set(draft.scores)
    if missing := sorted(expected - given):
        errors.append(f"valeurs non évaluées : {', '.join(missing)}")
    if unknown := sorted(given - expected):
        errors.append(f"valeurs inconnues de research-values.yaml : {', '.join(unknown)}")
    rules = values.evaluation
    for name in sorted(given & expected):
        item = draft.scores[name]
        if item.score is None and not rules.allow_not_applicable:
            errors.append(f"{name} : « non applicable » interdit par research-values.yaml")
        if item.score is not None and item.score not in rules.scale:
            errors.append(f"{name} : score {item.score} hors de l'échelle {rules.scale}")
        if rules.require_justification and not item.justification.strip():
            errors.append(f"{name} : justification obligatoire")
    if not errors and all(draft.scores[n].score is None for n in expected):
        errors.append("aucune valeur applicable : le gap ne peut pas être évalué")
    return errors


def alignment_score(draft: AlignmentDraft, values: ValuesConfig) -> float:
    """Moyenne des scores des valeurs applicables, pondérée par leur poids, ramenée entre 0 et 1."""
    low, high = min(values.evaluation.scale), max(values.evaluation.scale)
    applicable = [(values.values[n].weight, s.score) for n, s in draft.scores.items() if s.score is not None]
    total_weight = sum(w for w, _ in applicable)
    if not total_weight:
        return 0.0
    return round(sum(w * (score - low) / (high - low) for w, score in applicable) / total_weight, 4)


def priority_score(alignment: float, strength: EvidenceStrength, priority: PriorityConfig) -> float:
    weights = priority.weights
    total = weights.get("alignment", 0) + weights.get("evidence_strength", 0)
    if not total:
        return 0.0
    combined = weights.get("alignment", 0) * alignment + weights.get("evidence_strength", 0) * priority.evidence_strength[strength]
    return round(combined / total, 4)


# --- Contrôle d'ensemble (research-lab gap check) ------------------------------------------


@dataclass
class GapCheck:
    status: str = "OK"  # OK, NEEDS_MORE_RESEARCH ou BLOCKED
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check_gap_analysis(
    gaps: list[Gap],
    evidence: list[Evidence],
    searches_by_gap: dict[str, list[SearchExecution]],
    alignments: dict[str, Alignment],
    candidate_papers: int,
    min_supporting_papers: int,
    values_hash: str,
) -> GapCheck:
    """Contrôle l'analyse des gaps d'un projet avant sa présentation à la Gate 1."""
    check = GapCheck()
    by_id = {e.evidence_id: e for e in evidence}
    if not gaps:
        check.errors.append("aucun gap enregistré")
    if candidate_papers:
        check.errors.append(f"{candidate_papers} publications trouvées par les recherches contradictoires restent à trier")

    for gap in gaps:
        searches = searches_by_gap.get(gap.gap_id, [])
        check.errors.extend(f"{gap.gap_id} : {e}" for e in check_gap(gap, by_id, searches, min_supporting_papers))
        if not gap.active:
            continue
        if not useful_searches(searches):
            check.warnings.append(f"{gap.gap_id} : aucune recherche contradictoire (Q3), nouveauté non vérifiée")
        alignment = alignments.get(gap.gap_id)
        if alignment is None:
            check.errors.append(f"{gap.gap_id} : pas d'évaluation au regard des valeurs (`alignment set`)")
        elif alignment.gap_version != gap.version:
            check.errors.append(
                f"{gap.gap_id} : évaluation périmée (version {alignment.gap_version} évaluée, gap en version {gap.version})"
            )
        elif alignment.values_hash != values_hash:
            check.errors.append(f"{gap.gap_id} : évaluation faite avec d'autres valeurs ou pondérations, à refaire")

    if check.errors:
        check.status = "BLOCKED"
    elif not any(g.status == GapStatus.SUPPORTED for g in gaps):
        check.status = "NEEDS_MORE_RESEARCH"
        check.warnings.append("aucun gap au statut supported")
    return check
