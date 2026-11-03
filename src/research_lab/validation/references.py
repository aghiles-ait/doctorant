"""Normalisation et validation des identifiants bibliographiques, détection des doublons.

Ces contrôles portent sur la forme des identifiants (Q1, spec §8). Ils ne prouvent
ni l'existence d'une référence ni qu'elle soutient une affirmation.
"""

import re
import unicodedata
from collections.abc import Iterable

from research_lab.schemas.paper import PaperMetadata

_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
_DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/", "doi:")
_ARXIV_DOI_RE = re.compile(r"^10\.48550/arxiv\.(.+)$", re.IGNORECASE)

_ARXIV_NEW_RE = re.compile(r"^\d{4}\.\d{4,5}$")
_ARXIV_OLD_RE = re.compile(r"^[a-z][a-z.-]*(\.[A-Z]{2})?/\d{7}$")
_ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([^?#\s]+?)(?:\.pdf)?/?$", re.IGNORECASE)
_ARXIV_VERSION_RE = re.compile(r"v\d+$")

_OPENALEX_RE = re.compile(r"^W\d+$")

# Écart toléré entre années pour rapprocher deux titres identiques (préprint puis publication).
TITLE_MATCH_MAX_YEAR_GAP = 1


def normalize_doi(value: str | None) -> str | None:
    """Renvoie le DOI en minuscules, sans préfixe d'URL, ou None s'il est invalide."""
    if not value:
        return None
    doi = value.strip()
    for prefix in _DOI_PREFIXES:
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix) :]
            break
    doi = doi.lower()
    return doi if _DOI_RE.match(doi) else None


def normalize_arxiv_id(value: str | None) -> str | None:
    """Renvoie l'identifiant arXiv sans version ni préfixe, ou None s'il est invalide."""
    if not value:
        return None
    raw = value.strip()
    if match := _ARXIV_URL_RE.search(raw):
        raw = match.group(1)
    if raw.lower().startswith("arxiv:"):
        raw = raw[len("arxiv:") :]
    raw = _ARXIV_VERSION_RE.sub("", raw)
    if _ARXIV_NEW_RE.match(raw) or _ARXIV_OLD_RE.match(raw):
        return raw
    return None


def arxiv_id_from_doi(doi: str | None) -> str | None:
    """Les préprints arXiv ont un DOI DataCite de la forme 10.48550/arXiv.<id>."""
    if doi and (match := _ARXIV_DOI_RE.match(doi)):
        return normalize_arxiv_id(match.group(1))
    return None


def normalize_openalex_id(value: str | None) -> str | None:
    if not value:
        return None
    work_id = value.strip().rsplit("/", 1)[-1].upper()
    return work_id if _OPENALEX_RE.match(work_id) else None


def normalize_title(title: str) -> str:
    """Forme canonique d'un titre pour la comparaison : sans accents, ponctuation ni casse."""
    text = unicodedata.normalize("NFKD", title)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", text.casefold())
    return " ".join(text.split())


def same_work(a: PaperMetadata, b: PaperMetadata) -> bool:
    """Deux métadonnées désignent-elles la même publication ?

    Un identifiant commun suffit. À défaut, on exige un titre identique (normalisé)
    et des années compatibles, pour éviter de fusionner deux travaux homonymes.
    """
    for field in ("doi", "arxiv_id", "openalex_id"):
        va, vb = getattr(a, field), getattr(b, field)
        if va and vb and va == vb:
            return True
    if normalize_title(a.title) != normalize_title(b.title):
        return False
    if a.published and b.published:
        return abs(a.published.year - b.published.year) <= TITLE_MATCH_MAX_YEAR_GAP
    return True


def find_duplicate[T: PaperMetadata](candidate: PaperMetadata, papers: Iterable[T]) -> T | None:
    """Cherche d'abord par identifiant, puis par titre, pour privilégier la correspondance la plus sûre."""
    papers = list(papers)
    for field in ("doi", "arxiv_id", "openalex_id"):
        value = getattr(candidate, field)
        if value:
            for paper in papers:
                if getattr(paper, field) == value:
                    return paper
    for paper in papers:
        if same_work(candidate, paper):
            return paper
    return None
