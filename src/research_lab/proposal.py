"""Opérations de la rédaction du Research Proposal (skill research-writer)."""

from research_lab.bibliography import render_bibtex
from research_lab.storage.repositories import ProjectRepository
from research_lab.validation.proposal import ProposalCheck, check_proposal, cited_paper_ids
from research_lab.workflow.state import ResearchState

PROPOSAL_FILE = "research-proposal.md"
REFERENCES_FILE = "references.bib"


class ProposalError(Exception):
    """Opération refusée : état du projet ou Proposal absent."""


def _read(repo: ProjectRepository, name: str) -> str | None:
    path = repo.dir / name
    return path.read_text(encoding="utf-8") if path.exists() else None


def expected_bibliography(repo: ProjectRepository, text: str) -> str:
    """references.bib attendu : les publications du corpus citées par le Proposal."""
    by_id = {p.paper_id: p for p in repo.load_papers()}
    return render_bibtex([by_id[p] for p in cited_paper_ids(text, repo.load_evidence()) if p in by_id])


def write_references(repo: ProjectRepository) -> int:
    """Régénère references.bib depuis la base ; renvoie le nombre d'entrées."""
    state = repo.load_project().state
    if state != ResearchState.PROPOSAL_DRAFT:
        raise ProposalError(f"Le projet est à l'état {state} ; cette opération exige {ResearchState.PROPOSAL_DRAFT}")
    text = _read(repo, PROPOSAL_FILE)
    if not text or not text.strip():
        raise ProposalError(f"{PROPOSAL_FILE} est absent ou vide")
    content = expected_bibliography(repo, text)
    (repo.dir / REFERENCES_FILE).write_text(content, encoding="utf-8")
    return content.count("\n@")


def check_proposal_file(repo: ProjectRepository) -> ProposalCheck:
    text = _read(repo, PROPOSAL_FILE)
    return check_proposal(
        text,
        papers=repo.load_papers(),
        evidence=repo.load_evidence(),
        approved_gaps=repo.approved_gaps(),
        questions=repo.load_questions(),
        solutions=repo.load_solutions(),
        reviews=repo.load_reviews(),
        searches=repo.load_search_log(),
        bibliography=_read(repo, REFERENCES_FILE),
        expected_bibliography=expected_bibliography(repo, text or ""),
    )
