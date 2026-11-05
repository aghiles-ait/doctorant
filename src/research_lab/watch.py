"""Exécution d'une recherche bibliographique multi-sources (outil du skill scientific-watch)."""

from research_lab import __version__
from research_lab.config import Settings
from research_lab.corpus import merge_hits
from research_lab.providers.base import Provider, ProviderError
from research_lab.schemas.search import SearchExecution, SearchQuery, SearchStatus, SourceResult, SourceStatus
from research_lab.storage.repositories import ProjectRepository, load_all_papers, next_search_id, now
from research_lab.workflow.state import ResearchState


class SearchNotAllowed(Exception):
    pass


def run_search(
    repo: ProjectRepository,
    settings: Settings,
    providers: list[Provider],
    query: SearchQuery,
    allow_partial: bool = False,
    gap_id: str | None = None,
) -> SearchExecution:
    """Interroge chaque source, fusionne les résultats et consigne l'exécution.

    La déduplication porte sur toute la base : une publication déjà connue d'un autre
    projet garde son identifiant et est rattachée à celui-ci.
    Si une source échoue, le corpus reste inchangé (statut FAILED), sauf si
    `allow_partial` est vrai (statut PARTIAL). Dans tous les cas l'exécution est journalisée.

    Pendant l'analyse des gaps, seules les recherches contradictoires sont permises (Q3) :
    `gap_id` désigne le gap dont on cherche des travaux qui le combleraient déjà.
    """
    project = repo.load_project()
    if gap_id is None and project.state != ResearchState.LITERATURE_SEARCH:
        hint = " (recherche contradictoire : préciser le gap)" if project.state == ResearchState.GAP_ANALYSIS else ""
        raise SearchNotAllowed(
            f"Le projet est à l'état {project.state}, la recherche exige {ResearchState.LITERATURE_SEARCH}{hint}"
        )
    if gap_id is not None:
        if project.state != ResearchState.GAP_ANALYSIS:
            raise SearchNotAllowed(f"Une recherche contradictoire exige l'état {ResearchState.GAP_ANALYSIS}")
        gap = next((g for g in repo.load_gaps() if g.gap_id == gap_id), None)
        if gap is None:
            raise SearchNotAllowed(f"{gap_id} n'existe pas dans le projet {project.project_id}")
        if not gap.active:
            raise SearchNotAllowed(f"{gap_id} est au statut {gap.status}")

    search_id = next_search_id(repo.db)
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
    merge_warnings: list[str] = []
    touched = []
    if status != SearchStatus.FAILED:
        papers = load_all_papers(repo.db)
        report = merge_hits(papers, all_hits, search_id, query.text, started_at)
        in_project = repo.paper_ids()
        new_ids = [pid for pid in report.touched_paper_ids if pid not in in_project]
        matched_ids = [pid for pid in report.touched_paper_ids if pid in in_project]
        merge_warnings = report.warnings
        touched_ids = set(report.touched_paper_ids)
        touched = [p for p in papers if p.paper_id in touched_ids]

    execution = SearchExecution(
        search_id=search_id,
        project_id=project.project_id,
        gap_id=gap_id,
        query=query,
        sources=[p.source for p in providers],
        started_at=started_at,
        finished_at=now(),
        status=status,
        results=results,
        new_paper_ids=new_ids,
        matched_paper_ids=matched_ids,
        merge_warnings=merge_warnings,
        tool_version=__version__,
        config_hash=settings.config_hash(),
    )
    repo.record_search(execution, touched)
    return execution
