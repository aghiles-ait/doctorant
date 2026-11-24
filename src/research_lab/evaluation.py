"""Évaluation de la qualité scientifique d'un projet (sprint 4, spec §8 et §11).

Deux volets, séparés à dessein :
- des indicateurs calculés par le code sur les contrôles Q1 à Q5 et la revue : ils mesurent ce qui est
  vérifiable (identifiants, preuves, recherches, lecture), pas la valeur scientifique ;
- des notes données par un humain aux gaps et aux hypothèses, seul jugement sur leur qualité. La nouveauté
  n'est jamais réduite à un score (spec §11).
"""

import re
from dataclasses import asdict, dataclass, field

from research_lab.config import Settings
from research_lab.schemas.evaluation import Rating, RatingSession
from research_lab.schemas.paper import PaperStatus
from research_lab.storage.database import Database
from research_lab.storage.repositories import (
    ProjectRepository,
    load_all_rating_sessions,
    next_rating_session_id,
    now,
)
from research_lab.validation.critique import unanswered_objections
from research_lab.validation.gaps import useful_searches
from research_lab.validation.outputs import check_literature_review
from research_lab.workflow import approvals


# Titre de section « Limites » (« ## 4. Limites de cet état de l'art », « ## Limites »).
_LIMITS_HEADING = re.compile(r"^##\s+(?:[0-9.]+\s+)?limit", re.IGNORECASE | re.MULTILINE)


class EvaluationError(Exception):
    """Évaluation humaine refusée."""


@dataclass
class Indicator:
    control: str  # Q1 à Q5, revue, workflow
    name: str
    value: str
    ok: bool | None = None  # None : informatif, sans cible


@dataclass
class QualityReport:
    project_id: str
    state: str
    indicators: list[Indicator] = field(default_factory=list)

    @property
    def failed(self) -> list[Indicator]:
        return [i for i in self.indicators if i.ok is False]

    def as_dict(self) -> dict:
        return {**asdict(self), "failed": [i.name for i in self.failed]}


def _ratio(part: int, whole: int) -> str:
    return f"{part}/{whole}" + (f" ({100 * part / whole:.0f} %)" if whole else "")


def quality_report(repo: ProjectRepository, settings: Settings) -> QualityReport:
    project = repo.load_project()
    report = QualityReport(project_id=project.project_id, state=project.state)
    add = lambda *args: report.indicators.append(Indicator(*args))  # noqa: E731

    papers = repo.load_papers()
    included = [p for p in papers if p.status == PaperStatus.INCLUDED]
    evidence = [e for e in repo.load_evidence() if e.withdrawn_at is None]
    gaps = [g for g in repo.load_gaps() if g.active]
    approved = repo.approved_gaps()
    searches = repo.searches_by_gap()

    # Q1 — validité bibliographique
    add("Q1", "publications incluses avec identifiant externe", _ratio(sum(p.has_identifier() for p in included), len(included)),
        all(p.has_identifier() for p in included))
    add("Q1", "publications incluses avec provenance", _ratio(sum(bool(p.provenance) for p in included), len(included)),
        all(p.provenance for p in included))
    review_path = repo.dir / "literature-review.md"
    if review_path.exists():
        citations = check_literature_review(review_path.read_text(encoding="utf-8"), papers, evidence)
        add("Q1", "citations invalides dans literature-review.md", str(len(citations.errors)), not citations.errors)

    # Q2 — traçabilité
    with_evidence = {e.paper_id for e in evidence}
    add("Q2", "publications incluses appuyées par au moins une preuve",
        _ratio(sum(p.paper_id in with_evidence for p in included), len(included)))
    add("Q2", "preuves localisées dans le texte intégral (page)",
        _ratio(sum(e.page is not None for e in evidence), len(evidence)))
    coverages = repo.reading_coverage()
    add("Q2", "textes intégraux lus en entier (texte principal)",
        _ratio(sum(c.complete for c in coverages.values()), len(coverages)),
        all(c.complete for c in coverages.values()) if settings.policy.require_full_reading else None)

    # Q3 — recherche contradictoire, sur les gaps retenus s'il y en a, sinon sur les gaps actifs
    scope = [g for g in gaps if g.gap_id in approved] if approved else gaps
    searched = [g for g in scope if useful_searches(searches.get(g.gap_id, []))]
    add("Q3", "gaps avec une recherche contradictoire ayant ramené des résultats", _ratio(len(searched), len(scope)),
        len(searched) == len(scope) if scope else None)
    empty = sum(1 for runs in searches.values() for s in runs if s not in useful_searches([s]))
    add("Q3", "recherches contradictoires vides ou en échec", str(empty))
    add("Q3", "gaps citant des preuves contraires",
        _ratio(sum(bool(g.contradicting_evidence) for g in scope), len(scope)))

    # Q4 — falsifiabilité (critère de réfutation contrôlé à l'enregistrement) et mise à l'épreuve
    questions = [q for q in repo.load_questions() if q.active]
    solutions = [s for s in repo.load_solutions() if s.active]
    hypotheses = [(q.question_id, h.hypothesis_id) for q in questions for h in q.hypotheses]
    tested = {(s.question_id, h) for s in solutions for h in s.addressed_hypotheses}
    if hypotheses:
        add("Q4", "hypothèses avec critère de réfutation", _ratio(len(hypotheses), len(hypotheses)), True)
        add("Q4", "hypothèses testées par au moins une solution",
            _ratio(sum(h in tested for h in hypotheses), len(hypotheses)), all(h in tested for h in hypotheses))

    # Q5 — transparence des limites
    log = repo.load_search_log()
    add("Q5", "recherches journalisées (requête, sources, dates, configuration)", str(len(log)), bool(log) or None)
    for name in ("literature-review.md", "research-proposal.md"):
        path = repo.dir / name
        if path.exists():
            text = path.read_text(encoding="utf-8")
            has_limits = bool(_LIMITS_HEADING.search(text))
            add("Q5", f"section Limites dans {name}", "présente" if has_limits else "absente", has_limits)
            cited = sum(s.search_id in text for s in log)
            add("Q5", f"recherches citées dans {name}", _ratio(cited, len(log)))

    # Revue critique
    reviews = repo.load_reviews()
    if reviews:
        last = reviews[-1]
        responses = repo.load_responses()
        add("revue", "tours de revue", str(len(reviews)))
        add("revue", "dernier verdict", last.verdict, last.verdict == "ACCEPTABLE")
        severities = [o.severity for r in reviews for o in r.objections]
        add("revue", "objections (critiques / majeures / mineures)",
            " / ".join(str(severities.count(s)) for s in ("critical", "major", "minor")))
        add("revue", "objections critiques ou majeures sans réponse (dernière revue)",
            str(len(unanswered_objections(last, responses))))
        actions = [r.action for r in responses.values()]
        add("revue", "réponses (révisé / réfuté / limite admise)",
            " / ".join(str(actions.count(a)) for a in ("revised", "rebutted", "accepted_limitation")))

    # Workflow : un raccourci pris pendant le développement doit rester visible.
    forced = [c for c in project.history if c.forced]
    add("workflow", "transitions forcées", str(len(forced)), not forced)
    return report


