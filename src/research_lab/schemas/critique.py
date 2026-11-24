"""Revue critique indépendante (spec §4.1 scientific-critic, §8) et réponses aux objections."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from research_lab.schemas.gap import EvidenceId
from research_lab.schemas.question import Text

# Élément visé par une objection : gap, question, hypothèse (RQ-001/H1), solution, preuve ou publication.
Target = Annotated[str, Field(pattern=r"^((GAP|RQ|SOL|EV|PAPER)-\d{3,}|RQ-\d{3,}/H\d+)$")]


class Verdict(StrEnum):
    ACCEPTABLE = "ACCEPTABLE"  # passage à la rédaction du Research Proposal
    MAJOR_REVISION = "MAJOR_REVISION"  # retour à la conception des solutions
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"  # les preuves ne soutiennent pas le raisonnement


class Severity(StrEnum):
    CRITICAL = "critical"  # invalide le raisonnement : incompatible avec ACCEPTABLE
    MAJOR = "major"  # doit recevoir une réponse avant de poursuivre
    MINOR = "minor"


ANSWER_REQUIRED = (Severity.CRITICAL, Severity.MAJOR)


class VerificationResult(StrEnum):
    SUPPORTS = "supports"
    PARTIALLY_SUPPORTS = "partially_supports"
    DOES_NOT_SUPPORT = "does_not_support"


class Verification(BaseModel):
    """Relecture indépendante d'une preuve : l'extrait soutient-il l'affirmation qu'on lui prête ?"""

    model_config = ConfigDict(extra="forbid")

    evidence_id: EvidenceId
    result: VerificationResult
    note: Text


class ObjectionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Severity
    targets: list[Target] = Field(min_length=1)
    statement: Text
    rationale: Text  # sur quoi repose l'objection (preuves, lacune de raisonnement)
    suggestion: str = ""


class ReviewDraft(BaseModel):
    """Revue rédigée par le reviewer (`research-lab critique submit --file`)."""

    model_config = ConfigDict(extra="forbid")

    verdict: Verdict
    summary: Text
    objections: list[ObjectionDraft] = Field(default_factory=list)
    verifications: list[Verification] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent_verdict(self) -> "ReviewDraft":
        severities = {o.severity for o in self.objections}
        if self.verdict == Verdict.ACCEPTABLE and Severity.CRITICAL in severities:
            raise ValueError("verdict ACCEPTABLE incompatible avec une objection critique")
        if self.verdict != Verdict.ACCEPTABLE and not severities & set(ANSWER_REQUIRED):
            raise ValueError(f"verdict {self.verdict} : le justifier par au moins une objection critique ou majeure")
        ids = [v.evidence_id for v in self.verifications]
        if len(set(ids)) != len(ids):
            raise ValueError("une preuve est vérifiée plusieurs fois")
        challenged = {t for o in self.objections if o.severity in ANSWER_REQUIRED for t in o.targets}
        if unchallenged := [v.evidence_id for v in self.verifications
                            if v.result == VerificationResult.DOES_NOT_SUPPORT and v.evidence_id not in challenged]:
            raise ValueError(
                f"preuves jugées non probantes sans objection critique ou majeure qui les vise : {', '.join(unchallenged)}"
            )
        return self


class Objection(ObjectionDraft):
    objection_id: str = Field(pattern=r"^OBJ-\d{3,}$")
    round: int = Field(ge=1)


class ScientificReview(BaseModel):
    """Revue enregistrée : elle fige ce qui a été revu (empreintes, versions)."""

    project_id: str
    round: int = Field(ge=1)  # n-ième passage à l'état SCIENTIFIC_REVIEW
    verdict: Verdict
    summary: str
    objections: list[Objection]
    verifications: list[Verification]
    reviewer: str
    at: datetime
    reviewed_artifacts: dict[str, str]  # fichier -> sha256
    question_versions: dict[str, int]
    solution_versions: dict[str, int]


class ResponseAction(StrEnum):
    REVISED = "revised"  # question ou solution visée révisée depuis la revue
    REBUTTED = "rebutted"  # objection contestée, argument à l'appui
    ACCEPTED_LIMITATION = "accepted_limitation"  # objection admise, reportée dans les limites du Proposal


class ResponseDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ResponseAction
    response: Text


class ObjectionResponse(ResponseDraft):
    objection_id: str
    actor: str
    at: datetime
