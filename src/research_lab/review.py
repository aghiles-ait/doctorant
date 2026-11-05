"""Opérations de l'état de l'art (skill literature-review) : tri, texte intégral, preuves."""

from collections.abc import Iterator

from research_lab.config import Settings
from research_lab.fulltext import FulltextFetcher, pages_bytes
from research_lab.schemas.evidence import Evidence, EvidenceLocation, EvidenceType, FulltextRecord, FulltextStatus
from research_lab.schemas.paper import Paper, PaperStatus, ScreeningDecision
from research_lab.storage.repositories import (
    ProjectRepository,
    load_fulltext,
    next_evidence_id,
    now,
    read_pages,
    save_fulltext,
    sha256,
)
from research_lab.validation.evidence import find_quote_pages, quote_in, quote_length
from research_lab.workflow.state import ResearchState

# Pendant l'analyse des gaps, les recherches contradictoires ajoutent des publications à trier,
# à lire et à citer : tri, texte intégral et preuves restent possibles.
_EVIDENCE_STATES = (ResearchState.LITERATURE_REVIEW, ResearchState.GAP_ANALYSIS)


class ReviewError(Exception):
    """Opération refusée : état du projet, publication ou extrait invalide."""


def _require_state(repo: ProjectRepository, *allowed: ResearchState) -> None:
    state = repo.load_project().state
    if state not in allowed:
        raise ReviewError(f"Le projet est à l'état {state} ; cette opération exige {' ou '.join(allowed)}")


def _project_paper(repo: ProjectRepository, paper_id: str) -> Paper:
    paper = repo.get_paper(paper_id)
    if paper is None:
        raise ReviewError(f"{paper_id} n'appartient pas au corpus du projet {repo.project_id}")
    return paper


# --- Tri ------------------------------------------------------------------------------


def decide(repo: ProjectRepository, paper_id: str, decision: PaperStatus, reason: str, actor: str) -> ScreeningDecision:
    """Inclut ou exclut une publication ; une décision peut être révisée, l'historique est conservé."""
    _require_state(repo, *_EVIDENCE_STATES)
    paper = _project_paper(repo, paper_id)
    if repo.load_project().state == ResearchState.GAP_ANALYSIS and paper.status != PaperStatus.CANDIDATE:
        raise ReviewError(
            f"{paper_id} est déjà trié ({paper.status}) ; pendant l'analyse des gaps, seules les publications "
            "candidates (trouvées par les recherches contradictoires) se trient"
        )
    if decision == PaperStatus.EXCLUDED:
        active = [e.evidence_id for e in repo.load_evidence() if e.paper_id == paper_id and e.active]
        if active:
            raise ReviewError(f"{paper_id} a des preuves actives ({', '.join(active)}) : les retirer avant de l'exclure")
    record = ScreeningDecision(
        project_id=repo.project_id, paper_id=paper_id, decision=decision, reason=reason.strip(), actor=actor, at=now()
    )
    repo.record_decision(record)
    return record


# --- Texte intégral --------------------------------------------------------------------


def fetch_fulltexts(
    repo: ProjectRepository, settings: Settings, fetcher: FulltextFetcher, paper_ids: list[str] | None = None
) -> Iterator[FulltextRecord]:
    """Récupère le texte intégral des publications incluses (ou de celles demandées).

    Un texte déjà disponible n'est pas retéléchargé, y compris s'il l'a été pour un autre projet.
    Les échecs sont enregistrés et peuvent être retentés.
    """
    _require_state(repo, *_EVIDENCE_STATES)
    if paper_ids:
        papers = [_project_paper(repo, pid) for pid in paper_ids]
        if not_included := [p.paper_id for p in papers if p.status != PaperStatus.INCLUDED]:
            raise ReviewError(f"Publications non incluses : {', '.join(not_included)}")
    else:
        papers = [p for p in repo.load_papers() if p.status == PaperStatus.INCLUDED]

    for paper in papers:
        existing = load_fulltext(repo.db, paper.paper_id)
        if existing and existing.status == FulltextStatus.AVAILABLE:
            yield existing
            continue
        outcome = fetcher.fetch(paper)
        save_fulltext(
            repo.db,
            settings.papers_dir,
            outcome.record,
            outcome.pdf,
            pages_bytes(outcome.pages) if outcome.pages is not None else None,
        )
        yield outcome.record
    repo.export()


# --- Preuves ---------------------------------------------------------------------------


def add_evidence(
    repo: ProjectRepository,
    settings: Settings,
    *,
    paper_id: str,
    claim: str,
    quote: str,
    evidence_type: EvidenceType,
    page: int | None,
    actor: str,
) -> Evidence:
    """Enregistre une preuve après avoir vérifié que l'extrait figure dans la publication.

    `page` désigne une page du texte intégral ; sans page, l'extrait est cherché dans le résumé.
    """
    _require_state(repo, *_EVIDENCE_STATES)
    paper = _project_paper(repo, paper_id)
    if paper.status != PaperStatus.INCLUDED:
        raise ReviewError(f"{paper_id} n'est pas inclus (statut {paper.status}) : le trier d'abord")
    if (length := quote_length(quote)) < settings.policy.min_quote_chars:
        raise ReviewError(
            f"Extrait trop court ({length} lettres et chiffres, minimum {settings.policy.min_quote_chars}) : "
            "citer une phrase complète"
        )

    if page is None:
        if not paper.abstract:
            raise ReviewError(f"{paper_id} n'a pas de résumé")
        if not quote_in(quote, paper.abstract):
            raise ReviewError(f"Extrait introuvable dans le résumé de {paper_id}")
        location, text_sha256 = EvidenceLocation.ABSTRACT, sha256(paper.abstract.encode())
    else:
        try:
            pages, text_sha256 = read_pages(repo.db, settings.papers_dir, paper_id)
        except FileNotFoundError as exc:
            raise ReviewError(f"{exc} : utiliser une preuve du résumé (sans --page)") from exc
        if not 1 <= page <= len(pages):
            raise ReviewError(f"{paper_id} a {len(pages)} pages ; la page {page} n'existe pas")
        if not quote_in(quote, pages[page - 1]):
            found = find_quote_pages(quote, pages)
            hint = f" ; il figure page(s) {', '.join(map(str, found))}" if found else " ni ailleurs dans le texte"
            raise ReviewError(f"Extrait introuvable page {page} de {paper_id}{hint}")
        location = EvidenceLocation.FULL_TEXT

    evidence = Evidence(
        evidence_id=next_evidence_id(repo.db),
        project_id=repo.project_id,
        paper_id=paper_id,
        claim=claim.strip(),
        quote=quote.strip(),
        location=location,
        page=page,
        evidence_type=evidence_type,
        text_sha256=text_sha256,
        created_at=now(),
        actor=actor,
    )
    repo.add_evidence(evidence)
    return evidence


def withdraw_evidence(repo: ProjectRepository, evidence_id: str, reason: str) -> None:
    _require_state(repo, *_EVIDENCE_STATES)
    if not reason.strip():
        raise ReviewError("Le retrait d'une preuve exige une raison")
    try:
        repo.withdraw_evidence(evidence_id, reason.strip())
    except ValueError as exc:
        raise ReviewError(str(exc)) from exc
