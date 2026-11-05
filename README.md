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

### Périmètre et recherche bibliographique

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

### État de l'art

```bash
$L project transition decentralized-ai-governance LITERATURE_REVIEW   # exige corpus check OK

$L corpus list decentralized-ai-governance --status candidate
$L corpus decide decentralized-ai-governance PAPER-001 --include --reason "…"
$L corpus decide decentralized-ai-governance PAPER-004 --exclude --reason "…"

$L fulltext fetch decentralized-ai-governance      # PDF en accès libre des publications incluses
$L fulltext status decentralized-ai-governance
$L fulltext show decentralized-ai-governance PAPER-001 --page 3

$L evidence add decentralized-ai-governance --paper PAPER-001 --page 3 --type empirical_result \
   --claim "…" --quote "extrait exact du texte"   # refusé si l'extrait n'est pas à cette page
$L evidence list decentralized-ai-governance
$L evidence withdraw decentralized-ai-governance EV-004 --reason "…"

# rédiger research/projects/decentralized-ai-governance/literature-review.md, citations [PAPER-xxx, EV-xxx]
$L review check decentralized-ai-governance
$L project transition decentralized-ai-governance GAP_ANALYSIS
```

Une preuve n'est acceptée que si son extrait figure réellement dans la publication : à la page
indiquée du texte intégral, ou dans le résumé quand aucune version libre n'existe. La comparaison
ignore la casse, les accents, la ponctuation et les espaces, pour tolérer les artefacts
d'extraction des PDF. Elle ne juge pas si l'extrait soutient l'affirmation : c'est le rôle du
reviewer (sprint 3) et de la Gate 1.

### Gaps et alignement sur les valeurs

```bash
# brouillon JSON écrit par l'agent (champs : voir .claude/skills/gap-analysis/SKILL.md)
$L gap add decentralized-ai-governance --file research/projects/decentralized-ai-governance/drafts/gap.json
$L watch search decentralized-ai-governance --for-gap GAP-001 -q "…"   # recherche contradictoire (Q3)
$L corpus decide decentralized-ai-governance PAPER-040 --include --reason "…"   # nouvelles publications
$L gap revise decentralized-ai-governance GAP-001 --file … --reason "…"   # nouvelle version
$L gap list decentralized-ai-governance
$L gap show decentralized-ai-governance GAP-001 --history

$L alignment set decentralized-ai-governance GAP-001 --file …/drafts/alignment-GAP-001.json
$L alignment show decentralized-ai-governance   # classement par priorité
$L gap check decentralized-ai-governance        # OK, NEEDS_MORE_RESEARCH ou BLOCKED
```

Un gap est un manque de connaissance établi par la littérature (spec §4.2) et cite des
preuves `EV-xxx`. Le code refuse ce que les preuves ne permettent pas d'affirmer :
- une force de preuves surévaluée ;
- le statut `supported` sans preuves d'au moins deux publications ni recherche contradictoire ;
- une nouveauté `not_found_in_searches` sans recherche contradictoire.

Les valeurs de `research-values.yaml` ne créent pas de gaps. Elles servent à les noter : chaque
valeur reçoit un score justifié, avec les compromis entre valeurs. La priorité combine cet
alignement avec la force des preuves (`config/scoring.yaml`). Réviser un gap ou modifier les
valeurs rend son évaluation périmée.

### Gate 1 : validation humaine

```bash
$L gate submit decentralized-ai-governance    # l'agent soumet (refusé si `gap check` est BLOCKED)
$L gate status decentralized-ai-governance    # dossier : gaps classés, contrôles, intégrité
$L gate verify decentralized-ai-governance    # livrables inchangés depuis la soumission ?

# Décision : toi seul, dans ton propre terminal (refusée depuis Claude Code ou sans terminal)
$L gate approve decentralized-ai-governance --gap GAP-001 --gap GAP-003 --comment "…"   # → PROBLEM_FORMULATION
$L gate revise decentralized-ai-governance --comment "Chercher aussi …"                  # → LITERATURE_SEARCH
```

La soumission fige les empreintes de `scope.md`, `literature-review.md`, `evidence-matrix.json`,
`gaps.json` et `alignment.json`, ainsi que la version de chaque gap. Une approbation est refusée
si l'un de ces fichiers a changé depuis. La décision demande de retaper l'identifiant du projet,
puis elle est enregistrée de façon immuable avec ton identifiant système et la date, et exportée
dans `gate-1.json`. Une révision conserve le corpus, les preuves et les gaps ; ton commentaire
indique à l'agent quoi chercher, puis le projet est soumis à nouveau (tour 2, 3…).

