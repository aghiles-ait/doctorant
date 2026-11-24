"""Évaluation humaine de la qualité scientifique : notes des gaps et des hypothèses (spec §11)."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Target = Annotated[str, StringConstraints(pattern=r"^(GAP-\d{3,}|RQ-\d{3,}/H\d+)$")]


class Rating(BaseModel):
    """Notes d'un humain sur un gap ou une hypothèse, dans la version qu'il a lue."""

    model_config = ConfigDict(extra="forbid")

    target: Target
    target_version: int = Field(ge=1)  # version du gap, ou de la question pour une hypothèse
    scores: dict[str, int] = Field(min_length=1)  # critère -> note
    comment: str = ""


class RatingSession(BaseModel):
    """Une séance d'évaluation, immuable. Une séance plus récente remplace les notes d'une cible."""

    session_id: str = Field(pattern=r"^EVAL-\d{3,}$")
    project_id: str
    rater: str
    at: datetime
    state: str  # état du projet au moment de l'évaluation
    ratings: list[Rating] = Field(min_length=1)
    comment: str = ""
