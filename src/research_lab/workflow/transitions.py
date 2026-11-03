"""Transitions du workflow, contrôlées par le programme (spec §6).

Sprint 1 : seules les transitions NEW → SCOPING → LITERATURE_SEARCH sont
implémentées. Les autres, dont les gates, lèvent une erreur explicite.
"""

from collections.abc import Callable
from pathlib import Path

from research_lab.workflow.state import ResearchState as S


class TransitionError(Exception):
    pass


def _scope_written(project_dir: Path) -> str | None:
    scope = project_dir / "scope.md"
    if not scope.exists() or not scope.read_text(encoding="utf-8").strip():
        return "scope.md est absent ou vide : le périmètre doit être défini avant la recherche"
    return None


# (origine, destination) -> précondition renvoyant un message d'erreur ou None
_TRANSITIONS: dict[tuple[S, S], Callable[[Path], str | None]] = {
    (S.NEW, S.SCOPING): lambda _: None,
    (S.SCOPING, S.LITERATURE_SEARCH): _scope_written,
}


def check_transition(current: S, target: S, project_dir: Path) -> None:
    precondition = _TRANSITIONS.get((current, target))
    if precondition is None:
        raise TransitionError(f"Transition {current} → {target} non autorisée (ou pas encore implémentée)")
    if (error := precondition(project_dir)) is not None:
        raise TransitionError(error)
