"""Modification des fichiers de config/ depuis l'interface web.

Seules les valeurs existantes changent (pas de clé ajoutée ni retirée) ; les commentaires et la mise en forme
du fichier sont conservés. Le fichier modifié n'est écrit qu'après validation par `load_settings`, sur une copie.
"""

import io
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import FoldedScalarString, LiteralScalarString

from research_lab.config import load_settings

CONFIG_FILES = ["research-policy.yaml", "research-values.yaml", "scoring.yaml", "academic-sources.yaml", "costs.yaml"]


# Sections documentaires, que le code ne lit pas : non modifiables, pour ne pas laisser croire qu'elles agissent.
INFORMATIVE: dict[str, dict[str, str]] = {
    "research-policy.yaml": {
        "scientific_quality": "Règles de la spec §8, appliquées par les contrôles du code et les skills, pas par ces valeurs.",
        "human_gates": "Les deux gates sont toujours obligatoires : le workflow les impose, quelle que soit cette valeur.",
    },
}


class ConfigEditError(Exception):
    pass


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096  # ne pas replier les lignes longues
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def config_data(root: Path) -> dict[str, dict]:
    """Contenu de chaque fichier, tel que le formulaire le pré-remplit."""
    directory = root / "config"
    return {name: yaml.safe_load((directory / name).read_text(encoding="utf-8")) or {}
            for name in CONFIG_FILES if (directory / name).exists()}


def _scalar(old: Any, new: Any, where: str) -> Any:
    if isinstance(old, bool) or isinstance(new, bool):
        if not (isinstance(old, bool) and isinstance(new, bool)):
            raise ConfigEditError(f"{where} : oui/non attendu")
        return new
    if isinstance(old, (int, float)):
        if not isinstance(new, (int, float)):
            raise ConfigEditError(f"{where} : nombre attendu")
        return new
    if isinstance(old, str):
        if not isinstance(new, str):
            raise ConfigEditError(f"{where} : texte attendu")
        for style in (FoldedScalarString, LiteralScalarString):  # style de bloc (`>`, `|`) conservé
            if isinstance(old, style):
                return style(new if new.endswith("\n") else new + "\n")
        return new
    raise ConfigEditError(f"{where} : valeur non modifiable")


def _merge(node: CommentedMap, data: dict, where: str) -> None:
    for key, new in data.items():
        path = f"{where}.{key}" if where else key
        if key not in node:
            raise ConfigEditError(f"{path} : clé inconnue (le formulaire ne modifie que les valeurs existantes)")
        old = node[key]
        if isinstance(old, CommentedMap):
            if not isinstance(new, dict):
                raise ConfigEditError(f"{path} : section attendue")
            _merge(old, new, path)
        elif isinstance(old, CommentedSeq):
            if not isinstance(new, list) or any(isinstance(v, (dict, list)) for v in new):
                raise ConfigEditError(f"{path} : liste de valeurs attendue")
            old[:] = new  # style (en ligne ou en bloc) conservé
        else:
            node[key] = _scalar(old, new, path)


def update_config(root: Path, name: str, data: dict) -> None:
    """Applique `data` au fichier config/<name>, le valide, puis l'écrit."""
    if name not in CONFIG_FILES:
        raise ConfigEditError(f"Fichier de configuration inconnu : {name}")
    path = root / "config" / name
    y = _yaml()
    current = path.read_text(encoding="utf-8")
    document = y.load(current)
    plain = yaml.safe_load(current) or {}
    if fixed := [k for k in INFORMATIVE.get(name, {}) if k in data and data[k] != plain.get(k)]:
        raise ConfigEditError(f"{', '.join(fixed)} : section informative, non lue par le code, non modifiable")
    _merge(document, data, "")
    out = io.StringIO()
    y.dump(document, out)
    text = out.getvalue()
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copytree(root / "config", Path(tmp) / "config")
        (Path(tmp) / "config" / name).write_text(text, encoding="utf-8")
        try:
            load_settings(Path(tmp))
        except (ValidationError, ValueError) as exc:
            raise ConfigEditError(f"Configuration invalide, fichier inchangé : {exc}") from exc
    temporary = path.with_suffix(".yaml.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)
