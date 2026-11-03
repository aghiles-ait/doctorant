---
name: scientific-watch
description: Veille bibliographique traçable. Interroge arXiv et OpenAlex pour un projet de recherche, constitue un corpus dédupliqué avec provenance et journal des requêtes. À utiliser quand un projet est à l'état LITERATURE_SEARCH et qu'il faut trouver ou compléter les publications sur son sujet.
allowed-tools: Read, Bash(.venv/bin/research-lab *)
---

# scientific-watch — contrat v1.0

Toutes les opérations passent par la CLI `.venv/bin/research-lab`. Ne modifie jamais
`papers.json`, `search-log.json` ou `project.yaml` à la main : la CLI garantit
les identifiants stables, la déduplication et la provenance.

## Input

- `project_id` : projet existant dans `research/projects/<project_id>/`, à l'état `LITERATURE_SEARCH`.
- `research/projects/<project_id>/scope.md` : question, mots-clés, synonymes, période, critères d'inclusion.
- `config/academic-sources.yaml`, `config/research-policy.yaml`.

## Process

1. **Vérifier l'état** : `.venv/bin/research-lab project status <id> --json`. Si l'état n'est pas
   `LITERATURE_SEARCH`, s'arrêter et le signaler.
2. **Lire `scope.md`** et en dériver un plan de requêtes : 3 à 6 requêtes couvrant le sujet principal,
   ses synonymes et les termes des approches concurrentes. Une requête = quelques mots-clés ;
   `"expression exacte"` entre guillemets. Toutes les requêtes utilisent la même période.
3. **Exécuter chaque requête** :
   ```
   .venv/bin/research-lab watch search <id> --query '<mots-clés>' --from AAAA-MM-JJ --to AAAA-MM-JJ --json
   ```
   Options : `--sources arxiv,openalex`, `--max-results N` (par source).
4. **Contrôler le corpus** : `.venv/bin/research-lab corpus check <id> --json`.
5. **Inspecter** si nécessaire : `corpus list <id>`, `corpus show <id> PAPER-xxx`, `search-log <id>`.

## Output

Fichiers produits par la CLI dans `research/projects/<id>/` :
- `papers.json` : publications (`PAPER-xxx`), identifiants externes, métadonnées, provenance.
- `search-log.json` : chaque exécution (`SEARCH-xxx`), requête envoyée à chaque API, dates, résultats, erreurs, empreinte de configuration.

Compte rendu à l'agent appelant :
- statut final : `OK`, `NEEDS_MORE_RESEARCH` ou `BLOCKED` ;
- tableau des recherches : `SEARCH-xxx`, requête, sources, période, nombre de nouveaux résultats ;
- taille du corpus et répartition par source ;
- limites : sources non interrogées (Semantic Scholar, Crossref), période, nombre maximal de résultats, langue.

## Quality gates

- `corpus check` ne renvoie pas `BLOCKED`.
- Toute publication mentionnée dans le compte rendu est citée par son `PAPER-xxx` et existe dans `papers.json`.
- Aucune publication issue de la mémoire du modèle ou d'une recherche web n'est présentée comme faisant partie du corpus.
- Le nombre de résultats disponibles (`total_available`) est rapporté : un corpus plafonné par `--max-results` n'est pas exhaustif.

## Failure behavior

| Situation | Code CLI | Comportement |
|---|---|---|
| Une source ne répond pas | `watch search` sort avec le code 2, statut `failed`, corpus inchangé | Relancer une fois la même requête. Si l'échec persiste : statut `BLOCKED`, citer l'erreur du journal. Ne pas utiliser `--allow-partial` sauf instruction humaine explicite. |
| Corpus sous le seuil de la politique | `corpus check` → `NEEDS_MORE_RESEARCH` | Élargir les requêtes ou la période, puis recontrôler. Si le sujet reste peu couvert, le rapporter tel quel : c'est une information, pas un échec à masquer. |
| Incohérence du corpus | `corpus check` sort avec le code 2 → `BLOCKED` | S'arrêter et rapporter les erreurs. Ne pas corriger les fichiers à la main. |
| Projet pas à l'état `LITERATURE_SEARCH` | code 1 | S'arrêter ; le périmètre doit d'abord être défini. |
