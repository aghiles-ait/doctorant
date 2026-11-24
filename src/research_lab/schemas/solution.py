"""Solutions conceptuelles et leur comparaison (spec §4.1 solution-architect, §7 Solution)."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from research_lab.schemas.gap import EvidenceId
from research_lab.schemas.question import Text

QuestionId = Annotated[str, Field(pattern=r"^RQ-\d{3,}$")]
SolutionId = Annotated[str, Field(pattern=r"^SOL-\d{3,}$")]
HypothesisId = Annotated[str, Field(pattern=r"^H\d+$")]


class SolutionStatus(StrEnum):
    PROPOSED = "proposed"
    WITHDRAWN = "withdrawn"  # abandonnée (irréaliste, redondante avec une autre)


class SolutionDraft(BaseModel):
    """Contenu d'une solution rédigée par l'agent (`research-lab solution add/revise --file`)."""

    model_config = ConfigDict(extra="forbid")

    title: Text
    question_id: QuestionId  # question à laquelle elle répond ; ne change pas d'une version à l'autre
    summary: Text
    architecture: Text  # composants et interactions, au niveau conceptuel
    addressed_hypotheses: list[HypothesisId] = Field(min_length=1)  # hypothèses de la question qu'elle permet de tester
    evaluation_plan: Text  # protocole : comment tester ces hypothèses avec cette solution
    tradeoffs: list[Text] = Field(min_length=1)
    risks: list[Text] = Field(min_length=1)
    evidence: list[EvidenceId] = Field(min_length=1)  # travaux de l'état de l'art sur lesquels elle s'appuie
    limitations: list[str] = Field(default_factory=list)
    status: SolutionStatus = SolutionStatus.PROPOSED

    @model_validator(mode="after")
    def _check_ids(self) -> "SolutionDraft":
        if len(set(self.addressed_hypotheses)) != len(self.addressed_hypotheses):
            raise ValueError("une hypothèse est citée plusieurs fois")
        if len(set(self.evidence)) != len(self.evidence):
            raise ValueError("une preuve est citée plusieurs fois")
        return self


class Solution(SolutionDraft):
    """Version courante d'une solution. L'identifiant ne change jamais ; chaque révision crée une version."""

    solution_id: SolutionId
    project_id: str
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    actor: str
    reason: str = Field(min_length=1)

    @property
    def active(self) -> bool:
        return self.status == SolutionStatus.PROPOSED


class ComparisonDraft(BaseModel):
    """Comparaison des solutions d'une question (`research-lab solution compare --file`)."""

    model_config = ConfigDict(extra="forbid")

    question_id: QuestionId
    criteria: list[Text] = Field(min_length=2)
    # Pour chaque solution active de la question, son appréciation sur chaque critère.
    assessments: dict[SolutionId, dict[str, Text]]
    recommendation: SolutionId | None = None  # aucune : le choix est laissé à l'humain
    justification: Text  # raison de la recommandation, ou de l'absence de recommandation

    @model_validator(mode="after")
    def _check_criteria(self) -> "ComparisonDraft":
        if len({c.lower() for c in self.criteria}) != len(self.criteria):
            raise ValueError("critères en double")
        return self


class Comparison(ComparisonDraft):
    version: int = Field(ge=1)
    solution_versions: dict[str, int]  # versions comparées : une révision ultérieure rend la comparaison périmée
    actor: str
    at: datetime
