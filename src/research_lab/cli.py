"""Interface en ligne de commande `research-lab`, appelée par les Skills."""

import getpass
import json
from datetime import date
from typing import Annotated

import typer
from pydantic import ValidationError

from research_lab.config import Settings, load_settings
from research_lab.corpus import CorpusStatus, check_corpus
from research_lab.providers import build_providers
from research_lab.schemas.paper import Source
from research_lab.schemas.search import SearchQuery, SearchStatus
from research_lab.storage.repositories import ProjectNotFound, ProjectRepository
from research_lab.watch import SearchNotAllowed, run_search
from research_lab.workflow.state import ResearchState
from research_lab.workflow.transitions import TransitionError

app = typer.Typer(help="Outils déterministes du laboratoire AI Research Doctorant.", no_args_is_help=True)
project_app = typer.Typer(help="Gestion des projets de recherche.", no_args_is_help=True)
watch_app = typer.Typer(help="Veille bibliographique (skill scientific-watch).", no_args_is_help=True)
corpus_app = typer.Typer(help="Consultation et contrôle du corpus.", no_args_is_help=True)
app.add_typer(project_app, name="project")
app.add_typer(watch_app, name="watch")
app.add_typer(corpus_app, name="corpus")

ProjectId = Annotated[str, typer.Argument(help="Identifiant du projet (ex. decentralized-ai-governance)")]
JsonFlag = Annotated[bool, typer.Option("--json", help="Sortie JSON")]


def _fail(message: str, code: int = 1) -> None:
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(code)


def _context(project_id: str) -> tuple[Settings, ProjectRepository]:
    try:
        settings = load_settings()
    except (FileNotFoundError, ValidationError) as exc:
        _fail(f"Configuration invalide : {exc}")
    return settings, ProjectRepository(settings.projects_dir, project_id)


def _require_project(repo: ProjectRepository) -> None:
    if not repo.exists():
        _fail(f"Projet introuvable : {repo.project_id} (créer avec `research-lab project init`)")


def _print_json(data: object) -> None:
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))


# --- project ---------------------------------------------------------------


@project_app.command("init")
def project_init(
    project_id: ProjectId,
    topic: Annotated[str, typer.Option(help="Sujet de recherche")],
) -> None:
    """Crée un projet à l'état NEW."""
    _, repo = _context(project_id)
    try:
        project = repo.create(topic, actor=getpass.getuser())
    except FileExistsError as exc:
        _fail(str(exc))
    except ValidationError as exc:
        _fail(f"Projet invalide : {exc}")
    typer.echo(f"Projet {project.project_id} créé dans {repo.dir} (état {project.state})")


@project_app.command("status")
def project_status(project_id: ProjectId, as_json: JsonFlag = False) -> None:
    """Affiche l'état du projet et un résumé du corpus."""
    _, repo = _context(project_id)
    _require_project(repo)
    project = repo.load_project()
    papers = repo.load_papers()
    log = repo.load_search_log()
    if as_json:
        _print_json({**project.model_dump(mode="json"), "paper_count": len(papers), "search_count": len(log)})
        return
    typer.echo(f"Projet : {project.project_id}\nSujet  : {project.topic}\nÉtat   : {project.state}")
    typer.echo(f"Corpus : {len(papers)} publications, {len(log)} recherches journalisées")


@project_app.command("transition")
def project_transition(
    project_id: ProjectId,
    target: Annotated[ResearchState, typer.Argument(help="État cible")],
) -> None:
    """Fait passer le projet à l'état suivant si les préconditions sont remplies."""
    _, repo = _context(project_id)
    _require_project(repo)
    try:
        project = repo.transition(target, actor=getpass.getuser())
    except TransitionError as exc:
        _fail(f"Transition refusée : {exc}")
    typer.echo(f"{project.project_id} : état {project.state}")


# --- watch -----------------------------------------------------------------