Limite : le contrôle (variable `CLAUDECODE` absente, terminal interactif, règles `deny` de
`.claude/settings.json`) empêche l'agent d'approuver en suivant son workflow ; ce n'est pas une
authentification forte. Un programme ayant accès au shell pourrait le contourner délibérément.

## Stockage

Toutes les données sont dans **`knowledge/research.db`** (SQLite), partagée entre les projets :
une publication trouvée par deux projets n'a qu'un identifiant `PAPER-xxx`. Les fichiers
`project.yaml`, `papers.json` et `search-log.json` de chaque projet sont **régénérés depuis la
base** après chaque écriture : ils servent à la lecture, les modifier n'a aucun effet.

```bash
$L db info                  # projets, nombre de publications et de recherches
$L db import-files          # importe les projets créés au sprint 1 (fichiers JSON)
```

La base n'est pas versionnée dans Git (fichier binaire) : **sauvegarde-la** avec le reste
de tes données de recherche.

| Code de sortie | Signification |
|---|---|
| 0 | Succès |
| 1 | Erreur d'utilisation ou état du projet incompatible |
| 2 | `watch search` : une source a échoué, corpus inchangé ; `corpus check`, `review check`, `gap check` : `BLOCKED` ; `gate verify` : livrables modifiés |

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

**Sprint 2 — implémenté**

*Base de données*
- Base SQLite partagée, migrations numérotées, import sans perte des projets du sprint 1.
- Garanties portées par la base : identifiants immuables, publications et journal jamais
  supprimés, toute publication a au moins un identifiant externe, écritures en une transaction.
- Déduplication sur toute la base ; doublons probables signalés (`merge_warnings`) quand deux
  publications existantes se révèlent identiques, plutôt que fusionnées automatiquement.

*État de l'art*
- Tri des publications (`included` / `excluded`) avec justification historisée.
- Texte intégral : PDF arXiv puis versions libres d'OpenAlex, texte extrait page par page,
  stocké dans `knowledge/papers/` et protégé par son empreinte.
- Preuves `EV-xxx` vérifiées contre le texte, immuables, retirables avec une raison ;
  matrice de preuves `evidence-matrix.json`.
- Contrôle des citations de `literature-review.md` et transitions `LITERATURE_REVIEW` /
  `GAP_ANALYSIS` conditionnées. Skill `literature-review`, agent `doctorant` étape 3.

*Gaps et valeurs*
- Gaps `GAP-xxx` versionnés (identifiant stable, historique en ajout seul), appuyés sur des
  preuves vérifiées ; règles de force des preuves, de statut et de nouveauté contrôlées par le code.
- Recherches contradictoires rattachées à un gap (`--for-gap`), seules recherches permises en
  `GAP_ANALYSIS` ; tri, texte intégral et preuves des publications qu'elles trouvent.
- Évaluation de chaque gap actif au regard de `research-values.yaml`, score de priorité,
  `gaps.json`, `alignment.json`, `gap check`. Skills `gap-analysis` et `values-alignment`.

*Gate 1*
- Gate 1 : soumission par l'agent avec empreintes des livrables, décision humaine
  (`approve` avec choix des gaps, ou `revise` avec instructions), enregistrée de façon immuable
  avec la transition dans une même transaction ; `gate-1.json`, `gate verify`.
- Les transitions des gates ne passent jamais par `project transition`.

**Non implémenté**
- Connecteurs Semantic Scholar et Crossref ; vérification de l'existence des DOI auprès de Crossref.
- En `LITERATURE_REVIEW`, plus de nouvelle recherche bibliographique ; en `GAP_ANALYSIS`, seulement
  des recherches contradictoires. Le retour à `LITERATURE_SEARCH` passe par `gate revise`.
- Pas de décision `reject` à la Gate 1 : `revise` couvre le besoin.
- Skills `problem-formulation`, `solution-architect`, `scientific-critic`, `research-writer`,
  agent `scientific-reviewer`, Gate 2, `references.bib` : sprint 3.
- Templates (`templates/`), suivi des coûts, évaluations : sprints 3 et 4.
- Transitions au-delà de `PROBLEM_FORMULATION` : refusées explicitement par la CLI.
