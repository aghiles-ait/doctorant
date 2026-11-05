"""Interface en ligne de commande `research-lab`, appelée par les Skills."""

import getpass
import json
import sys
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel, ValidationError

from research_lab.config import Settings, load_settings
from research_lab.corpus import CorpusStatus, check_corpus
from research_lab.fulltext import FulltextFetcher
from research_lab.gaps import GapError, add_gap, check_gaps, revise_gap, set_alignment
from research_lab.schemas.gap import AlignmentDraft, GapDraft
from research_lab.providers import build_providers
from research_lab.review import ReviewError, add_evidence, decide, fetch_fulltexts, withdraw_evidence
from research_lab.schemas.evidence import EvidenceType, FulltextStatus
from research_lab.schemas.paper import PaperStatus, Source
from research_lab.schemas.search import SearchQuery, SearchStatus
from research_lab.storage.database import Database
from research_lab.storage.repositories import (
    FulltextTampered,
    ImportConflict,
    ProjectNotFound,
    ProjectRepository,
    import_project_files,
    load_fulltext,
    read_pages,
)
from research_lab.validation.outputs import check_literature_review
from research_lab.watch import SearchNotAllowed, run_search
from research_lab.schemas.gate import Gate, GateDecisionType
from research_lab.workflow.approvals import (
    GateError,
    decide_gate_1,
    human_check_failure,
    latest_submission,
    modified_artifacts,
    submit_gate_1,
)
from research_lab.workflow.state import ResearchState
from research_lab.workflow.transitions import TransitionError

app = typer.Typer(help="Outils déterministes du laboratoire AI Research Doctorant.", no_args_is_help=True)
project_app = typer.Typer(help="Gestion des projets de recherche.", no_args_is_help=True)
watch_app = typer.Typer(help="Veille bibliographique (skill scientific-watch).", no_args_is_help=True)
corpus_app = typer.Typer(help="Consultation et contrôle du corpus.", no_args_is_help=True)
db_app = typer.Typer(help="Base de connaissances partagée (knowledge/research.db).", no_args_is_help=True)
fulltext_app = typer.Typer(help="Texte intégral des publications incluses (accès libre).", no_args_is_help=True)
evidence_app = typer.Typer(help="Preuves extraites des publications (EV-xxx).", no_args_is_help=True)
review_app = typer.Typer(help="Contrôle de l'état de l'art (literature-review.md).", no_args_is_help=True)
gap_app = typer.Typer(help="Gaps scientifiques (GAP-xxx), skill gap-analysis.", no_args_is_help=True)
alignment_app = typer.Typer(help="Évaluation des gaps au regard des valeurs, skill values-alignment.", no_args_is_help=True)
gate_app = typer.Typer(help="Gate 1 : validation humaine de la problématique.", no_args_is_help=True)
app.add_typer(project_app, name="project")
app.add_typer(watch_app, name="watch")
app.add_typer(corpus_app, name="corpus")
app.add_typer(fulltext_app, name="fulltext")
app.add_typer(evidence_app, name="evidence")
app.add_typer(review_app, name="review")
app.add_typer(gap_app, name="gap")
app.add_typer(alignment_app, name="alignment")
app.add_typer(gate_app, name="gate")
app.add_typer(db_app, name="db")

ProjectId = Annotated[str, typer.Argument(help="Identifiant du projet (ex. decentralized-ai-governance)")]
JsonFlag = Annotated[bool, typer.Option("--json", help="Sortie JSON")]


def _fail(message: str, code: int = 1) -> None:
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(code)


def _settings_and_db() -> tuple[Settings, Database]:
    try:
        settings = load_settings()
    except (FileNotFoundError, ValidationError) as exc:
        _fail(f"Configuration invalide : {exc}")
    return settings, Database(settings.db_path)


def _context(project_id: str) -> tuple[Settings, ProjectRepository]:
    settings, db = _settings_and_db()
    return settings, ProjectRepository(db, settings.projects_dir, project_id)


def _require_project(repo: ProjectRepository) -> None:
    if repo.has_unimported_files():
        _fail(f"Le projet {repo.project_id} n'est pas encore dans la base : `research-lab db import-files {repo.project_id}`")
    if not repo.exists():
        _fail(f"Projet introuvable : {repo.project_id} (créer avec `research-lab project init`)")


