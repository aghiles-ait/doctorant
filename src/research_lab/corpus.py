"""Intégration des résultats de recherche au corpus et contrôles d'intégrité."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from research_lab.schemas.paper import Paper, PaperMetadata, Provenance, SourceHit
from research_lab.schemas.search import SearchExecution
from research_lab.validation.references import find_duplicate, normalize_title

# Champs complétés lorsqu'une autre source apporte une valeur manquante.
_FILLABLE = ("authors", "abstract", "published", "venue", "work_type", "doi", "arxiv_id", "openalex_id", "url")


_IDENTIFIERS = ("doi", "arxiv_id", "openalex_id")


@dataclass
class MergeReport:
    new_paper_ids: list[str] = field(default_factory=list)
    matched_paper_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def touched_paper_ids(self) -> list[str]:
        return [*self.new_paper_ids, *self.matched_paper_ids]


def _next_id(papers: list[Paper]) -> str:
    highest = max((int(p.paper_id.split("-")[1]) for p in papers), default=0)
    return f"PAPER-{highest + 1:03d}"


def _fill_missing(paper: Paper, metadata: PaperMetadata, papers: list[Paper]) -> list[str]:
    """Complète sans jamais écraser une valeur déjà présente : la première source fait foi.

    Un identifiant déjà attribué à une autre publication n'est pas recopié : les deux
    entrées désignent probablement le même travail, ce qui est signalé sans fusion automatique.
    """
    warnings = []
    for name in _FILLABLE:
        value = getattr(metadata, name)
        if getattr(paper, name) or not value:
            continue
        if name in _IDENTIFIERS:
            owner = next((p for p in papers if p is not paper and getattr(p, name) == value), None)
            if owner is not None:
                warnings.append(
                    f"{paper.paper_id} et {owner.paper_id} semblent être la même publication "
                    f"({name}={value}) : à vérifier manuellement"
                )
                continue
        setattr(paper, name, value)
    return warnings


def merge_hits(
    papers: list[Paper],
    hits: list[SourceHit],
    search_id: str,
    query: str,
    retrieved_at: datetime,
) -> MergeReport:
    """Fusionne les résultats dans `papers` (modifiée en place).

    Un résultat qui correspond à une publication connue lui ajoute une provenance ;
    sinon il crée une publication avec un nouvel identifiant PAPER-xxx. Les identifiants
    existants ne changent jamais.
    """
    report = MergeReport()
    for hit in hits:
        provenance = Provenance(
            source=hit.source,
            source_id=hit.source_id,
            search_id=search_id,
            query=query,
            retrieved_at=retrieved_at,
        )
        existing = find_duplicate(hit.metadata, papers)
        if existing is None:
            paper = Paper(paper_id=_next_id(papers), provenance=[provenance], **hit.metadata.model_dump())
            papers.append(paper)
            report.new_paper_ids.append(paper.paper_id)
            continue
        report.warnings.extend(w for w in _fill_missing(existing, hit.metadata, papers) if w not in report.warnings)
        if not any(p.source == provenance.source and p.source_id == provenance.source_id and p.search_id == search_id
                   for p in existing.provenance):
            existing.provenance.append(provenance)
        if existing.paper_id not in report.new_paper_ids and existing.paper_id not in report.matched_paper_ids:
            report.matched_paper_ids.append(existing.paper_id)
    return report


class CorpusStatus(StrEnum):
    OK = "OK"
    NEEDS_MORE_RESEARCH = "NEEDS_MORE_RESEARCH"
    BLOCKED = "BLOCKED"


@dataclass
class CorpusCheck:
    status: CorpusStatus
    paper_count: int
    errors: list[str]
    warnings: list[str]


def check_corpus(papers: list[Paper], log: list[SearchExecution], min_corpus_size: int) -> CorpusCheck:
    """Vérifie l'intégrité du corpus : identifiants, provenance rattachée au journal, doublons."""
    errors: list[str] = []
    warnings: list[str] = []
    known_searches = {s.search_id for s in log}

    seen_ids: set[str] = set()
    for paper in papers:
        if paper.paper_id in seen_ids:
            errors.append(f"Identifiant interne en double : {paper.paper_id}")
        seen_ids.add(paper.paper_id)
        if not paper.has_identifier():
            errors.append(f"{paper.paper_id} : aucun identifiant externe")
        for prov in paper.provenance:
            if prov.search_id not in known_searches:
                errors.append(f"{paper.paper_id} : provenance {prov.search_id} absente de search-log.json")

    for field_name in ("doi", "arxiv_id", "openalex_id"):
        owners: dict[str, str] = {}
        for paper in papers:
            value = getattr(paper, field_name)
            if value and value in owners:
                errors.append(f"Doublon {field_name}={value} : {owners[value]} et {paper.paper_id}")
            elif value:
                owners[value] = paper.paper_id

    titles: dict[str, str] = {}
    for paper in papers:
        key = normalize_title(paper.title)
        if key in titles:
            warnings.append(f"Titres identiques, à vérifier manuellement : {titles[key]} et {paper.paper_id}")
        titles.setdefault(key, paper.paper_id)

    if errors:
        status = CorpusStatus.BLOCKED
    elif len(papers) < min_corpus_size:
        status = CorpusStatus.NEEDS_MORE_RESEARCH
        warnings.append(f"Corpus de {len(papers)} publications, minimum fixé par la politique : {min_corpus_size}")
    else:
        status = CorpusStatus.OK
    return CorpusCheck(status=status, paper_count=len(papers), errors=errors, warnings=warnings)
