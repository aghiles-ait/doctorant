"""Sprint 4 : tests de non-régression.

- Migrations : une migration publiée ne change plus, et toute base, à n'importe quelle version du schéma, se
  met à jour jusqu'à la dernière.
- Exports de référence (`golden/`) : le scénario complet, du sujet à la Gate 2, produit exactement les mêmes
  livrables et sorties de contrôle, une fois retirés les horodatages, empreintes et nom d'utilisateur.
- Instantanés (`fixtures/snapshot-vN/`) : un laboratoire enregistré par une version antérieure reste lisible,
  ses exports régénérés sont identiques et ses validations humaines restent vérifiables.

Après un changement voulu : `UPDATE_GOLDEN=1 .venv/bin/pytest tests/regression`, puis relire le diff.
Nouvel instantané (après une migration) : `REGRESSION_SNAPSHOT=1 .venv/bin/pytest tests/regression`.
"""

import getpass
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "integration"))  # scénario complet de test_cli_flow.py

from test_cli_flow import PROJECT, apis, invoke, project_ready, runner  # noqa: F401 — fixtures partagées
from test_cli_flow import test_gate_2_flow as run_complete_flow

from research_lab.cli import app
from research_lab.storage.database import _MIGRATIONS, SCHEMA_VERSION, Database

HERE = Path(__file__).parent
GOLDEN = HERE / "golden"
SNAPSHOTS = HERE / "fixtures"
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"

# Livrables du projet et sorties de contrôle comparés aux références.
EXPORTS = [
    "project.yaml", "papers.json", "search-log.json", "evidence-matrix.json", "gaps.json", "alignment.json",
    "gate-1.json", "research-questions.json", "solutions.json", "scientific-review.json", "gate-2.json",
    "human-evaluation.json", "references.bib",
]
COMMANDS = {
    "project-resume.json": ["project", "resume", PROJECT, "--json"],
    "eval-report.json": ["eval", "report", PROJECT, "--json"],
    "gate-status.txt": ["gate", "status", PROJECT],
    "critique-check.txt": ["critique", "check", PROJECT],
    "proposal-check.txt": ["proposal", "check", PROJECT],
}


def normalize(text: str, root: Path) -> str:
    text = text.replace(str(root), "<root>").replace(str(root.resolve()), "<root>")
    text = re.sub(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?", "<datetime>", text)
    text = re.sub(r"\b[0-9a-f]{64}\b", "<sha256>", text)
    return re.sub(rf"\b{re.escape(getpass.getuser())}\b", "<user>", text)


def compare(name: str, actual: str) -> None:
    path = GOLDEN / name
    if UPDATE or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
        if not UPDATE:
            pytest.fail(f"référence créée : {path} (la relire, puis relancer)")
    assert actual == path.read_text(encoding="utf-8"), f"{name} diffère de la référence (UPDATE_GOLDEN=1 si voulu)"


# --- Migrations ----------------------------------------------------------------------------------


def _digest(script: str) -> str:
    return hashlib.sha256(script.encode()).hexdigest()


def test_published_migrations_never_change():
    path = GOLDEN / "migrations.json"
    recorded = json.loads(path.read_text()) if path.exists() else {}
    current = {str(n): _digest(s) for n, s in enumerate(_MIGRATIONS, start=1)}
    changed = [n for n, digest in recorded.items() if current.get(n) != digest]
    assert not changed, f"migrations publiées modifiées : {changed} (en ajouter une nouvelle à la fin de _MIGRATIONS)"
    if UPDATE or set(current) != set(recorded):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(current, indent=2) + "\n")
        if not UPDATE:
            pytest.fail(f"nouvelles migrations enregistrées dans {path} : relancer")


@pytest.mark.parametrize("version", range(SCHEMA_VERSION))
def test_every_schema_version_upgrades_to_the_latest(tmp_path, version):
    path = tmp_path / "research.db"
    conn = sqlite3.connect(path, isolation_level=None)
    for number, script in enumerate(_MIGRATIONS[:version], start=1):
        conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {number};\nCOMMIT;")
    conn.close()
    assert Database(path).conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


# --- Exports de référence --------------------------------------------------------------------------


@pytest.fixture
def completed(project_ready, apis, lab_root, tmp_path, monkeypatch):  # noqa: F811
    """Scénario complet jusqu'à la Gate 2 approuvée, puis une notation humaine."""
    run_complete_flow(project_ready, apis, lab_root, tmp_path, monkeypatch)
    rated = runner.invoke(app, ["eval", "rate", PROJECT], input="4\n3\n5\nManque réel\n4\n4\n3\n\nRAS\n")
    assert rated.exit_code == 0, rated.output
    return project_ready


def test_complete_scenario_matches_golden_exports(completed, lab_root):
    for name in EXPORTS:
        compare(f"exports/{name}", normalize((completed / name).read_text(encoding="utf-8"), lab_root))
    for name, args in COMMANDS.items():
        result = invoke(*args)
        assert result.exit_code == 0, result.output
        compare(f"commands/{name}", normalize(result.output, lab_root))

    if os.environ.get("REGRESSION_SNAPSHOT") == "1":
        target = SNAPSHOTS / f"snapshot-v{SCHEMA_VERSION}"
        shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True)
        db = Database(lab_root / "knowledge" / "research.db")
        db.conn.execute(f"VACUUM INTO '{target / 'research.db'}'")
        db.conn.close()
        shutil.copytree(lab_root / "knowledge" / "papers", target / "papers")
        shutil.copytree(completed, target / "project", ignore=shutil.ignore_patterns("*.tmp"))


# --- Instantanés d'anciennes versions --------------------------------------------------------------


def _snapshots() -> list[Path]:
    return sorted(SNAPSHOTS.glob("snapshot-v*")) if SNAPSHOTS.exists() else []


@pytest.mark.parametrize("snapshot", _snapshots(), ids=lambda p: p.name)
def test_snapshot_from_earlier_version_still_reads_and_verifies(snapshot, lab_root):
    (lab_root / "knowledge").mkdir(exist_ok=True)
    shutil.copy2(snapshot / "research.db", lab_root / "knowledge" / "research.db")
    shutil.copytree(snapshot / "papers", lab_root / "knowledge" / "papers")
    shutil.copytree(snapshot / "project", lab_root / "research" / "projects" / PROJECT)

    resume = json.loads(invoke("project", "resume", PROJECT, "--json").output)
    assert (resume["state"], resume["stale_exports"]) == ("COMPLETED", [])  # exports régénérés identiques
    for args in (["gate", "verify", PROJECT], ["review", "check", PROJECT], ["proposal", "check", PROJECT],
                 ["critique", "check", PROJECT], ["eval", "report", PROJECT], ["eval", "summary"]):
        result = invoke(*args)
        assert result.exit_code == 0, f"{' '.join(args)} : {result.output}"
    assert "2/2 gaps et hypothèses notés" in invoke("eval", "report", PROJECT).output  # notation conservée
