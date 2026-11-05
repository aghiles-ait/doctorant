"""Récupération du texte intégral des publications en accès libre.

Sources essayées dans l'ordre : PDF arXiv, puis versions en accès libre recensées par OpenAlex.
Le texte est extrait page par page : une preuve peut ainsi être localisée à une page précise.
"""

import io
import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pypdf

from research_lab.config import ProviderConfig, Settings
from research_lab.providers.base import HttpClient, ProviderError
from research_lab.providers.openalex import auth_params
from research_lab.schemas.evidence import FulltextRecord, FulltextStatus
from research_lab.schemas.paper import Paper, Source
from research_lab.storage.repositories import now, sha256

EXTRACTOR = f"pypdf {pypdf.__version__}"


def pages_bytes(pages: list[str]) -> bytes:
    """Sérialisation canonique du texte extrait ; son empreinte est `text_sha256`."""
    return json.dumps(pages, ensure_ascii=False, indent=0).encode()


def extract_pages(pdf: bytes) -> list[str]:
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    return [page.extract_text() or "" for page in reader.pages]


@dataclass
class FetchOutcome:
    record: FulltextRecord
    pdf: bytes | None = None
    pages: list[str] | None = None


class FulltextFetcher:
    def __init__(self, settings: Settings, sleep: Callable[[float], None] = time.sleep) -> None:
        self._config = settings.sources.fulltext
        retry = settings.sources.retry
        download = ProviderConfig(
            base_url="",
            timeout_seconds=self._config.timeout_seconds,
            min_interval_seconds=self._config.min_interval_seconds,
        )
        self._download = HttpClient(download, retry, sleep=sleep)
        openalex = settings.sources.providers.get(Source.OPENALEX)
        self._openalex_url = openalex.base_url if openalex and openalex.enabled else None
        self._openalex = HttpClient(openalex, retry, sleep=sleep, params=auth_params()) if self._openalex_url else None

    def candidate_urls(self, paper: Paper, errors: list[str]) -> Iterator[str]:
        """URLs de PDF en accès libre, par ordre de préférence.

        OpenAlex n'est consulté que si le PDF arXiv manque ou échoue ; ses erreurs vont dans `errors`.
        """
        seen: set[str] = set()
        if paper.arxiv_id:
            url = f"{self._config.arxiv_pdf_url}/{paper.arxiv_id}"
            seen.add(url)
            yield url
        if paper.openalex_id and self._openalex:
            try:
                work = self._openalex.get(
                    f"{self._openalex_url}/works/{paper.openalex_id}", params={"select": "best_oa_location,locations"}
                ).json()
            except (ProviderError, ValueError) as exc:
                errors.append(f"OpenAlex : {exc}")
                return
            for location in [work.get("best_oa_location") or {}, *(work.get("locations") or [])]:
                url = location.get("pdf_url")
                if location.get("is_oa") and url and url not in seen:
                    seen.add(url)
                    yield url

    def fetch(self, paper: Paper) -> FetchOutcome:
        errors: list[str] = []
        tried = False
        max_bytes = int(self._config.max_pdf_mb * 1024 * 1024)
        for url in self.candidate_urls(paper, errors):
            tried = True
            try:
                response = self._download.get(url, params={})
            except ProviderError as exc:
                errors.append(str(exc))
                continue
            pdf = response.content
            if len(pdf) > max_bytes:
                errors.append(f"{url} : PDF de plus de {self._config.max_pdf_mb} Mo")
                continue
            if not pdf.startswith(b"%PDF-"):
                errors.append(f"{url} : la réponse n'est pas un PDF ({response.headers.get('content-type', '?')})")
                continue
            try:
                pages = extract_pages(pdf)
            except Exception as exc:  # PDF non fiable : toute erreur de lecture est un échec de cette source
                errors.append(f"{url} : extraction impossible ({type(exc).__name__}: {exc})")
                continue
            if sum(len(p.strip()) for p in pages) < self._config.min_extracted_chars:
                errors.append(f"{url} : texte non extractible (PDF scanné ?)")
                continue
            record = FulltextRecord(
                paper_id=paper.paper_id,
                status=FulltextStatus.AVAILABLE,
                pdf_url=url,
                pdf_sha256=sha256(pdf),
                text_sha256=sha256(pages_bytes(pages)),
                page_count=len(pages),
                extractor=EXTRACTOR,
                fetched_at=now(),
            )
            return FetchOutcome(record, pdf=pdf, pages=pages)

        if not tried and not errors:
            status, error = FulltextStatus.UNAVAILABLE, "aucune version en accès libre connue"
        else:
            status, error = FulltextStatus.FAILED, "; ".join(errors) or "aucune version en accès libre exploitable"
        return FetchOutcome(FulltextRecord(paper_id=paper.paper_id, status=status, fetched_at=now(), error=error))