@watch_app.command("search")
def watch_search(
    project_id: ProjectId,
    query: Annotated[str, typer.Option("--query", "-q", help='Mots-clés ; "expression exacte" entre guillemets')],
    date_from: Annotated[str | None, typer.Option("--from", help="Date de début AAAA-MM-JJ")] = None,
    date_to: Annotated[str | None, typer.Option("--to", help="Date de fin AAAA-MM-JJ")] = None,
    sources: Annotated[str | None, typer.Option(help="Sources séparées par des virgules (défaut : config)")] = None,
    max_results: Annotated[int | None, typer.Option(help="Nombre maximal de résultats par source")] = None,
    allow_partial: Annotated[bool, typer.Option(help="Fusionner les résultats même si une source échoue")] = False,
    as_json: JsonFlag = False,
) -> None:
    """Interroge les sources académiques et enrichit le corpus du projet."""
    settings, repo = _context(project_id)
    _require_project(repo)
    try:
        selected = [Source(s.strip()) for s in sources.split(",")] if sources else settings.sources.default_sources
        search_query = SearchQuery(
            text=query,
            date_from=date.fromisoformat(date_from) if date_from else None,
            date_to=date.fromisoformat(date_to) if date_to else None,
            max_results=max_results or settings.sources.default_max_results,
        )
        providers = build_providers(settings, selected)
    except (ValueError, ValidationError) as exc:
        _fail(f"Paramètres invalides : {exc}")
    if allow_partial and not settings.policy.allow_partial_search:
        _fail("--allow-partial est interdit par config/research-policy.yaml (literature_search.allow_partial_search)")

    try:
        execution = run_search(repo, settings, providers, search_query, allow_partial=allow_partial)
    except (SearchNotAllowed, ProjectNotFound) as exc:
        _fail(str(exc))

    if as_json:
        _print_json(execution.model_dump(mode="json"))
    else:
        typer.echo(f"{execution.search_id} — statut {execution.status}")
        for r in execution.results:
            detail = f"{r.hits} résultats / {r.total_available} disponibles" if r.status == "ok" else f"ERREUR : {r.error}"
            typer.echo(f"  {r.source:<9} {detail}")
            for w in r.warnings:
                typer.echo(f"    avertissement : {w}")
        typer.echo(f"  nouvelles publications : {len(execution.new_paper_ids)}")
        typer.echo(f"  déjà connues           : {len(execution.matched_paper_ids)}")
    if execution.status == SearchStatus.FAILED:
        _fail("Recherche échouée : corpus inchangé (voir search-log.json)", code=2)
    if execution.status == SearchStatus.PARTIAL:
        typer.secho("Recherche partielle : au moins une source n'a pas répondu", fg=typer.colors.YELLOW, err=True)


@app.command("search-log")
def search_log(project_id: ProjectId, as_json: JsonFlag = False) -> None:
    """Affiche l'historique des recherches."""
    _, repo = _context(project_id)
    _require_project(repo)
    log = repo.load_search_log()
    if as_json:
        _print_json([s.model_dump(mode="json") for s in log])
        return
    for s in log:
        period = f"{s.query.date_from or '…'} → {s.query.date_to or '…'}"
        typer.echo(
            f"{s.search_id}  {s.started_at:%Y-%m-%d %H:%M}Z  {s.status:<9} {','.join(s.sources):<16} "
            f"{period}  +{len(s.new_paper_ids)} nouv.  « {s.query.text} »"
        )


# --- corpus ----------------------------------------------------------------


@corpus_app.command("list")
def corpus_list(
    project_id: ProjectId,
    source: Annotated[Source | None, typer.Option(help="Filtrer par source")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Liste les publications du corpus."""
    _, repo = _context(project_id)
    _require_project(repo)
    papers = repo.load_papers()
    if source:
        papers = [p for p in papers if any(prov.source == source for prov in p.provenance)]
    if as_json:
        _print_json([p.model_dump(mode="json", exclude={"abstract"}) for p in papers])
        return
    for p in papers:
        ident = p.doi or (f"arXiv:{p.arxiv_id}" if p.arxiv_id else p.openalex_id)
        year = p.published.year if p.published else "????"
        sources_ = ",".join(sorted({prov.source for prov in p.provenance}))
        typer.echo(f"{p.paper_id}  {year}  {ident:<38} [{sources_}]  {p.title[:90]}")
    typer.echo(f"{len(papers)} publications")


@corpus_app.command("show")
def corpus_show(project_id: ProjectId, paper_id: Annotated[str, typer.Argument()]) -> None:
    """Affiche toutes les métadonnées et la provenance d'une publication (JSON)."""
    _, repo = _context(project_id)
    _require_project(repo)
    for p in repo.load_papers():
        if p.paper_id == paper_id:
            _print_json(p.model_dump(mode="json"))
            return
    _fail(f"{paper_id} absent du corpus de {project_id}")


@corpus_app.command("check")
def corpus_check(project_id: ProjectId, as_json: JsonFlag = False) -> None:
    """Contrôle l'intégrité du corpus : renvoie OK, NEEDS_MORE_RESEARCH ou BLOCKED."""
    settings, repo = _context(project_id)
    _require_project(repo)
    result = check_corpus(repo.load_papers(), repo.load_search_log(), settings.policy.min_corpus_size)
    if as_json:
        _print_json({"status": result.status, "paper_count": result.paper_count, "errors": result.errors, "warnings": result.warnings})
    else:
        typer.echo(f"Statut : {result.status} ({result.paper_count} publications)")
        for e in result.errors:
            typer.echo(f"  erreur : {e}")
        for w in result.warnings:
            typer.echo(f"  avertissement : {w}")
    if result.status == CorpusStatus.BLOCKED:
        raise typer.Exit(2)
