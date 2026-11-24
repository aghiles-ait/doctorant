"""Contrôle du Research Proposal (skill research-writer, spec §8 Q2 et Q5).

Le code vérifie que le Proposal a les sections attendues, que ses citations sont valides, qu'il
traite chaque élément validé du raisonnement (gaps retenus, questions, hypothèses, solutions,
objections de la revue), qu'il cite les recherches effectuées et que references.bib est à jour.
Il ne juge pas la qualité de la rédaction : c'est le rôle de l'humain à la Gate 2.
"""

import re
from dataclasses import dataclass, field

from research_lab.schemas.critique import ANSWER_REQUIRED, ScientificReview
from research_lab.schemas.evidence import Evidence
from research_lab.schemas.paper import Paper
from research_lab.schemas.question import ResearchQuestion
from research_lab.schemas.search import SearchExecution
from research_lab.schemas.solution import Solution
from research_lab.validation.evidence import match_key
from research_lab.validation.outputs import check_literature_review

# Sections attendues (titres Markdown), dans l'ordre de templates/research-proposal.md.
REQUIRED_SECTIONS = [
    "Résumé",
    "Méthode",
    "État de l'art",
    "Gaps retenus",
    "Questions de recherche et hypothèses",
    "Solutions",
    "Protocole d'évaluation",
    "Revue critique",
    "Limites",
    "Références",
]

_HEADING_RE = re.compile(r"^#{1,4}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_ID_RE = re.compile(r"\b((?:GAP|RQ|SOL|OBJ|SEARCH)-\d{3,})\b")
_HYPOTHESIS_RE = re.compile(r"\b(RQ-\d{3,}/H\d+)\b")


@dataclass
class ProposalCheck:
    status: str = "OK"  # OK ou BLOCKED
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cited_papers: list[str] = field(default_factory=list)


def cited_paper_ids(text: str, evidence: list[Evidence]) -> list[str]:
    """Publications citées directement ([PAPER-xxx]) ou par l'une de leurs preuves ([EV-xxx])."""
    check = check_literature_review(text, [], evidence)
    by_evidence = {e.evidence_id: e for e in evidence}
    ids = set(check.cited_papers) | {by_evidence[e].paper_id for e in check.cited_evidence if e in by_evidence}
    return sorted(ids, key=lambda p: int(p.split("-")[1]))


def check_proposal(
    text: str | None,
    *,
    papers: list[Paper],
    evidence: list[Evidence],
    approved_gaps: dict[str, int],
    questions: list[ResearchQuestion],
    solutions: list[Solution],
    reviews: list[ScientificReview],
    searches: list[SearchExecution],
    bibliography: str | None,
    expected_bibliography: str,
) -> ProposalCheck:
    check = ProposalCheck()
    if text is None or not text.strip():
        check.errors.append("research-proposal.md est absent ou vide (partir de templates/research-proposal.md)")
        check.status = "BLOCKED"
        return check

    headings = [match_key(h) for h in _HEADING_RE.findall(text)]
    if missing := [s for s in REQUIRED_SECTIONS if not any(match_key(s) in h for h in headings)]:
        check.errors.append(f"sections manquantes : {', '.join(missing)}")

    # Citations de publications et de preuves : mêmes règles que l'état de l'art (avertissements exclus).
    check.errors.extend(check_literature_review(text, papers, evidence).errors)
    check.cited_papers = cited_paper_ids(text, evidence)

    mentioned = set(_ID_RE.findall(text)) | set(_HYPOTHESIS_RE.findall(text))
    known = {g for g in approved_gaps} | {q.question_id for q in questions} | {s.solution_id for s in solutions}
    known |= {o.objection_id for r in reviews for o in r.objections} | {s.search_id for s in searches}
    known |= {f"{q.question_id}/{h.hypothesis_id}" for q in questions for h in q.hypotheses}
    if unknown := sorted(m for m in mentioned if m not in known):
        check.errors.append(f"identifiants inconnus ou gaps non retenus : {', '.join(unknown)}")

    required = list(approved_gaps)
    for question in (q for q in questions if q.active):
        required += [question.question_id, *(f"{question.question_id}/{h.hypothesis_id}" for h in question.hypotheses)]
    required += [s.solution_id for s in solutions if s.active]
    if reviews:
        required += [o.objection_id for o in reviews[-1].objections if o.severity in ANSWER_REQUIRED]
    if absent := [r for r in required if r not in mentioned]:
        check.errors.append(f"non traités dans le Proposal : {', '.join(absent)}")

    cited_searches = {m for m in mentioned if m.startswith("SEARCH-")}
    if not cited_searches:
        check.errors.append("Méthode (Q5) : citer les recherches effectuées (SEARCH-xxx : requêtes, sources, dates)")
    elif uncited := [s.search_id for s in searches if s.search_id not in cited_searches]:
        check.warnings.append(f"recherches non citées : {', '.join(uncited)}")

    if bibliography != expected_bibliography:
        check.errors.append("references.bib absent ou pas à jour : `research-lab proposal references`")

    if check.errors:
        check.status = "BLOCKED"
    return check
