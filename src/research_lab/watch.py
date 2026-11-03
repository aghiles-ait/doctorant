"""Exécution d'une recherche bibliographique multi-sources (outil du skill scientific-watch)."""

from research_lab import __version__
from research_lab.config import Settings
from research_lab.corpus import merge_hits
from research_lab.providers.base import Provider, ProviderError
from research_lab.schemas.search import SearchExecution, SearchQuery, SearchStatus, SourceResult, SourceStatus
from research_lab.storage.repositories import ProjectRepository, now
from research_lab.workflow.state import ResearchState


class SearchNotAllowed(Exception):
    pass


def _next_search_id(log: list[SearchExecution]) -> str:
    highest = max((int(s.search_id.split("-")[1]) for s in log), default=0)
    return f"SEARCH-{highest + 1:03d}"


def run_search(
    repo: ProjectRepository,
    settings: Settings,
    providers: list[Provider],
    query: SearchQuery,
    allow_partial: bool = False,
) -> SearchExecution:
    """Interroge chaque source, fusionne les résultats et consigne l'exécution.

    Si une source échoue, le corpus reste inchangé (statut FAILED), sauf si
    `allow_partial` est vrai (statut PARTIAL). Dans tous les cas l'exécution est journalisée.
    """
    project = repo.load_project()
    if project.state != ResearchState.LITERATURE_SEARCH:
        raise SearchNotAllowed(f"Le projet est à l'état {project.state}, la recherche exige {ResearchState.LITERATURE_SEARCH}")

    log = repo.load_search_log()
    search_id = _next_search_id(log)
    started_at = now()

    results: list[SourceResult] = []
    all_hits = []
    for provider in providers:
        try:
            outcome = provider.search(query)
        except (ProviderError, ValueError) as exc:
            results.append(SourceResult(source=provider.source, status=SourceStatus.ERROR, error=str(exc)))
            continue
        all_hits.extend(outcome.hits)
        results.append(
            SourceResult(
                source=provider.source,
                status=SourceStatus.OK,
                provider_query=outcome.provider_query,
                total_available=outcome.total_available,
                hits=len(outcome.hits),
                warnings=outcome.warnings,
            )
        )

    failed = any(r.status == SourceStatus.ERROR for r in results)
    if not failed:
        status = SearchStatus.COMPLETED
    elif allow_partial:
        status = SearchStatus.PARTIAL
    else:
        status = SearchStatus.FAILED

    new_ids: list[str] = []
    matched_ids: list[str] = []
    if status != SearchStatus.FAILED:
        papers = repo.load_papers()
        report = merge_hits(papers, all_hits, search_id, query.text, started_at)
        new_ids, matched_ids = report.new_paper_ids, report.matched_paper_ids

    execution = SearchExecution(
        search_id=search_id,
        project_id=project.project_id,
        query=query,
        sources=[p.source for p in providers],
        started_at=started_at,
        finished_at=now(),
        status=status,
        results=results,
        new_paper_ids=new_ids,
        matched_paper_ids=matched_ids,
        tool_version=__version__,
        config_hash=settings.config_hash(),
    )
    # Le journal est écrit avant le corpus : une provenance ne référence jamais une recherche absente du journal.
    repo.save_search_log([*log, execution])
    if status != SearchStatus.FAILED:
        repo.save_papers(papers)
    return execution
