"""Vues des projets pour l'interface web (api.py) : état, position dans le workflow, livrables de chaque état,
qualité et coûts. Tout est lu dans la base à chaque appel ; rien n'est écrit.
"""

from collections import Counter
from pathlib import Path

from research_lab.config import Settings
from research_lab.costs import cost_report, load_usage
from research_lab.evaluation import quality_report
from research_lab.proposal import PROPOSAL_FILE, check_proposal_file
from research_lab.resume import resume_report
from research_lab.schemas.gate import Gate
from research_lab.schemas.paper import Paper, PaperStatus
from research_lab.storage.database import Database
from research_lab.storage.repositories import FulltextTampered, ProjectRepository, pdf_path
from research_lab.workflow.state import ResearchState as S

# Livrables produits à chaque état (spec §6 et §3).
DELIVERABLES: dict[S, list[str]] = {
    S.NEW: ["project.yaml"],
    S.SCOPING: ["scope.md"],
    S.LITERATURE_SEARCH: ["papers.json", "search-log.json"],
    S.LITERATURE_REVIEW: ["literature-review.md", "evidence-matrix.json"],
    S.GAP_ANALYSIS: ["gaps.json", "alignment.json"],
    S.AWAITING_GATE_1: ["gate-1.json"],
    S.PROBLEM_FORMULATION: ["research-questions.json"],
    S.SOLUTION_DESIGN: ["solutions.json"],
    S.SCIENTIFIC_REVIEW: ["scientific-review.json"],
    S.PROPOSAL_DRAFT: ["research-proposal.md", "references.bib"],
    S.AWAITING_GATE_2: ["gate-2.json"],
    S.COMPLETED: ["human-evaluation.json"],
}
DOCUMENTS = ["scope.md", "literature-review.md", PROPOSAL_FILE]


def _paper_url(paper: Paper) -> str | None:
    """Page de la publication : DOI, sinon arXiv, sinon l'URL de la source, sinon OpenAlex."""
    if paper.doi:
        return f"https://doi.org/{paper.doi}"
    if paper.arxiv_id:
        return f"https://arxiv.org/abs/{paper.arxiv_id}"
    if paper.url:
        return paper.url
    return f"https://openalex.org/{paper.openalex_id}" if paper.openalex_id else None


def _local_pdf(repo: ProjectRepository, paper_id: str) -> str | None:
    return f"/api/papers/{paper_id}/pdf" if pdf_path(repo.papers_dir, paper_id).exists() else None


def _produced(path: Path) -> bool:
    """Livrable présent et non vide (`gaps.json` et `alignment.json` sont exportés vides dès la création)."""
    return path.exists() and path.read_text(encoding="utf-8").strip() not in ("", "[]")


def project_summary(repo: ProjectRepository) -> dict:
    project = repo.load_project()
    return {
        "id": project.project_id, "topic": project.topic, "state": project.state,
        "updated_at": project.updated_at.isoformat(),
        "waiting_for_human": project.state in (S.AWAITING_GATE_1, S.AWAITING_GATE_2),
    }


def project_view(repo: ProjectRepository, settings: Settings) -> dict:
    project = repo.load_project()
    papers = repo.load_papers()
    evidence = [e for e in repo.load_evidence() if e.withdrawn_at is None]
    log = repo.load_search_log()
    reasons = {d.paper_id: d.reason for d in repo.load_decisions()}  # dernière décision de tri
    try:
        coverages = repo.reading_coverage()
        reading = {"complete": sum(c.complete for c in coverages.values()), "total": len(coverages)}
    except FulltextTampered as exc:
        reading = {"error": str(exc)}
    resume = resume_report(repo, settings)
    proposal = None
    if (repo.dir / PROPOSAL_FILE).exists():
        check = check_proposal_file(repo)
        proposal = {"status": check.status, "errors": check.errors, "warnings": check.warnings}
    costs = cost_report(load_usage(repo.db, repo.project_id), settings.costs.prices, project)
    return {
        "id": project.project_id,
        "topic": project.topic,
        "state": project.state,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
        "history": [c.model_dump(mode="json") for c in project.history],
        "visits": Counter(str(c.to_state) for c in project.history),
        "resume": {
            "step": resume.step, "action": resume.action, "waiting_for_human": resume.waiting_for_human,
            "human_instructions": resume.human_instructions, "next_steps": resume.next_steps,
            "stale_exports": resume.stale_exports, "last_change_forced": resume.last_change_forced,
        },
        "files": {
            name: {"exists": _produced(repo.dir / name), "href": f"/api/projects/{repo.project_id}/files/{name}"}
            for names in DELIVERABLES.values() for name in names
        },
        "papers": {
            "by_status": Counter(str(p.status) for p in papers),
            "all": [
                {"id": p.paper_id, "title": p.title, "year": p.published.year if p.published else None,
                 "venue": p.venue, "status": str(p.status), "url": _paper_url(p),
                 "pdf": _local_pdf(repo, p.paper_id),
                 "sources": sorted({str(x.source) for x in p.provenance}),
                 "searches": sorted({x.search_id for x in p.provenance}), "reason": reasons.get(p.paper_id)}
                for p in papers
            ],
        },
        "search_log": [
            {"id": x.search_id, "at": x.started_at.isoformat(), "query": x.query.text, "from": x.query.date_from,
             "to": x.query.date_to, "status": str(x.status), "gap_id": x.gap_id, "new": len(x.new_paper_ids),
             "matched": len(x.matched_paper_ids),
             "sources": [{"source": str(r.source), "status": str(r.status), "total": r.total_available, "hits": r.hits}
                         for r in x.results]}
            for x in log
        ],
        "searches": {"total": len(log), "contradictory": sum(1 for s in log if s.gap_id)},
        "evidence": {"total": len(evidence), "by_type": Counter(str(e.evidence_type) for e in evidence)},
        "reading": reading,
        "gaps": repo.gaps_export(),
        "alignment": repo.alignment_export(),
        "gate_1": repo.gate_export(Gate.GATE_1),
        "gate_2": repo.gate_export(Gate.GATE_2),
        "questions": repo.questions_export(),
        "solutions": repo.solutions_export(),
        "reviews": repo.critique_export(),
        "proposal": proposal,
        "quality": [i.__dict__ for i in quality_report(repo, settings).indicators],
        "ratings": [s.model_dump(mode="json") for s in repo.load_rating_sessions()],
        "costs": {
            "total": costs.total.cost, "responses": costs.total.responses,
            "by_agent": {k: v.cost for k, v in costs.by_agent.items()},
            "by_state": {k: v.cost for k, v in costs.by_state.items()},
        },
        "documents": [name for name in DOCUMENTS if (repo.dir / name).exists()],
    }


def project_ids(db: Database) -> list[str]:
    """Projets, du plus récemment modifié au plus ancien."""
    return [r["project_id"] for r in db.conn.execute("SELECT project_id FROM projects ORDER BY updated_at DESC")]


def workflow() -> dict:
    return {"states": [str(s) for s in S], "deliverables": {str(s): names for s, names in DELIVERABLES.items()}}
