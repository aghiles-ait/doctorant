from datetime import date

import pytest

from research_lab.schemas.paper import PaperMetadata
from research_lab.validation.references import (
    arxiv_id_from_doi,
    find_duplicate,
    normalize_arxiv_id,
    normalize_doi,
    normalize_openalex_id,
    normalize_title,
    same_work,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://doi.org/10.1109/ICBC64466.2025.11185065", "10.1109/icbc64466.2025.11185065"),
        ("doi:10.1000/xyz123", "10.1000/xyz123"),
        ("10.48550/arXiv.2504.15676", "10.48550/arxiv.2504.15676"),
        ("not-a-doi", None),
        ("10.12/too-short-prefix", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_doi(raw, expected):
    assert normalize_doi(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://arxiv.org/abs/2504.15676v1", "2504.15676"),
        ("https://arxiv.org/pdf/2504.15676v2.pdf", "2504.15676"),
        ("arXiv:2401.01234", "2401.01234"),
        ("hep-th/9901001v3", "hep-th/9901001"),
        ("math.GT/0309136", "math.GT/0309136"),
        ("12345", None),
        (None, None),
    ],
)
def test_normalize_arxiv_id(raw, expected):
    assert normalize_arxiv_id(raw) == expected


def test_arxiv_id_from_datacite_doi():
    assert arxiv_id_from_doi("10.48550/arxiv.2504.15676") == "2504.15676"
    assert arxiv_id_from_doi("10.1109/icbc64466.2025.11185065") is None


def test_normalize_openalex_id():
    assert normalize_openalex_id("https://openalex.org/W4414632071") == "W4414632071"
    assert normalize_openalex_id("https://openalex.org/A5115834605") is None


def test_normalize_title_ignores_case_accents_and_punctuation():
    assert normalize_title("Gouvernance  Décentralisée : un État de l'Art!") == normalize_title(
        "gouvernance decentralisee un etat de l art"
    )


def _meta(**kwargs) -> PaperMetadata:
    return PaperMetadata(title=kwargs.pop("title", "A paper"), **kwargs)


def test_same_work_by_shared_identifier_despite_different_titles():
    assert same_work(_meta(title="Preprint title", arxiv_id="2504.15676"), _meta(title="Published title", arxiv_id="2504.15676"))


def test_same_title_far_apart_in_time_is_not_merged():
    a = _meta(title="Introduction", published=date(2015, 1, 1))
    b = _meta(title="Introduction", published=date(2024, 1, 1))
    assert not same_work(a, b)


def test_same_title_preprint_then_publication_is_merged():
    a = _meta(title="Trustworthy DAMs", published=date(2024, 12, 20))
    b = _meta(title="Trustworthy DAMs.", published=date(2025, 6, 2))
    assert same_work(a, b)


def test_find_duplicate_prefers_identifier_match_over_title_match():
    by_title = _meta(title="Shared title")
    by_doi = _meta(title="Other title", doi="10.1000/abc")
    candidate = _meta(title="Shared title", doi="10.1000/abc")
    assert find_duplicate(candidate, [by_title, by_doi]) is by_doi
