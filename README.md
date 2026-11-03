# AI Research Doctorant

Laboratoire de recherche scientifique assisté par IA, piloté depuis Claude Code.
Spécification : [specs.md](specs.md).

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env   # facultatif : clé API OpenAlex
```

Les variables `OPENALEX_API_KEY` et `OPENALEX_MAILTO` sont lues dans l'environnement du
processus (le fichier `.env` n'est pas chargé automatiquement : `set -a; source .env; set +a`).
Sans clé, OpenAlex limite les requêtes à un petit budget quotidien partagé par adresse IP.

## Utilisation avec Claude Code

Lancer `claude` à la racine du dépôt, puis par exemple :

> Utilise l'agent doctorant pour démarrer un projet sur la gouvernance décentralisée de l'IA.

L'agent crée le projet, rédige `scope.md`, puis exécute le skill `scientific-watch`.

## Utilisation directe de la CLI

```bash
L=.venv/bin/research-lab
$L project init decentralized-ai-governance --topic "Decentralized AI governance"
$L project transition decentralized-ai-governance SCOPING
# rédiger research/projects/decentralized-ai-governance/scope.md
$L project transition decentralized-ai-governance LITERATURE_SEARCH

$L watch search decentralized-ai-governance -q '"AI governance" decentralized' --from 2022-01-01 --to 2026-10-26
$L corpus list decentralized-ai-governance
$L corpus show decentralized-ai-governance PAPER-001
$L corpus check decentralized-ai-governance
$L search-log decentralized-ai-governance
```

Les commandes acceptent `--json` pour une sortie exploitable par les Skills.

| Code de sortie | Signification |
|---|---|
| 0 | Succès |
| 1 | Erreur d'utilisation ou état du projet incompatible |
| 2 | `watch search` : une source a échoué, corpus inchangé ; `corpus check` : corpus incohérent (`BLOCKED`) |

## Tests

```bash
.venv/bin/pytest             # hors réseau (APIs simulées à partir de réponses réelles enregistrées)
.venv/bin/pytest -m network  # appels réels à arXiv et OpenAlex
```

## État d'avancement

**Sprint 1 — implémenté**
- Projet persistant et transitions `NEW → SCOPING → LITERATURE_SEARCH` contrôlées par le code
  (`scope.md` obligatoire avant la recherche).
- Connecteurs arXiv et OpenAlex : pagination, limites de débit, relances.
- Corpus par projet (`papers.json`) : identifiants `PAPER-xxx` stables, déduplication
  par DOI, arXiv ID, OpenAlex ID puis titre et année, provenance de chaque résultat.
- Journal des recherches (`search-log.json`) : requête envoyée à chaque API, période,
  horodatages, nombre de résultats, erreurs, version de l'outil et empreinte de configuration.
- Agent `doctorant` (étapes 1 et 2) et skill `scientific-watch`.

**Non implémenté**
- Connecteurs Semantic Scholar et Crossref ; vérification de l'existence des DOI auprès de Crossref.
- Base SQLite (`knowledge/research.db`) et corpus partagé entre projets : sprint 2.
- Skills `literature-review`, `gap-analysis`, `values-alignment`, matrice de preuves, Gate 1 : sprint 2.
- Skills `problem-formulation`, `solution-architect`, `scientific-critic`, `research-writer`,
  agent `scientific-reviewer`, Gate 2, `references.bib` : sprint 3.
- Templates (`templates/`), scores (`config/scoring.yaml`), suivi des coûts, évaluations : sprints 2 à 4.
- Transitions au-delà de `LITERATURE_SEARCH` : refusées explicitement par la CLI.
