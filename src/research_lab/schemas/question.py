"""Questions de recherche et hypothèses falsifiables (spec §4.1 problem-formulation, §7 ResearchQuestion, Q4)."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from research_lab.schemas.gap import EvidenceId

GapId = Annotated[str, Field(pattern=r"^GAP-\d{3,}$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def _normalized(text: str) -> str:
    return " ".join(text.lower().split())


class QuestionStatus(StrEnum):
    ACTIVE = "active"
    WITHDRAWN = "withdrawn"  # abandonnée (reformulée autrement, gap plus retenu)


class Hypothesis(BaseModel):
    """Hypothèse falsifiable : ce qui serait observé si elle est vraie, et ce qui la réfuterait."""

    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str = Field(pattern=r"^H\d+$")  # local à la question : RQ-001/H1
    statement: Text
    prediction: Text  # observation attendue si l'hypothèse est vraie
    refutation_criterion: Text  # observation ou résultat qui la réfuterait (Q4)
    test_method: Text  # expérience, simulation, étude empirique, preuve formelle…
    metrics: list[Text] = Field(min_length=1)
    evidence: list[EvidenceId] = Field(min_length=1)  # preuves de l'état de l'art qui la motivent

    @model_validator(mode="after")
    def _check(self) -> "Hypothesis":
        if _normalized(self.refutation_criterion) == _normalized(self.prediction):
            raise ValueError(f"{self.hypothesis_id} : le critère de réfutation répète la prédiction")
        if len(set(self.evidence)) != len(self.evidence):
            raise ValueError(f"{self.hypothesis_id} : une preuve est citée plusieurs fois")
        return self


class QuestionDraft(BaseModel):
    """Contenu d'une question rédigée par l'agent (`research-lab question add/revise --file`)."""

    model_config = ConfigDict(extra="forbid")

    question: Text
    gap_ids: list[GapId] = Field(min_length=1)  # gaps retenus à la Gate 1 auxquels elle répond
    # Comment la question découle des gaps : interprétation de l'agent.
    rationale: Text
    hypotheses: list[Hypothesis] = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)  # périmètre, ressources, hypothèses de travail
    limitations: list[str] = Field(default_factory=list)
    status: QuestionStatus = QuestionStatus.ACTIVE

    @model_validator(mode="after")
    def _check_ids(self) -> "QuestionDraft":
        if len(set(self.gap_ids)) != len(self.gap_ids):
            raise ValueError("un gap est cité plusieurs fois")
        ids = [h.hypothesis_id for h in self.hypotheses]
        if len(set(ids)) != len(ids):
            raise ValueError("identifiants d'hypothèses en double")
        return self


class ResearchQuestion(QuestionDraft):
    """Version courante d'une question. L'identifiant ne change jamais ; chaque révision crée une version."""

    question_id: str = Field(pattern=r"^RQ-\d{3,}$")
    project_id: str
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    actor: str
    reason: str = Field(min_length=1)

    @property
    def active(self) -> bool:
        return self.status == QuestionStatus.ACTIVE
