"""Sections numérotées de scope.md (`## 2. Périmètre`) et raisons de tri qui les citent (`§2 — …`).

Une décision de tri justifiée par « §2 — gouvernance d'entreprise sans mécanisme décentralisé » renvoie au critère
précis du périmètre ; le statut (incluse, exclue) est déjà dans la décision et n'a pas à être répété.
"""

import re

_SECTION = re.compile(r"^##\s+(\d+)\.?\s+(.+?)\s*$", re.MULTILINE)
# « §2 — justification » ; le tiret peut être —, –, - ou deux-points.
REASON_FORMAT = "§N — justification"
_REASON = re.compile(r"^§(\d+)\s*[—–:-]\s*(\S.*)$", re.DOTALL)
_MIN_JUSTIFICATION = 10


def scope_sections(text: str) -> dict[str, str]:
    """Numéro -> titre des sections de premier niveau numérotées, sans précision entre parenthèses."""
    return {n: re.sub(r"\s*\(.*\)\s*$", "", title) for n, title in _SECTION.findall(text)}


def reason_error(reason: str, sections: dict[str, str]) -> str | None:
    """Pourquoi la raison d'un tri ne cite pas correctement une section de scope.md, ou None."""
    listing = ", ".join(f"§{n} {t}" for n, t in sections.items())
    if not sections:
        return "scope.md n'a pas de sections numérotées (« ## 2. Périmètre ») auxquelles rattacher le tri"
    match = _REASON.match(reason.strip())
    if not match:
        return f"raison attendue : « {REASON_FORMAT} », N étant la section de scope.md qui fonde la décision ({listing})"
    number, justification = match.groups()
    if number not in sections:
        return f"§{number} n'existe pas dans scope.md ({listing})"
    if len(re.sub(r"\W", "", justification)) < _MIN_JUSTIFICATION:
        return "justification trop courte : dire en quoi la publication relève (ou non) de ce critère"
    return None
