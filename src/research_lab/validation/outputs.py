"""Contrôle des livrables rédigés par l'agent : chaque référence citée doit exister et être valide."""

import re
from dataclasses import dataclass, field

from research_lab.schemas.evidence import Evidence
from research_lab.schemas.paper import Paper, PaperStatus

_CITATION_RE = re.compile(r"\b(PAPER-\d{3,}|EV-\d{3,})\b")


@dataclass
class OutputCheck:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cited_papers: list[str] = field(default_factory=list)
    cited_evidence: list[str] = field(default_factory=list)


def check_literature_review(text: str | None, papers: list[Paper], evidence: list[Evidence]) -> OutputCheck:
    """Vérifie les citations de literature-review.md.

    Ce contrôle établit que les références existent et sont utilisables ; il ne juge pas
    si une preuve soutient effectivement la phrase qui la cite.
    """
    check = OutputCheck()
    if text is None or not text.strip():
        check.errors.append("literature-review.md est absent ou vide")
        return check

    cited = list(dict.fromkeys(_CITATION_RE.findall(text)))
    check.cited_papers = [c for c in cited if c.startswith("PAPER-")]
    check.cited_evidence = [c for c in cited if c.startswith("EV-")]
    by_paper = {p.paper_id: p for p in papers}
    by_evidence = {e.evidence_id: e for e in evidence}

    for paper_id in check.cited_papers:
        paper = by_paper.get(paper_id)
        if paper is None:
            check.errors.append(f"{paper_id} cité mais absent du corpus du projet")
        elif paper.status != PaperStatus.INCLUDED:
            check.errors.append(f"{paper_id} cité mais pas inclus (statut {paper.status})")
    for evidence_id in check.cited_evidence:
        item = by_evidence.get(evidence_id)
        if item is None:
            check.errors.append(f"{evidence_id} cité mais n'existe pas dans ce projet")
        elif not item.active:
            check.errors.append(f"{evidence_id} cité mais retiré ({item.withdrawn_reason})")

    cited_via_evidence = {by_evidence[e].paper_id for e in check.cited_evidence if e in by_evidence}
    with_evidence = {e.paper_id for e in evidence if e.active}
    for paper in papers:
        if paper.status != PaperStatus.INCLUDED:
            continue
        if paper.paper_id not in check.cited_papers and paper.paper_id not in cited_via_evidence:
            check.warnings.append(f"{paper.paper_id} inclus mais jamais cité")
        if paper.paper_id not in with_evidence:
            check.warnings.append(f"{paper.paper_id} inclus mais sans aucune preuve")
    return check