def _print_json(data: object) -> None:
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _read_draft[M: BaseModel](model: type[M], path: str) -> M:
    """Lit un brouillon JSON (fichier, ou `-` pour l'entrée standard) et le valide."""
    try:
        raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
        return model.model_validate_json(raw)
    except OSError as exc:
        _fail(f"Lecture impossible : {exc}")
    except ValidationError as exc:
        _fail(f"Contenu invalide :\n{exc}")


DraftFile = Annotated[str, typer.Option("--file", help="Brouillon JSON (chemin, ou - pour l'entrée standard)")]


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
    settings, repo = _context(project_id)
    _require_project(repo)
    try:
        project = repo.transition(target, actor=getpass.getuser(), policy=settings.policy)
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
    for_gap: Annotated[str | None, typer.Option("--for-gap", help="Recherche contradictoire pour ce gap (état GAP_ANALYSIS)")] = None,
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
        execution = run_search(repo, settings, providers, search_query, allow_partial=allow_partial, gap_id=for_gap)
    except (SearchNotAllowed, ProjectNotFound) as exc:
        _fail(str(exc))

    if as_json:
        _print_json(execution.model_dump(mode="json"))
    else:
        target = f" (recherche contradictoire, {execution.gap_id})" if execution.gap_id else ""
        typer.echo(f"{execution.search_id} — statut {execution.status}{target}")
        for r in execution.results:
            detail = f"{r.hits} résultats / {r.total_available} disponibles" if r.status == "ok" else f"ERREUR : {r.error}"
            typer.echo(f"  {r.source:<9} {detail}")
            for w in r.warnings:
                typer.echo(f"    avertissement : {w}")
        typer.echo(f"  nouvelles publications : {len(execution.new_paper_ids)}")
        typer.echo(f"  déjà connues           : {len(execution.matched_paper_ids)}")
        for w in execution.merge_warnings:
            typer.echo(f"  doublon probable : {w}")
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
        target = f"  [{s.gap_id}]" if s.gap_id else ""
        typer.echo(
            f"{s.search_id}  {s.started_at:%Y-%m-%d %H:%M}Z  {s.status:<9} {','.join(s.sources):<16} "
            f"{period}  +{len(s.new_paper_ids)} nouv.  « {s.query.text} »{target}"
        )


# --- corpus ----------------------------------------------------------------


