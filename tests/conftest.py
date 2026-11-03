import shutil
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_text():
    return lambda name: (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def lab_root(tmp_path, monkeypatch) -> Path:
    """Dépôt temporaire avec la vraie configuration, sans attente entre requêtes ni relances lentes."""
    shutil.copytree(REPO_ROOT / "config", tmp_path / "config")
    sources_file = tmp_path / "config" / "academic-sources.yaml"
    sources = yaml.safe_load(sources_file.read_text())
    sources["retry"]["backoff_seconds"] = 0
    for provider in sources["providers"].values():
        provider["min_interval_seconds"] = 0
    sources_file.write_text(yaml.safe_dump(sources))
    monkeypatch.setenv("RESEARCH_LAB_ROOT", str(tmp_path))
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.delenv("OPENALEX_MAILTO", raising=False)
    return tmp_path
