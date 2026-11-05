"""Modèles des gaps scientifiques (spec §4.3) et de leur évaluation au regard des valeurs (spec §5)."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

EvidenceId = Annotated[str, Field(pattern=r"^EV-\d{3,}$")]


class GapCategory(StrEnum):
    UNRESOLVED_QUESTION = "unresolved_research_question"  # question ouverte, reconnue ou non par les auteurs
    CONFLICTING_RESULTS = "conflicting_results"  # résultats contradictoires entre publications
    MISSING_EVALUATION = "missing_evaluation"  # propriété affirmée mais jamais évaluée
    UNCOMPARED_APPROACHES = "uncompared_approaches"  # approches concurrentes jamais comparées


class GapStatus(StrEnum):
    CANDIDATE = "candidate"  # insuffisamment établi (spec : « mark insufficiently supported gaps as candidates »)
    SUPPORTED = "supported"  # appuyé par plusieurs publications et soumis à une recherche contradictoire
    RESOLVED = "resolved"  # des travaux existants le comblent déjà
    WITHDRAWN = "withdrawn"  # abandonné (erreur d'analyse, hors périmètre)


ACTIVE_GAP_STATUSES = (GapStatus.CANDIDATE, GapStatus.SUPPORTED)


class EvidenceStrength(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


STRENGTH_ORDER = [EvidenceStrength.LOW, EvidenceStrength.MEDIUM, EvidenceStrength.HIGH]


class NoveltyAssessment(StrEnum):
    UNVERIFIED = "unverified"  # pas encore de recherche contradictoire
    PARTIALLY_ADDRESSED = "partially_addressed"  # des travaux y répondent en partie (preuves contradictoires)
    NOT_FOUND_IN_SEARCHES = "not_found_in_searches"  # rien trouvé par les recherches journalisées ; jamais « nouveau »


class GapDraft(BaseModel):
    """Contenu d'un gap rédigé par l'agent (`research-lab gap add/revise --file`)."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    category: GapCategory
    # Raisonnement qui mène des preuves au gap : interprétation de l'agent, distincte des observations.
    rationale: str = Field(min_length=1)
    supporting_evidence: list[EvidenceId] = Field(min_length=1)
    contradicting_evidence: list[EvidenceId] = Field(default_factory=list)
    evidence_strength: EvidenceStrength
    status: GapStatus = GapStatus.CANDIDATE
    novelty_assessment: NoveltyAssessment = NoveltyAssessment.UNVERIFIED
    open_questions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    objections: list[str] = Field(default_factory=list)  # contre-arguments connus

    @model_validator(mode="after")
    def _check_evidence_ids(self) -> "GapDraft":
        if both := sorted(set(self.supporting_evidence) & set(self.contradicting_evidence)):
            raise ValueError(f"preuves à la fois favorables et contraires : {', '.join(both)}")
        ids = [*self.supporting_evidence, *self.contradicting_evidence]
        if len(set(ids)) != len(ids):
            raise ValueError("une preuve est citée plusieurs fois")
        return self


class Gap(GapDraft):
    """Version courante d'un gap. L'identifiant ne change jamais ; chaque révision crée une version."""

    gap_id: str = Field(pattern=r"^GAP-\d{3,}$")
    project_id: str
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    actor: str
    reason: str = Field(min_length=1)  # raison de la création ou de la dernière révision

    @property
    def active(self) -> bool:
        return self.status in ACTIVE_GAP_STATUSES


class ValueScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: int | None  # None : valeur non applicable à ce gap
    justification: str = ""


class AlignmentDraft(BaseModel):
    """Évaluation d'un gap au regard de research-values.yaml (`research-lab alignment set --file`)."""

    model_config = ConfigDict(extra="forbid")

    scores: dict[str, ValueScore]
    tradeoffs: list[str]  # compromis entre valeurs ; liste vide seulement si aucun n'est identifié


class Alignment(AlignmentDraft):
    gap_id: str
    gap_version: int  # version du gap évaluée : une révision du gap rend l'évaluation périmée
    alignment_score: float  # moyenne pondérée des valeurs applicables, entre 0 et 1
    priority_score: float  # combinaison de l'alignement et de la force des preuves (config/scoring.yaml)
    values_hash: str  # empreinte de research-values.yaml et scoring.yaml au moment de l'évaluation
    actor: str
    at: datetime