@corpus_app.command("list")
def corpus_list(
    project_id: ProjectId,
    source: Annotated[Source | None, typer.Option(help="Filtrer par source")] = None,
    status: Annotated[PaperStatus | None, typer.Option(help="Filtrer par statut de tri")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Liste les publications du corpus."""
    _, repo = _context(project_id)
    _require_project(repo)
    papers = repo.load_papers()
    if source:
        papers = [p for p in papers if any(prov.source == source for prov in p.provenance)]
    if status:
        papers = [p for p in papers if p.status == status]
    if as_json:
        _print_json([p.model_dump(mode="json", exclude={"abstract"}) for p in papers])
        return
    for p in papers:
        ident = p.doi or (f"arXiv:{p.arxiv_id}" if p.arxiv_id else p.openalex_id)
        year = p.published.year if p.published else "????"
        sources_ = ",".join(sorted({prov.source for prov in p.provenance}))
        typer.echo(f"{p.paper_id}  {p.status:<9}  {year}  {ident:<38} [{sources_}]  {p.title[:90]}")
    typer.echo(f"{len(papers)} publications")


@corpus_app.command("decide")
def corpus_decide(
    project_id: ProjectId,
    paper_id: Annotated[str, typer.Argument()],
    include: Annotated[bool | None, typer.Option("--include/--exclude", help="Inclure ou exclure")] = None,
    reason: Annotated[str, typer.Option(help="Justification au regard des critères de scope.md")] = "",
) -> None:
    """Trie une publication (LITERATURE_REVIEW, ou candidates en GAP_ANALYSIS) ; la décision est historisée."""
    _, repo = _context(project_id)
    _require_project(repo)
    if include is None:
        _fail("Préciser --include ou --exclude")
    if not reason.strip():
        _fail("--reason est obligatoire")
    decision = PaperStatus.INCLUDED if include else PaperStatus.EXCLUDED
    try:
        decide(repo, paper_id, decision, reason, actor=getpass.getuser())
    except ReviewError as exc:
        _fail(str(exc))
    remaining = sum(p.status == PaperStatus.CANDIDATE for p in repo.load_papers())
    typer.echo(f"{paper_id} : {decision} ({remaining} publications restent à trier)")


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


# --- fulltext ----------------------------------------------------------------


@fulltext_app.command("fetch")
def fulltext_fetch(
    project_id: ProjectId,
    paper: Annotated[list[str] | None, typer.Option("--paper", help="Publication(s) ciblée(s) ; défaut : toutes les incluses")] = None,
) -> None:
    """Télécharge le PDF en accès libre et en extrait le texte page par page."""
    settings, repo = _context(project_id)
    _require_project(repo)
    counts = {status: 0 for status in FulltextStatus}
    try:
        for record in fetch_fulltexts(repo, settings, FulltextFetcher(settings), paper):
            counts[record.status] += 1
            detail = f"{record.page_count} pages" if record.status == FulltextStatus.AVAILABLE else record.error
            typer.echo(f"{record.paper_id}  {record.status:<11}  {detail}")
    except ReviewError as exc:
        _fail(str(exc))
    typer.echo(", ".join(f"{n} {s}" for s, n in counts.items()))


@fulltext_app.command("status")
def fulltext_status(project_id: ProjectId, as_json: JsonFlag = False) -> None:
    """État du texte intégral pour chaque publication incluse."""
    _, repo = _context(project_id)
    _require_project(repo)
    rows = []
    for p in repo.load_papers():
        if p.status != PaperStatus.INCLUDED:
            continue
        record = load_fulltext(repo.db, p.paper_id)
        rows.append({
            "paper_id": p.paper_id,
            "status": record.status if record else "not_attempted",
            "pages": record.page_count if record else None,
            "error": record.error if record else None,
            "title": p.title,
        })
    if as_json:
        _print_json(rows)
        return
    for r in rows:
        detail = f"{r['pages']} pages" if r["pages"] else (r["error"] or "")
        typer.echo(f"{r['paper_id']}  {r['status']:<13}  {r['title'][:60]:<60}  {detail[:80]}")


@fulltext_app.command("show")
def fulltext_show(
    project_id: ProjectId,
    paper_id: Annotated[str, typer.Argument()],
    page: Annotated[int | None, typer.Option(help="Afficher une seule page")] = None,
) -> None:
    """Affiche le texte intégral extrait, avec les numéros de page à citer dans les preuves."""
    settings, repo = _context(project_id)
    _require_project(repo)
    if repo.get_paper(paper_id) is None:
        _fail(f"{paper_id} absent du corpus de {project_id}")
    try:
        pages, _ = read_pages(repo.db, settings.papers_dir, paper_id)
    except (FileNotFoundError, FulltextTampered) as exc:
        _fail(str(exc))
    if page is not None and not 1 <= page <= len(pages):
        _fail(f"{paper_id} a {len(pages)} pages")
    for number, text in enumerate(pages, start=1):
        if page is None or number == page:
            typer.echo(f"===== {paper_id} — page {number}/{len(pages)} =====\n{text}\n")


# --- evidence ----------------------------------------------------------------


@evidence_app.command("add")
def evidence_add(
    project_id: ProjectId,
    paper: Annotated[str, typer.Option(help="Publication source (PAPER-xxx), incluse")],
    claim: Annotated[str, typer.Option(help="Affirmation que l'extrait soutient, reformulée")],
    quote: Annotated[str, typer.Option(help="Extrait exact, recopié du texte")],
    evidence_type: Annotated[EvidenceType, typer.Option("--type", help="Nature de la preuve")],
    page: Annotated[int | None, typer.Option(help="Page du texte intégral (sans --page : extrait du résumé)")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Enregistre une preuve si l'extrait figure bien dans la publication."""
    settings, repo = _context(project_id)
    _require_project(repo)
    try:
        evidence = add_evidence(
            repo, settings, paper_id=paper, claim=claim, quote=quote, evidence_type=evidence_type, page=page,
            actor=getpass.getuser(),
        )
    except (ReviewError, FulltextTampered) as exc:
        _fail(f"Preuve refusée : {exc}")
    if as_json:
        _print_json(evidence.model_dump(mode="json"))
    else:
        where = f"page {evidence.page}" if evidence.page else "résumé"
        typer.echo(f"{evidence.evidence_id} enregistrée ({evidence.paper_id}, {where})")


@evidence_app.command("list")
def evidence_list(
    project_id: ProjectId,
    paper: Annotated[str | None, typer.Option(help="Filtrer par publication")] = None,
    withdrawn: Annotated[bool, typer.Option(help="Inclure les preuves retirées")] = False,
    as_json: JsonFlag = False,
) -> None:
    """Liste les preuves du projet."""
    _, repo = _context(project_id)
    _require_project(repo)
    items = [e for e in repo.load_evidence() if (withdrawn or e.active) and (paper is None or e.paper_id == paper)]
    if as_json:
        _print_json([e.model_dump(mode="json") for e in items])
        return
    for e in items:
        where = f"p.{e.page}" if e.page else "résumé"
        flag = "  [RETIRÉE]" if not e.active else ""
        typer.echo(f"{e.evidence_id}  {e.paper_id}  {where:<7} {e.evidence_type:<18} {e.claim[:80]}{flag}")
    typer.echo(f"{len(items)} preuves")


@evidence_app.command("withdraw")
def evidence_withdraw(
    project_id: ProjectId,
    evidence_id: Annotated[str, typer.Argument()],
    reason: Annotated[str, typer.Option(help="Raison du retrait")] = "",
) -> None:
    """Retire une preuve (elle reste dans l'historique, mais ne peut plus être citée)."""
    _, repo = _context(project_id)
    _require_project(repo)
    try:
        withdraw_evidence(repo, evidence_id, reason)
    except ReviewError as exc:
        _fail(str(exc))
    typer.echo(f"{evidence_id} retirée")


# --- review ------------------------------------------------------------------


@review_app.command("check")
def review_check(project_id: ProjectId, as_json: JsonFlag = False) -> None:
    """Vérifie les citations de literature-review.md (PAPER-xxx et EV-xxx)."""
    _, repo = _context(project_id)
    _require_project(repo)
    path = repo.dir / "literature-review.md"
    text = path.read_text(encoding="utf-8") if path.exists() else None
    result = check_literature_review(text, repo.load_papers(), repo.load_evidence())
    if as_json:
        _print_json({"errors": result.errors, "warnings": result.warnings,
                     "cited_papers": result.cited_papers, "cited_evidence": result.cited_evidence})
    else:
        status = "BLOCKED" if result.errors else "OK"
        typer.echo(f"Statut : {status} ({len(result.cited_papers)} publications et {len(result.cited_evidence)} preuves citées)")
        for e in result.errors:
            typer.echo(f"  erreur : {e}")
        for w in result.warnings:
            typer.echo(f"  avertissement : {w}")
    if result.errors:
        raise typer.Exit(2)


# --- gap ---------------------------------------------------------------------


@gap_app.command("add")
def gap_add(
    project_id: ProjectId,
    file: DraftFile,
    reason: Annotated[str, typer.Option(help="Origine du gap (facultatif)")] = "",
    as_json: JsonFlag = False,
) -> None:
    """Enregistre un gap (GAP-xxx) à partir d'un brouillon JSON ; ses preuves sont vérifiées."""
    settings, repo = _context(project_id)
    _require_project(repo)
    draft = _read_draft(GapDraft, file)
    try:
        gap = add_gap(repo, settings, draft, reason, actor=getpass.getuser())
    except GapError as exc:
        _fail(f"Gap refusé : {exc}")
    if as_json:
        _print_json(gap.model_dump(mode="json"))
    else:
        typer.echo(f"{gap.gap_id} enregistré ({gap.status}, preuves {gap.evidence_strength})")


@gap_app.command("revise")
def gap_revise(
    project_id: ProjectId,
    gap_id: Annotated[str, typer.Argument()],
    file: DraftFile,
    reason: Annotated[str, typer.Option(help="Raison de la révision")] = "",
    as_json: JsonFlag = False,
) -> None:
    """Remplace le contenu d'un gap par une nouvelle version (l'historique est conservé)."""
    settings, repo = _context(project_id)
    _require_project(repo)
    draft = _read_draft(GapDraft, file)
    try:
        gap = revise_gap(repo, settings, gap_id, draft, reason, actor=getpass.getuser())
    except GapError as exc:
        _fail(f"Révision refusée : {exc}")
    if as_json:
        _print_json(gap.model_dump(mode="json"))
    else:
        typer.echo(f"{gap.gap_id} version {gap.version} ({gap.status}, preuves {gap.evidence_strength})")


@gap_app.command("list")
def gap_list(project_id: ProjectId, as_json: JsonFlag = False) -> None:
    """Liste les gaps du projet (version courante)."""
    _, repo = _context(project_id)
    _require_project(repo)
    gaps = repo.gaps_export()
    if as_json:
        _print_json(gaps)
        return
    for g in gaps:
        typer.echo(
            f"{g['gap_id']}  v{g['version']}  {g['status']:<9}  {g['evidence_strength']:<6}  "
            f"{g['novelty_assessment']:<21}  {len(g['contradictory_searches'])} rech.  {g['title'][:70]}"
        )
    typer.echo(f"{len(gaps)} gaps")


@gap_app.command("show")
def gap_show(
    project_id: ProjectId,
    gap_id: Annotated[str, typer.Argument()],
    history: Annotated[bool, typer.Option(help="Toutes les versions")] = False,
) -> None:
    """Affiche un gap (JSON). Les champs du brouillon peuvent être repris pour `gap revise`."""
    _, repo = _context(project_id)
    _require_project(repo)
    if history:
        versions = repo.gap_history(gap_id)
        if not versions:
            _fail(f"{gap_id} n'existe pas dans le projet {project_id}")
        _print_json([v.model_dump(mode="json") for v in versions])
        return
    gap = next((g for g in repo.gaps_export() if g["gap_id"] == gap_id), None)
    if gap is None:
        _fail(f"{gap_id} n'existe pas dans le projet {project_id}")
    _print_json(gap)


@gap_app.command("check")
def gap_check(project_id: ProjectId, as_json: JsonFlag = False) -> None:
    """Contrôle l'analyse des gaps et leur évaluation : OK, NEEDS_MORE_RESEARCH ou BLOCKED."""
    settings, repo = _context(project_id)
    _require_project(repo)
    result = check_gaps(repo, settings)
    if as_json:
        _print_json({"status": result.status, "errors": result.errors, "warnings": result.warnings})
    else:
        typer.echo(f"Statut : {result.status}")
        for e in result.errors:
            typer.echo(f"  erreur : {e}")
        for w in result.warnings:
            typer.echo(f"  avertissement : {w}")
    if result.status == "BLOCKED":
        raise typer.Exit(2)


# --- alignment -------------------------------------------------------------------


@alignment_app.command("set")
def alignment_set(
    project_id: ProjectId,
    gap_id: Annotated[str, typer.Argument()],
    file: DraftFile,
    as_json: JsonFlag = False,
) -> None:
    """Évalue un gap au regard de chaque valeur de research-values.yaml et calcule sa priorité."""
    settings, repo = _context(project_id)
    _require_project(repo)
    draft = _read_draft(AlignmentDraft, file)
    try:
        alignment = set_alignment(repo, settings, gap_id, draft, actor=getpass.getuser())
    except GapError as exc:
        _fail(f"Évaluation refusée : {exc}")
    if as_json:
        _print_json(alignment.model_dump(mode="json"))
    else:
        typer.echo(
            f"{gap_id} : alignement {alignment.alignment_score:.2f}, priorité {alignment.priority_score:.2f}"
        )


@alignment_app.command("show")
def alignment_show(project_id: ProjectId, as_json: JsonFlag = False) -> None:
    """Classement des gaps actifs par priorité (alignement sur les valeurs et force des preuves)."""
    _, repo = _context(project_id)
    _require_project(repo)
    ranking = repo.alignment_export()
    if as_json:
        _print_json(ranking)
        return
    for r in ranking:
        if r["priority_score"] is None:
            detail = "non évalué"
        else:
            detail = f"priorité {r['priority_score']:.2f}  alignement {r['alignment_score']:.2f}"
            detail += "  [PÉRIMÉE]" if r["stale"] else ""
        typer.echo(f"{r['rank']:>2}. {r['gap_id']}  {r['status']:<9}  {r['evidence_strength']:<6}  {detail}  {r['title'][:60]}")


# --- gate --------------------------------------------------------------------


@gate_app.command("submit")
def gate_submit(project_id: ProjectId) -> None:
    """Soumet l'analyse des gaps à la Gate 1 : fige les livrables, puis attend la décision humaine."""
    settings, repo = _context(project_id)
    _require_project(repo)
    try:
        submission = submit_gate_1(repo, settings, actor=getpass.getuser())
    except GateError as exc:
        _fail(f"Soumission refusée : {exc}")
    typer.echo(f"{project_id} : soumis à la Gate 1 (tour {submission.round}, gap check {submission.check_status})")
    typer.echo(f"Décision humaine : `research-lab gate status {project_id}`, puis `gate approve` ou `gate revise`")


@gate_app.command("status")
def gate_status(project_id: ProjectId, as_json: JsonFlag = False) -> None:
    """Dossier soumis à la Gate 1 : gaps classés, contrôles, intégrité des livrables, décisions passées."""
    _, repo = _context(project_id)
    _require_project(repo)
    rounds = repo.gate_export(Gate.GATE_1)
    submission = latest_submission(repo)
    modified = modified_artifacts(repo, submission) if submission else []
    ranking = [r for r in repo.alignment_export() if submission and r["gap_id"] in submission.gap_versions]
    if as_json:
        _print_json({"state": repo.load_project().state, "rounds": rounds, "ranking": ranking,
                     "modified_artifacts": modified})
        return
    typer.echo(f"État : {repo.load_project().state}")
    if submission is None:
        typer.echo("Aucune soumission à la Gate 1")
        return
    typer.echo(f"Tour {submission.round}, soumis le {submission.submitted_at:%Y-%m-%d %H:%M}Z par {submission.actor}")
    typer.echo(f"gap check à la soumission : {submission.check_status}")
    for w in submission.check_warnings:
        typer.echo(f"  avertissement : {w}")
    typer.echo("Gaps soumis (par priorité) :")
    for r in ranking:
        priority = "non évalué" if r["priority_score"] is None else f"priorité {r['priority_score']:.2f}"
        typer.echo(f"  {r['rank']:>2}. {r['gap_id']}  {r['status']:<9}  {r['evidence_strength']:<6}  {priority}  {r['title'][:70]}")
    typer.echo("Détail : gaps.json, alignment.json, literature-review.md ; `gap show <projet> GAP-xxx`")
    typer.echo(f"Livrables : {'modifiés depuis la soumission : ' + ', '.join(modified) if modified else 'inchangés'}")
    for item in rounds:
        if (d := item["decision"]) is not None:
            gaps = f" — {', '.join(d['selected_gaps'])}" if d["selected_gaps"] else ""
            typer.echo(f"Tour {item['round']} : {d['decision']} par {d['approver']}{gaps} — « {d['comment']} »")


@gate_app.command("verify")
def gate_verify(project_id: ProjectId) -> None:
    """Vérifie que les livrables soumis à la Gate 1 n'ont pas changé depuis (code 2 sinon)."""
    _, repo = _context(project_id)
    _require_project(repo)
    submission = latest_submission(repo)
    if submission is None:
        _fail("Aucune soumission à la Gate 1")
    if modified := modified_artifacts(repo, submission):
        typer.echo(f"Modifiés depuis la soumission du tour {submission.round} : {', '.join(modified)}")
        raise typer.Exit(2)
    typer.echo(f"Livrables identiques à la soumission du tour {submission.round}")


def _human_decision(project_id: str, decision: GateDecisionType, comment: str, gaps: list[str]) -> None:
    _, repo = _context(project_id)
    _require_project(repo)
    if reason := human_check_failure():
        _fail(f"Décision refusée : {reason}")
    submission = latest_submission(repo)
    if submission is not None and decision == GateDecisionType.APPROVE:
        current = {g.gap_id: g for g in repo.load_gaps()}
        for gap_id in gaps:
            if gap := current.get(gap_id):
                flag = "  (candidate : insuffisamment établi)" if gap.status == "candidate" else ""
                typer.echo(f"  retenu : {gap_id} v{gap.version} — {gap.title}{flag}")
    target = "PROBLEM_FORMULATION" if decision == GateDecisionType.APPROVE else "LITERATURE_SEARCH"
    typer.echo(f"Décision : {decision} → {target}\nCommentaire : {comment}")
    if typer.prompt(f"Pour confirmer, tapez l'identifiant du projet ({project_id})") != project_id:
        _fail("Confirmation incorrecte : rien n'a été enregistré")
    try:
        record = decide_gate_1(repo, decision, comment, approver=getpass.getuser(), selected_gaps=gaps)
    except GateError as exc:
        _fail(f"Décision refusée : {exc}")
    typer.echo(f"Gate 1, tour {record.round} : {record.decision} enregistré par {record.approver} (gate-1.json)")


@gate_app.command("approve")
def gate_approve(
    project_id: ProjectId,
    gap: Annotated[list[str], typer.Option("--gap", help="Gap retenu (répéter l'option pour plusieurs)")],
    comment: Annotated[str, typer.Option(help="Justification du choix")],
) -> None:
    """[HUMAIN] Approuve la problématique : les gaps retenus passent à la formulation du problème."""
    _human_decision(project_id, GateDecisionType.APPROVE, comment, gap)


@gate_app.command("revise")
def gate_revise(
    project_id: ProjectId,
    comment: Annotated[str, typer.Option(help="Ce qu'il faut chercher ou corriger (lu par l'agent)")],
) -> None:
    """[HUMAIN] Demande une révision : retour à la recherche bibliographique, travail existant conservé."""
    _human_decision(project_id, GateDecisionType.REVISE, comment, [])


# --- db ----------------------------------------------------------------------


@db_app.command("import-files")
def db_import_files(
    project_id: Annotated[str | None, typer.Argument(help="Projet à importer (défaut : tous ceux non importés)")] = None,
) -> None:
    """Importe dans la base les projets créés au sprint 1 (fichiers JSON), en gardant leurs identifiants."""
    settings, db = _settings_and_db()
    if project_id:
        candidates = [project_id]
    else:
        candidates = sorted(
            d.name for d in settings.projects_dir.glob("*")
            if ProjectRepository(db, settings.projects_dir, d.name).has_unimported_files()
        )
    if not candidates:
        typer.echo("Aucun projet à importer")
        return
    for pid in candidates:
        try:
            count = import_project_files(db, settings.projects_dir, pid)
        except (ImportConflict, ProjectNotFound, ValidationError) as exc:
            _fail(f"Import de {pid} refusé, base inchangée : {exc}")
        typer.echo(f"{pid} : {count} publications importées (originaux dans {pid}/migration-backup/)")


@db_app.command("info")
def db_info(as_json: JsonFlag = False) -> None:
    """Résumé de la base partagée : projets, publications, recherches."""
    settings, db = _settings_and_db()
    count = lambda table: db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: E731
    projects = [
        dict(r) for r in db.conn.execute(
            "SELECT p.project_id, p.state, COUNT(pp.paper_id) AS papers FROM projects p "
            "LEFT JOIN project_papers pp USING (project_id) GROUP BY p.project_id ORDER BY p.project_id"
        )
    ]
    info = {
        "path": str(settings.db_path),
        "schema_version": db.conn.execute("PRAGMA user_version").fetchone()[0],
        "papers": count("papers"),
        "searches": count("searches"),
        "projects": projects,
    }
    if as_json:
        _print_json(info)
        return
    typer.echo(f"Base   : {info['path']} (schéma v{info['schema_version']})")
    typer.echo(f"Corpus : {info['papers']} publications, {info['searches']} recherches")
    for p in projects:
        typer.echo(f"  {p['project_id']:<32} {p['state']:<20} {p['papers']} publications")