# --- Évaluation humaine ----------------------------------------------------------------


@dataclass
class RatingTarget:
    target: str
    version: int
    kind: str  # gap ou hypothesis
    title: str
    detail: str


def rating_targets(repo: ProjectRepository) -> list[RatingTarget]:
    """Gaps retenus à la Gate 1 (ou actifs, avant la Gate 1) et hypothèses des questions actives."""
    approved = repo.approved_gaps()
    targets = [
        RatingTarget(g.gap_id, g.version, "gap", g.title, g.description)
        for g in repo.load_gaps() if (g.gap_id in approved if approved else g.active)
    ]
    for q in repo.load_questions():
        if q.active:
            targets += [
                RatingTarget(f"{q.question_id}/{h.hypothesis_id}", q.version, "hypothesis", h.statement,
                             f"Prédiction : {h.prediction}\nRéfutation : {h.refutation_criterion}")
                for h in q.hypotheses
            ]
    return targets


def record_ratings(
    repo: ProjectRepository, settings: Settings, ratings: list[Rating], rater: str, comment: str = ""
) -> RatingSession:
    """Enregistre les notes d'un humain. Comme une décision de gate, jamais par un agent."""
    if reason := approvals.human_check_failure():
        raise EvaluationError(reason)
    if not ratings:
        raise EvaluationError("Aucune note")
    config = settings.policy.evaluation
    targets = {t.target: t for t in rating_targets(repo)}
    for rating in ratings:
        target = targets.get(rating.target)
        if target is None:
            raise EvaluationError(f"{rating.target} : ni gap retenu ou actif, ni hypothèse d'une question active")
        if rating.target_version != target.version:
            raise EvaluationError(f"{rating.target} : version {rating.target_version} notée, version courante {target.version}")
        criteria = config.gap_criteria if target.kind == "gap" else config.hypothesis_criteria
        if set(rating.scores) != set(criteria):
            raise EvaluationError(f"{rating.target} : critères attendus {', '.join(criteria)}")
        if bad := [c for c, s in rating.scores.items() if s not in config.scale]:
            raise EvaluationError(f"{rating.target} : notes hors de l'échelle {config.scale} pour {', '.join(bad)}")
    session = RatingSession(
        session_id=next_rating_session_id(repo.db), project_id=repo.project_id, rater=rater, at=now(),
        state=repo.load_project().state, ratings=ratings, comment=comment.strip(),
    )
    repo.record_rating_session(session)
    return session


def current_ratings(sessions: list[RatingSession]) -> dict[str, Rating]:
    """Dernière note de chaque cible."""
    return {r.target: r for s in sessions for r in s.ratings}


@dataclass
class EvaluationSummary:
    rated_projects: dict[str, str]  # projet -> sujet
    min_rated_topics: int
    averages: dict[str, float]  # critère -> moyenne des dernières notes, tous projets
    rating_count: int

    @property
    def target_met(self) -> bool:
        return len(self.rated_projects) >= self.min_rated_topics


def evaluation_summary(db: Database, settings: Settings) -> EvaluationSummary:
    """Synthèse de l'évaluation humaine, tous projets confondus (critère du MVP : trois sujets distincts)."""
    by_project: dict[str, list[RatingSession]] = {}
    for session in load_all_rating_sessions(db):
        by_project.setdefault(session.project_id, []).append(session)
    topics = {
        r["project_id"]: r["topic"]
        for r in db.conn.execute("SELECT project_id, topic FROM projects")
    }
    scores: dict[str, list[int]] = {}
    count = 0
    for sessions in by_project.values():
        for rating in current_ratings(sessions).values():
            count += 1
            for criterion, score in rating.scores.items():
                scores.setdefault(criterion, []).append(score)
    return EvaluationSummary(
        rated_projects={pid: topics.get(pid, "") for pid in sorted(by_project)},
        min_rated_topics=settings.policy.evaluation.min_rated_topics,
        averages={c: round(sum(v) / len(v), 2) for c, v in sorted(scores.items())},
        rating_count=count,
    )
