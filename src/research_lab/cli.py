"""Interface en ligne de commande `research-lab`, appelée par les Skills."""

import dataclasses
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
from research_lab.critique import CritiqueError, check_critique, respond, submit_review
from research_lab.evaluation import (
    EvaluationError,
    current_ratings,
    evaluation_summary,
    quality_report,
    rating_targets,
    record_ratings,
)
from research_lab.fulltext import FulltextFetcher
from research_lab.schemas.evaluation import Rating
from research_lab.gaps import GapError, add_gap, check_gaps, revise_gap, set_alignment
from research_lab.schemas.gap import AlignmentDraft, GapDraft
from research_lab.proposal import ProposalError, check_proposal_file, write_references
from research_lab.providers import build_providers
from research_lab.questions import QuestionError, add_question, check_questions, revise_question
from research_lab.reading import check_reading, coverage, outline, parse_page_range, select_pages
from research_lab.resume import resume_report
from research_lab.review import ReviewError, add_evidence, decide, fetch_fulltexts, withdraw_evidence
from research_lab.schemas.evidence import EvidenceType, FulltextStatus
from research_lab.schemas.paper import PaperStatus, Source
from research_lab.schemas.critique import ResponseAction, ResponseDraft, ReviewDraft
from research_lab.schemas.question import QuestionDraft
from research_lab.schemas.solution import ComparisonDraft, SolutionDraft
from research_lab.solutions import SolutionError, add_solution, check_solutions, revise_solution, set_comparison
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
from research_lab.schemas.gate import Gate, GateDecisionType, GateSubmission
from research_lab.workflow.approvals import (
    DECISION_TARGETS,
    GateError,
    current_gate,
    decide_gate_1,
    decide_gate_2,
    human_check_failure,
    latest_submission,
    modified_artifacts,
    submit_gate_1,
    submit_gate_2,
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
question_app = typer.Typer(
    help="Questions de recherche et hypothèses falsifiables (RQ-xxx), skill problem-formulation.", no_args_is_help=True
)
solution_app = typer.Typer(
    help="Solutions conceptuelles (SOL-xxx) et leur comparaison, skill solution-architect.", no_args_is_help=True
)
critique_app = typer.Typer(
    help="Revue critique indépendante (agent scientific-reviewer, skill scientific-critic).", no_args_is_help=True
)
proposal_app = typer.Typer(
    help="Research Proposal (research-proposal.md, references.bib), skill research-writer.", no_args_is_help=True
)
gate_app = typer.Typer(
    help="Validations humaines : Gate 1 (gaps retenus), Gate 2 (Research Proposal).", no_args_is_help=True
)
eval_app = typer.Typer(
    help="Évaluation de la qualité scientifique : indicateurs Q1 à Q5, notation humaine des gaps et hypothèses.",
    no_args_is_help=True,
)
app.add_typer(project_app, name="project")
app.add_typer(watch_app, name="watch")
app.add_typer(corpus_app, name="corpus")
app.add_typer(fulltext_app, name="fulltext")
app.add_typer(evidence_app, name="evidence")
app.add_typer(review_app, name="review")
app.add_typer(gap_app, name="gap")
app.add_typer(alignment_app, name="alignment")
app.add_typer(gate_app, name="gate")
app.add_typer(question_app, name="question")
app.add_typer(solution_app, name="solution")
app.add_typer(critique_app, name="critique")
app.add_typer(proposal_app, name="proposal")
app.add_typer(eval_app, name="eval")
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
    return settings, ProjectRepository(db, settings.projects_dir, project_id, settings.papers_dir)


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


@project_app.command("resume")
def project_resume(
    project_id: ProjectId,
    repair: Annotated[bool, typer.Option("--repair", help="Régénérer les exports périmés depuis la base")] = False,
    as_json: JsonFlag = False,
) -> None:
    """Où reprendre un projet interrompu : état, étape, instructions humaines, ce qui bloque la suite."""
    settings, repo = _context(project_id)
    _require_project(repo)
    if repair:
        repo.export()
    report = resume_report(repo, settings)
    if as_json:
        _print_json(dataclasses.asdict(report))
        return
    since = f" depuis {report.since.isoformat()}" if report.since else ""
    typer.echo(f"Projet : {report.project_id}\nÉtat   : {report.state}{since}"
               + (" (transition forcée)" if report.last_change_forced else ""))
    typer.echo(f"Étape  : {report.step}\nAction : {report.action}")
    if report.human_instructions:
        typer.echo(f"Décision humaine : {report.human_instructions}")
    for target, blockers in report.next_steps.items():
        typer.echo(f"→ {target} : " + ("possible" if not blockers else "bloqué"))
        for blocker in blockers:
            typer.echo(f"    - {blocker}")
    if report.stale_exports:
        typer.echo(f"Exports périmés : {', '.join(report.stale_exports)} (`project resume {project_id} --repair`)")


@project_app.command("transition")
def project_transition(
    project_id: ProjectId,
    target: Annotated[ResearchState, typer.Argument(help="État cible")],
    force: Annotated[
        bool, typer.Option("--force", help="N'importe quel état, sans précondition (hors gates) ; tracé dans l'historique")
    ] = False,
) -> None:
    """Fait passer le projet à l'état suivant si les préconditions sont remplies."""
    settings, repo = _context(project_id)
    _require_project(repo)
    try:
        project = repo.transition(target, actor=getpass.getuser(), policy=settings.policy, force=force)
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
    result = check_corpus(
        repo.load_papers(), repo.load_search_log(), settings.policy.min_corpus_size,
        settings.policy.max_examinable_results,
    )
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
        try:
            reading = repo.paper_coverage(p.paper_id)
        except FulltextTampered as exc:
            _fail(str(exc))
        rows.append({
            "paper_id": p.paper_id,
            "status": record.status if record else "not_attempted",
            "pages": record.page_count if record else None,
            "error": record.error if record else None,
            "reading": reading.as_dict() if reading else None,
            "reading_summary": reading.summary() if reading else None,
            "title": p.title,
        })
    if as_json:
        _print_json(rows)
        return
    for r in rows:
        detail = r["reading_summary"] or r["error"] or ""
        typer.echo(f"{r['paper_id']}  {r['status']:<13}  {r['title'][:60]:<60}  {detail[:120]}")
    complete = sum(1 for r in rows if r["reading"] and r["reading"]["complete"])
    available = sum(1 for r in rows if r["reading"])
    typer.echo(f"{complete}/{available} textes intégraux disponibles lus en entier (texte principal)")


@fulltext_app.command("show")
def fulltext_show(
    project_id: ProjectId,
    paper_id: Annotated[str, typer.Argument()],
    page: Annotated[int | None, typer.Option(help="Afficher une seule page")] = None,
    pages: Annotated[str | None, typer.Option(help="Afficher une plage de pages, par exemple 3-7")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Sans option : plan du texte (pages, taille, lues ou non). Avec --page/--pages : texte à citer.

    Chaque appel affiche au plus `fulltext.max_show_chars` caractères (une sortie trop longue peut être
    tronquée avant d'atteindre le modèle) ; les pages affichées sont enregistrées comme lues.
    """
    settings, repo = _context(project_id)
    _require_project(repo)
    if repo.get_paper(paper_id) is None:
        _fail(f"{paper_id} absent du corpus de {project_id}")
    try:
        text_pages, digest = read_pages(repo.db, settings.papers_dir, paper_id)
    except (FileNotFoundError, FulltextTampered) as exc:
        _fail(str(exc))
    if page is not None and pages is not None:
        _fail("--page et --pages sont exclusifs")
    read = repo.pages_read(paper_id, digest)

    if page is None and pages is None:
        rows = outline(text_pages, read)
        summary = coverage(paper_id, text_pages, read).summary()
        if as_json:
            _print_json({"paper_id": paper_id, "summary": summary, "pages": rows})
            return
        typer.echo(f"{paper_id} : {len(text_pages)} pages ; {summary}")
        for r in rows:
            mark = "lue" if r["read"] else "   "
            refs = " [réf.]" if r["references"] else ""
            typer.echo(f"  p.{r['page']:<4} {r['chars']:>6} car.  {mark}{refs}  {r['first_line']}")
        typer.echo(f"Lire : fulltext show {project_id} {paper_id} --pages N-M "
                   f"(au plus {settings.sources.fulltext.max_show_chars} caractères par appel)")
        return

    try:
        first, last = parse_page_range(pages if pages is not None else str(page), len(text_pages))
    except ValueError as exc:
        _fail(f"{paper_id} : {exc}")
    shown = select_pages(text_pages, first, last, settings.sources.fulltext.max_show_chars)
    repo.record_page_reads(paper_id, shown, digest)
    for number in shown:
        typer.echo(f"===== {paper_id} — page {number}/{len(text_pages)} =====\n{text_pages[number - 1]}\n")
    if shown[-1] < last:
        typer.echo(f"===== limite de {settings.sources.fulltext.max_show_chars} caractères atteinte : "
                   f"pages {shown[-1] + 1}-{last} non affichées, relancer avec --pages {shown[-1] + 1}-{last} =====")


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
    """Vérifie les citations de literature-review.md (PAPER-xxx et EV-xxx) et la lecture des textes intégraux."""
    settings, repo = _context(project_id)
    _require_project(repo)
    path = repo.dir / "literature-review.md"
    text = path.read_text(encoding="utf-8") if path.exists() else None
    result = check_literature_review(text, repo.load_papers(), repo.load_evidence())
    try:
        coverages = repo.reading_coverage()
    except FulltextTampered as exc:
        _fail(str(exc))
    if settings.policy.require_full_reading:
        result.errors.extend(check_reading(coverages.values(), project_id))
    if as_json:
        _print_json({"errors": result.errors, "warnings": result.warnings,
                     "fully_read": sorted(pid for pid, c in coverages.items() if c.complete),
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
    """Soumet le dossier à la gate de l'état courant (Gate 1 depuis GAP_ANALYSIS, Gate 2 depuis PROPOSAL_DRAFT)."""
    settings, repo = _context(project_id)
    _require_project(repo)
    state = repo.load_project().state
    try:
        if state == ResearchState.PROPOSAL_DRAFT:
            submission = submit_gate_2(repo, actor=getpass.getuser())
        else:
            submission = submit_gate_1(repo, settings, actor=getpass.getuser())
    except GateError as exc:
        _fail(f"Soumission refusée : {exc}")
    check = "proposal check" if submission.gate == Gate.GATE_2 else "gap check"
    typer.echo(f"{project_id} : soumis à la {_label(submission.gate)} (tour {submission.round}, {check} {submission.check_status})")
    typer.echo(f"Décision humaine : `research-lab gate status {project_id}`, puis `gate approve` ou `gate revise`")


def _label(gate: Gate) -> str:
    return "Gate 1" if gate == Gate.GATE_1 else "Gate 2"


def _gate_1_dossier(repo: ProjectRepository, submission: GateSubmission) -> None:
    typer.echo("Gaps soumis (par priorité) :")
    ranking = [r for r in repo.alignment_export() if r["gap_id"] in submission.gap_versions]
    for r in ranking:
        priority = "non évalué" if r["priority_score"] is None else f"priorité {r['priority_score']:.2f}"
        typer.echo(f"  {r['rank']:>2}. {r['gap_id']}  {r['status']:<9}  {r['evidence_strength']:<6}  {priority}  {r['title'][:70]}")
    typer.echo("Détail : gaps.json, alignment.json, literature-review.md ; `gap show <projet> GAP-xxx`")


def _gate_2_dossier(repo: ProjectRepository) -> None:
    for row in repo.solutions_export():
        if row["question_status"] != "active":
            continue
        recommendation = (row["comparison"] or {}).get("recommendation") or "aucune recommandation"
        typer.echo(f"{row['question_id']}  {row['question'][:80]}")
        for s in row["solutions"]:
            if s["status"] == "proposed":
                typer.echo(f"    {s['solution_id']}  {s['title'][:70]}{'  (recommandée)' if s['solution_id'] == recommendation else ''}")
    reviews = repo.critique_export()
    if reviews:
        last = reviews[-1]
        typer.echo(f"Revue critique : {len(reviews)} tour(s), dernier verdict {last['verdict']}")
        for o in last["objections"]:
            answer = o["response"]["action"] if o["response"] else "sans réponse"
            typer.echo(f"    {o['objection_id']}  {o['severity']:<8}  {o['statement'][:60]}  → {answer}")
    typer.echo("À lire : research-proposal.md (et references.bib) ; détail : solutions.json, scientific-review.json")


@gate_app.command("status")
def gate_status(project_id: ProjectId, as_json: JsonFlag = False) -> None:
    """Dossier soumis à la dernière gate : contenu, contrôles, intégrité des livrables, décisions passées."""
    _, repo = _context(project_id)
    _require_project(repo)
    state = repo.load_project().state
    gate = current_gate(repo)
    submission = latest_submission(repo, gate) if gate else None
    if as_json:
        _print_json({
            "state": state, "gate": gate, "rounds": repo.gate_export(gate) if gate else [],
            "ranking": [r for r in repo.alignment_export() if submission and r["gap_id"] in submission.gap_versions],
            "modified_artifacts": modified_artifacts(repo, submission) if submission else [],
        })
        return
    typer.echo(f"État : {state}")
    if submission is None:
        typer.echo("Aucune soumission à une gate")
        return
    typer.echo(f"{_label(submission.gate)}, tour {submission.round}, soumis le {submission.submitted_at:%Y-%m-%d %H:%M}Z par {submission.actor}")
    typer.echo(f"{'proposal' if submission.gate == Gate.GATE_2 else 'gap'} check à la soumission : {submission.check_status}")
    for w in submission.check_warnings:
        typer.echo(f"  avertissement : {w}")
    if submission.gate == Gate.GATE_1:
        _gate_1_dossier(repo, submission)
    else:
        _gate_2_dossier(repo)
    modified = modified_artifacts(repo, submission)
    typer.echo(f"Livrables : {'modifiés depuis la soumission : ' + ', '.join(modified) if modified else 'inchangés'}")
    for item in repo.gate_export(submission.gate):
        if (d := item["decision"]) is not None:
            gaps = f" — {', '.join(d['selected_gaps'])}" if d["selected_gaps"] else ""
            typer.echo(f"Tour {item['round']} : {d['decision']} par {d['approver']}{gaps} — « {d['comment']} »")


@gate_app.command("verify")
def gate_verify(project_id: ProjectId) -> None:
    """Vérifie que les livrables soumis à la dernière gate n'ont pas changé depuis (code 2 sinon)."""
    _, repo = _context(project_id)
    _require_project(repo)
    gate = current_gate(repo)
    if gate is None:
        _fail("Aucune soumission à une gate")
    submission = latest_submission(repo, gate)
    if modified := modified_artifacts(repo, submission):
        typer.echo(f"{_label(gate)} : modifiés depuis la soumission du tour {submission.round} : {', '.join(modified)}")
        raise typer.Exit(2)
    typer.echo(f"{_label(gate)} : livrables identiques à la soumission du tour {submission.round}")


def _human_decision(project_id: str, decision: GateDecisionType, comment: str, gaps: list[str]) -> None:
    _, repo = _context(project_id)
    _require_project(repo)
    if reason := human_check_failure():
        _fail(f"Décision refusée : {reason}")
    state = repo.load_project().state
    gate = Gate.GATE_2 if state == ResearchState.AWAITING_GATE_2 else Gate.GATE_1
    if gate == Gate.GATE_2 and gaps:
        _fail("La Gate 2 porte sur le Research Proposal : pas d'option --gap")
    if gate == Gate.GATE_1 and decision == GateDecisionType.APPROVE:
        current = {g.gap_id: g for g in repo.load_gaps()}
        for gap_id in gaps:
            if gap := current.get(gap_id):
                flag = "  (candidate : insuffisamment établi)" if gap.status == "candidate" else ""
                typer.echo(f"  retenu : {gap_id} v{gap.version} — {gap.title}{flag}")
    target = DECISION_TARGETS[gate][decision]
    typer.echo(f"{_label(gate)} — décision : {decision} → {target}\nCommentaire : {comment}")
    if typer.prompt(f"Pour confirmer, tapez l'identifiant du projet ({project_id})") != project_id:
        _fail("Confirmation incorrecte : rien n'a été enregistré")
    try:
        if gate == Gate.GATE_2:
            record = decide_gate_2(repo, decision, comment, approver=getpass.getuser())
        else:
            record = decide_gate_1(repo, decision, comment, approver=getpass.getuser(), selected_gaps=gaps)
    except GateError as exc:
        _fail(f"Décision refusée : {exc}")
    typer.echo(f"{_label(gate)}, tour {record.round} : {record.decision} enregistré par {record.approver} (gate-{gate[-1]}.json)")


@gate_app.command("approve")
def gate_approve(
    project_id: ProjectId,
    comment: Annotated[str, typer.Option(help="Justification de la décision")],
    gap: Annotated[list[str] | None, typer.Option("--gap", help="Gate 1 : gap retenu (répéter l'option)")] = None,
) -> None:
    """[HUMAIN] Gate 1 : retient des gaps (--gap) pour la formulation du problème. Gate 2 : accepte le Proposal."""
    _human_decision(project_id, GateDecisionType.APPROVE, comment, gap or [])


@gate_app.command("revise")
def gate_revise(
    project_id: ProjectId,
    comment: Annotated[str, typer.Option(help="Ce qu'il faut chercher ou corriger (lu par l'agent)")],
) -> None:
    """[HUMAIN] Demande une révision : Gate 1 → recherche bibliographique, Gate 2 → conception des solutions."""
    _human_decision(project_id, GateDecisionType.REVISE, comment, [])


# --- question ------------------------------------------------------------------


@question_app.command("add")
def question_add(
    project_id: ProjectId,
    file: DraftFile,
    reason: Annotated[str, typer.Option(help="Origine de la question (facultatif)")] = "",
    as_json: JsonFlag = False,
) -> None:
    """Enregistre une question de recherche (RQ-xxx) et ses hypothèses à partir d'un brouillon JSON."""
    _, repo = _context(project_id)
    _require_project(repo)
    draft = _read_draft(QuestionDraft, file)
    try:
        question = add_question(repo, draft, reason, actor=getpass.getuser())
    except QuestionError as exc:
        _fail(f"Question refusée : {exc}")
    if as_json:
        _print_json(question.model_dump(mode="json"))
    else:
        typer.echo(f"{question.question_id} enregistrée ({len(question.hypotheses)} hypothèses, {', '.join(question.gap_ids)})")


@question_app.command("revise")
def question_revise(
    project_id: ProjectId,
    question_id: Annotated[str, typer.Argument()],
    file: DraftFile,
    reason: Annotated[str, typer.Option(help="Raison de la révision")] = "",
    as_json: JsonFlag = False,
) -> None:
    """Remplace le contenu d'une question par une nouvelle version (l'historique est conservé)."""
    _, repo = _context(project_id)
    _require_project(repo)
    draft = _read_draft(QuestionDraft, file)
    try:
        question = revise_question(repo, question_id, draft, reason, actor=getpass.getuser())
    except QuestionError as exc:
        _fail(f"Révision refusée : {exc}")
    if as_json:
        _print_json(question.model_dump(mode="json"))
    else:
        typer.echo(f"{question.question_id} version {question.version} ({question.status})")


@question_app.command("list")
def question_list(project_id: ProjectId, as_json: JsonFlag = False) -> None:
    """Liste les questions de recherche du projet (version courante)."""
    _, repo = _context(project_id)
    _require_project(repo)
    questions = repo.questions_export()
    if as_json:
        _print_json(questions)
        return
    for q in questions:
        typer.echo(
            f"{q['question_id']}  v{q['version']}  {q['status']:<9}  {','.join(q['gap_ids']):<16}  "
            f"{len(q['hypotheses'])} hyp.  {q['question'][:70]}"
        )
    typer.echo(f"{len(questions)} questions ; gaps retenus à la Gate 1 : {', '.join(repo.approved_gaps()) or 'aucun'}")


@question_app.command("show")
def question_show(
    project_id: ProjectId,
    question_id: Annotated[str, typer.Argument()],
    history: Annotated[bool, typer.Option(help="Toutes les versions")] = False,
) -> None:
    """Affiche une question (JSON). Les champs du brouillon peuvent être repris pour `question revise`."""
    _, repo = _context(project_id)
    _require_project(repo)
    if history:
        versions = repo.question_history(question_id)
        if not versions:
            _fail(f"{question_id} n'existe pas dans le projet {project_id}")
        _print_json([v.model_dump(mode="json") for v in versions])
        return
    question = next((q for q in repo.questions_export() if q["question_id"] == question_id), None)
    if question is None:
        _fail(f"{question_id} n'existe pas dans le projet {project_id}")
    _print_json(question)


@question_app.command("check")
def question_check(project_id: ProjectId, as_json: JsonFlag = False) -> None:
    """Contrôle les questions et hypothèses avant la conception des solutions : OK ou BLOCKED."""
    _, repo = _context(project_id)
    _require_project(repo)
    result = check_questions(repo)
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


# --- solution ------------------------------------------------------------------


@solution_app.command("add")
def solution_add(
    project_id: ProjectId,
    file: DraftFile,
    reason: Annotated[str, typer.Option(help="Origine de la solution (facultatif)")] = "",
    as_json: JsonFlag = False,
) -> None:
    """Enregistre une solution (SOL-xxx) pour une question de recherche, à partir d'un brouillon JSON."""
    _, repo = _context(project_id)
    _require_project(repo)
    draft = _read_draft(SolutionDraft, file)
    try:
        solution = add_solution(repo, draft, reason, actor=getpass.getuser())
    except SolutionError as exc:
        _fail(f"Solution refusée : {exc}")
    if as_json:
        _print_json(solution.model_dump(mode="json"))
    else:
        typer.echo(f"{solution.solution_id} enregistrée pour {solution.question_id} ({', '.join(solution.addressed_hypotheses)})")


@solution_app.command("revise")
def solution_revise(
    project_id: ProjectId,
    solution_id: Annotated[str, typer.Argument()],
    file: DraftFile,
    reason: Annotated[str, typer.Option(help="Raison de la révision")] = "",
    as_json: JsonFlag = False,
) -> None:
    """Remplace le contenu d'une solution par une nouvelle version (la comparaison devient périmée)."""
    _, repo = _context(project_id)
    _require_project(repo)
    draft = _read_draft(SolutionDraft, file)
    try:
        solution = revise_solution(repo, solution_id, draft, reason, actor=getpass.getuser())
    except SolutionError as exc:
        _fail(f"Révision refusée : {exc}")
    if as_json:
        _print_json(solution.model_dump(mode="json"))
    else:
        typer.echo(f"{solution.solution_id} version {solution.version} ({solution.status})")


@solution_app.command("compare")
def solution_compare(project_id: ProjectId, file: DraftFile, as_json: JsonFlag = False) -> None:
    """Enregistre la comparaison des solutions actives d'une question, critère par critère."""
    _, repo = _context(project_id)
    _require_project(repo)
    draft = _read_draft(ComparisonDraft, file)
    try:
        comparison = set_comparison(repo, draft, actor=getpass.getuser())
    except SolutionError as exc:
        _fail(f"Comparaison refusée : {exc}")
    if as_json:
        _print_json(comparison.model_dump(mode="json"))
    else:
        recommendation = comparison.recommendation or "aucune recommandation"
        typer.echo(
            f"{comparison.question_id} : comparaison v{comparison.version} de {len(comparison.assessments)} solutions "
            f"sur {len(comparison.criteria)} critères ({recommendation})"
        )


@solution_app.command("list")
def solution_list(project_id: ProjectId, as_json: JsonFlag = False) -> None:
    """Liste les solutions par question, avec l'état de leur comparaison."""
    _, repo = _context(project_id)
    _require_project(repo)
    rows = repo.solutions_export()
    if as_json:
        _print_json(rows)
        return
    for row in rows:
        if row["comparison"] is None:
            compared = "non comparées"
        else:
            compared = "comparaison périmée" if row["comparison_stale"] else f"comparées (v{row['comparison']['version']})"
        typer.echo(f"{row['question_id']}  {compared}  {row['question'][:70]}")
        for s in row["solutions"]:
            mark = "  *" if row["comparison"] and row["comparison"]["recommendation"] == s["solution_id"] else ""
            typer.echo(f"  {s['solution_id']}  v{s['version']}  {s['status']:<9}  {','.join(s['addressed_hypotheses']):<8}  {s['title'][:60]}{mark}")


@solution_app.command("show")
def solution_show(
    project_id: ProjectId,
    solution_id: Annotated[str, typer.Argument()],
    history: Annotated[bool, typer.Option(help="Toutes les versions")] = False,
) -> None:
    """Affiche une solution (JSON). Les champs du brouillon peuvent être repris pour `solution revise`."""
    _, repo = _context(project_id)
    _require_project(repo)
    if history:
        versions = repo.solution_history(solution_id)
        if not versions:
            _fail(f"{solution_id} n'existe pas dans le projet {project_id}")
        _print_json([v.model_dump(mode="json") for v in versions])
        return
    solution = next(
        (s for row in repo.solutions_export() for s in row["solutions"] if s["solution_id"] == solution_id), None
    )
    if solution is None:
        _fail(f"{solution_id} n'existe pas dans le projet {project_id}")
    _print_json(solution)


@solution_app.command("check")
def solution_check(project_id: ProjectId, as_json: JsonFlag = False) -> None:
    """Contrôle les solutions et leurs comparaisons avant la revue critique : OK ou BLOCKED."""
    settings, repo = _context(project_id)
    _require_project(repo)
    result = check_solutions(repo, settings)
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


# --- critique ------------------------------------------------------------------


@critique_app.command("submit")
def critique_submit(
    project_id: ProjectId,
    file: DraftFile,
    reviewer: Annotated[str, typer.Option(help="Auteur de la revue")] = "scientific-reviewer",
    as_json: JsonFlag = False,
) -> None:
    """[REVIEWER] Enregistre la revue du tour en cours (immuable) ; les preuves relues sont revérifiées."""
    settings, repo = _context(project_id)
    _require_project(repo)
    draft = _read_draft(ReviewDraft, file)
    try:
        review = submit_review(repo, settings, draft, reviewer=reviewer)
    except CritiqueError as exc:
        _fail(f"Revue refusée : {exc}")
    if as_json:
        _print_json(review.model_dump(mode="json"))
        return
    counts = {s: sum(o.severity == s for o in review.objections) for s in ("critical", "major", "minor")}
    typer.echo(
        f"Revue du tour {review.round} : {review.verdict} ({counts['critical']} critiques, {counts['major']} majeures, "
        f"{counts['minor']} mineures ; {len(review.verifications)} preuves relues)"
    )


@critique_app.command("respond")
def critique_respond(
    project_id: ProjectId,
    objection_id: Annotated[str, typer.Argument()],
    action: Annotated[ResponseAction, typer.Option(help="revised, rebutted ou accepted_limitation")],
    response: Annotated[str, typer.Option(help="Réponse argumentée (ce qui a changé, ou pourquoi l'objection est contestée)")],
) -> None:
    """Répond à une objection de la revue ; une nouvelle réponse remplace la précédente."""
    _, repo = _context(project_id)
    _require_project(repo)
    try:
        draft = ResponseDraft(action=action, response=response)
        recorded = respond(repo, objection_id, draft, actor=getpass.getuser())
    except ValidationError as exc:
        _fail(f"Réponse invalide :\n{exc}")
    except CritiqueError as exc:
        _fail(f"Réponse refusée : {exc}")
    typer.echo(f"{recorded.objection_id} : {recorded.action}")


@critique_app.command("show")
def critique_show(project_id: ProjectId, as_json: JsonFlag = False) -> None:
    """Revues du projet, objections et réponses."""
    _, repo = _context(project_id)
    _require_project(repo)
    rounds = repo.critique_export()
    if as_json:
        _print_json(rounds)
        return
    if not rounds:
        typer.echo("Aucune revue")
    for review in rounds:
        typer.echo(f"Tour {review['round']} : {review['verdict']} par {review['reviewer']} — {review['summary'][:100]}")
        for o in review["objections"]:
            answer = f"→ {o['response']['action']}" if o["response"] else "→ sans réponse"
            typer.echo(f"  {o['objection_id']}  {o['severity']:<8}  {','.join(o['targets']):<20}  {o['statement'][:60]}  {answer}")
        results = [f"{v['evidence_id']} {v['result']}" for v in review["verifications"]]
        typer.echo(f"  preuves relues : {', '.join(results)}")


@critique_app.command("check")
def critique_check(project_id: ProjectId, as_json: JsonFlag = False) -> None:
    """Où en est la revue : verdict du tour, objections sans réponse, étape suivante (code 2 si bloqué)."""
    _, repo = _context(project_id)
    _require_project(repo)
    result = check_critique(repo)
    if as_json:
        _print_json({"status": result.status, "round": result.round, "verdict": result.verdict,
                     "next_state": result.next_state, "errors": result.errors})
    else:
        typer.echo(f"Statut : {result.status} (tour {result.round}, dernier verdict : {result.verdict or 'aucun'})")
        if result.next_state:
            typer.echo(f"Étape suivante : {result.next_state}")
        for e in result.errors:
            typer.echo(f"  erreur : {e}")
    if result.status == "BLOCKED":
        raise typer.Exit(2)


# --- proposal ------------------------------------------------------------------


@proposal_app.command("references")
def proposal_references(project_id: ProjectId) -> None:
    """Génère references.bib depuis la base, pour les publications citées par research-proposal.md."""
    _, repo = _context(project_id)
    _require_project(repo)
    try:
        count = write_references(repo)
    except ProposalError as exc:
        _fail(f"Bibliographie refusée : {exc}")
    typer.echo(f"references.bib : {count} entrées")


@proposal_app.command("check")
def proposal_check(project_id: ProjectId, as_json: JsonFlag = False) -> None:
    """Contrôle research-proposal.md : sections, citations, éléments traités, bibliographie (OK ou BLOCKED)."""
    _, repo = _context(project_id)
    _require_project(repo)
    result = check_proposal_file(repo)
    if as_json:
        _print_json({"status": result.status, "errors": result.errors, "warnings": result.warnings,
                     "cited_papers": result.cited_papers})
    else:
        typer.echo(f"Statut : {result.status} ({len(result.cited_papers)} publications citées)")
        for e in result.errors:
            typer.echo(f"  erreur : {e}")
        for w in result.warnings:
            typer.echo(f"  avertissement : {w}")
    if result.status == "BLOCKED":
        raise typer.Exit(2)


# --- eval --------------------------------------------------------------------


@eval_app.command("report")
def eval_report(project_id: ProjectId, as_json: JsonFlag = False) -> None:
    """Indicateurs calculés par le code (Q1 à Q5, revue, workflow). Ils ne jugent pas la valeur scientifique."""
    settings, repo = _context(project_id)
    _require_project(repo)
    report = quality_report(repo, settings)
    ratings = current_ratings(repo.load_rating_sessions())
    if as_json:
        _print_json({**report.as_dict(), "human_ratings": {t: r.model_dump(mode="json") for t, r in ratings.items()}})
        return
    typer.echo(f"Projet : {report.project_id} ({report.state})")
    for i in report.indicators:
        mark = {True: "ok ", False: "KO ", None: "   "}[i.ok]
        typer.echo(f"  {mark} {i.control:<8} {i.name} : {i.value}")
    targets = rating_targets(repo)
    typer.echo(f"Évaluation humaine : {sum(t.target in ratings for t in targets)}/{len(targets)} gaps et hypothèses notés"
               + ("" if ratings else f" (`research-lab eval rate {project_id}`, dans ton terminal)"))


@eval_app.command("rate")
def eval_rate(project_id: ProjectId) -> None:
    """Notation humaine des gaps et des hypothèses, critère par critère (terminal interactif, jamais par un agent)."""
    settings, repo = _context(project_id)
    _require_project(repo)
    if reason := human_check_failure():
        _fail(f"Évaluation refusée : {reason}")
    config = settings.policy.evaluation
    targets = rating_targets(repo)
    if not targets:
        _fail("Rien à évaluer : ni gap, ni hypothèse")
    previous = current_ratings(repo.load_rating_sessions())
    typer.echo(f"Échelle : {config.scale[0]} (très insuffisant) à {config.scale[-1]} (excellent) ; Entrée vide : passer")
    ratings: list[Rating] = []
    for target in targets:
        criteria = config.gap_criteria if target.kind == "gap" else config.hypothesis_criteria
        typer.echo(f"\n{target.target} (v{target.version}) — {target.title}\n{target.detail}")
        if old := previous.get(target.target):
            typer.echo(f"  note précédente : {old.scores}")
        scores: dict[str, int] = {}
        for criterion, question in criteria.items():
            answer = typer.prompt(f"  {criterion} — {question}", default="", show_default=False).strip()
            if not answer:
                break
            while not answer.isdigit() or int(answer) not in config.scale:
                answer = typer.prompt(f"  {criterion} : note parmi {config.scale}").strip()
            scores[criterion] = int(answer)
        if len(scores) == len(criteria):
            comment = typer.prompt("  commentaire", default="", show_default=False)
            ratings.append(Rating(target=target.target, target_version=target.version, scores=scores, comment=comment))
    if not ratings:
        _fail("Aucune note complète : rien n'a été enregistré")
    comment = typer.prompt("\nCommentaire général", default="", show_default=False)
    try:
        session = record_ratings(repo, settings, ratings, rater=getpass.getuser(), comment=comment)
    except EvaluationError as exc:
        _fail(f"Évaluation refusée : {exc}")
    typer.echo(f"{session.session_id} : {len(ratings)} notes enregistrées par {session.rater} (human-evaluation.json)")


@eval_app.command("summary")
def eval_summary(as_json: JsonFlag = False) -> None:
    """Synthèse de l'évaluation humaine, tous projets : sujets évalués (cible du MVP) et moyennes par critère."""
    settings, db = _settings_and_db()
    summary = evaluation_summary(db, settings)
    if as_json:
        _print_json({**dataclasses.asdict(summary), "target_met": summary.target_met})
        return
    status = "atteinte" if summary.target_met else "non atteinte"
    typer.echo(f"Sujets évalués par un humain : {len(summary.rated_projects)} (cible {summary.min_rated_topics}, {status})")
    for pid, topic in summary.rated_projects.items():
        typer.echo(f"  {pid} — {topic}")
    for criterion, average in summary.averages.items():
        typer.echo(f"  {criterion:<16} {average}")


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
