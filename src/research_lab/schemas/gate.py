"""Modèles des validations humaines (spec §1.3, §6.2)."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class Gate(StrEnum):
    GATE_1 = "gate_1"  # validation de la problématique
    GATE_2 = "gate_2"  # validation du Research Proposal


class GateDecisionType(StrEnum):
    APPROVE = "approve"
    REVISE = "revise"


class GateSubmission(BaseModel):
    """Dossier soumis à l'humain : ce qu'il valide est figé par les empreintes des livrables."""

    project_id: str
    gate: Gate
    round: int = Field(ge=1)
    submitted_at: datetime
    actor: str
    artifacts: dict[str, str]  # fichier du projet -> sha256
    gap_versions: dict[str, int] = Field(default_factory=dict)  # Gate 1 : gaps actifs soumis -> version
    question_versions: dict[str, int] = Field(default_factory=dict)  # Gate 2 : questions actives -> version
    solution_versions: dict[str, int] = Field(default_factory=dict)  # Gate 2 : solutions actives -> version
    check_status: str  # `gap check` (Gate 1) ou `proposal check` (Gate 2) au moment de la soumission
    check_warnings: list[str] = Field(default_factory=list)


class GateDecision(BaseModel):
    project_id: str
    gate: Gate
    round: int = Field(ge=1)
    decision: GateDecisionType
    approver: str
    at: datetime
    comment: str = Field(min_length=1)  # justification ; pour `revise`, les instructions données à l'agent
    selected_gaps: dict[str, int] = Field(default_factory=dict)  # Gate 1 : gaps retenus -> version approuvée
    artifacts_verified: bool  # empreintes identiques à celles de la soumission
    modified_artifacts: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _selection_matches_decision(self) -> "GateDecision":
        if self.gate == Gate.GATE_1 and self.decision == GateDecisionType.APPROVE and not self.selected_gaps:
            raise ValueError("une approbation retient au moins un gap")
        if (self.gate == Gate.GATE_2 or self.decision == GateDecisionType.REVISE) and self.selected_gaps:
            raise ValueError("seule une approbation de la Gate 1 retient des gaps")
        return self
