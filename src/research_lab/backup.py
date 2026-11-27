"""Sauvegarde cohérente du laboratoire (`db backup`, interface web) : base, textes intégraux, dossiers des projets."""

import shutil
import sqlite3
from pathlib import Path

from research_lab.config import Settings
from research_lab.storage.database import Database


def backup_lab(settings: Settings, db: Database, target: Path) -> int:
    """Copie le laboratoire dans `target` (absent ou vide) ; renvoie la version du schéma sauvegardé."""
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"{target} n'est pas vide")
    (target / "knowledge").mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(target / "knowledge" / "research.db") as copy:
        db.conn.backup(copy)  # cohérent même si une autre commande écrit en même temps
    for source, name in ((settings.papers_dir, "knowledge/papers"), (settings.projects_dir, "research/projects")):
        if source.exists():
            shutil.copytree(source, target / name, ignore=shutil.ignore_patterns("*.tmp"))
    return db.conn.execute("PRAGMA user_version").fetchone()[0]
