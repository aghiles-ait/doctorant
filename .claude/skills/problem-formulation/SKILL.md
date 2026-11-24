---
name: problem-formulation
description: Formulation du problème. À partir des gaps retenus par l'humain à la Gate 1, formule des questions de recherche RQ-xxx et des hypothèses falsifiables (prédiction, critère de réfutation, méthode de test, métriques, preuves EV-xxx), enregistrées et contrôlées par la CLI. À utiliser quand un projet est à l'état PROBLEM_FORMULATION.
allowed-tools: Read, Write(research/projects/*/drafts/*), Edit(research/projects/*/drafts/*), Bash(.venv/bin/research-lab *)
---

# problem-formulation — contrat v1.0

Une question de recherche répond à un ou plusieurs **gaps retenus par l'humain à la Gate 1**, et
seulement à ceux-là. Chaque question porte des hypothèses **falsifiables** (spec Q4) : une
hypothèse dit ce qu'on observerait si elle était vraie, et surtout ce qui la réfuterait.

Tout passe par `.venv/bin/research-lab`. Les seuls fichiers que tu écris sont des brouillons JSON
dans `research/projects/<id>/drafts/`. `research-questions.json` est régénéré depuis la base :
ne jamais le modifier.

## Input

- Projet à l'état `PROBLEM_FORMULATION` (`project status <id>`).
- Décision de la Gate 1 : `gate status <id>` (gaps retenus et commentaire de l'humain, à prendre en compte).
- Gaps retenus : `gap show <id> GAP-xxx` (preuves, objections, questions ouvertes, limites).
- Preuves : `evidence list <id> --json` ; `literature-review.md`, `alignment.json` (compromis entre valeurs).

## Process

1. **Lire la décision humaine** : gaps retenus et commentaire. Les gaps écartés ne donnent lieu à
   aucune question.

2. **Formuler les questions.** Une question par gap en général ; une question peut couvrir plusieurs
   gaps s'ils portent sur le même objet (le dire dans `rationale`). Partir des `open_questions` et
   `objections` du gap. Une bonne question est délimitée (objet, contexte, critère de réponse).

3. **Formuler les hypothèses** de chaque question (`H1`, `H2`… propres à la question) :
   - `statement` : l'affirmation testée ;
   - `prediction` : ce qu'on observerait si elle est vraie ;
   - `refutation_criterion` : le résultat qui la réfuterait — un seuil, un contre-exemple, une
     comparaison défavorable. Pas une reformulation de la prédiction à la négative vague ;
   - `test_method` : comment l'observer (expérience, simulation, étude empirique, preuve formelle) ;
   - `metrics` : ce qui est mesuré ;
   - `evidence` : les preuves `EV-xxx` qui motivent l'hypothèse (celles du gap, ou d'autres preuves
     du projet). Une hypothèse n'est pas un fait : elle s'appuie sur des preuves, elle ne les cite pas
     comme démonstration.
   Proposer aussi une hypothèse concurrente quand la littérature en suggère une (preuves contraires du gap).

4. **Écrire le brouillon** `research/projects/<id>/drafts/question-<nom>.json` :
   ```json
   {
     "question": "…?",
     "gap_ids": ["GAP-001"],
     "rationale": "GAP-001 montre que … ; la question porte sur …",
     "hypotheses": [
       {
         "hypothesis_id": "H1",
         "statement": "…",
         "prediction": "…",
         "refutation_criterion": "…",
         "test_method": "…",
         "metrics": ["…"],
         "evidence": ["EV-004", "EV-012"]
       }
     ],
     "constraints": ["…"],
     "limitations": ["…"]
   }
   ```
   puis `.venv/bin/research-lab question add <id> --file research/projects/<id>/drafts/question-<nom>.json`.

5. **Réviser** si besoin : `question show <id> RQ-xxx`, modifier le brouillon, puis
   `question revise <id> RQ-xxx --file … --reason "<ce qui change et pourquoi>"`.
   Une question abandonnée passe au statut `withdrawn` (elle n'est jamais supprimée).

6. **Contrôler et clore** : `.venv/bin/research-lab question check <id>` jusqu'à `OK`, puis
   `.venv/bin/research-lab project transition <id> SOLUTION_DESIGN`.

## Output

- Questions `RQ-xxx` versionnées dans la base ; `research/projects/<id>/research-questions.json`
  (généré), avec les publications citées par les hypothèses.

Compte rendu : questions et gaps couverts, hypothèses avec leur critère de réfutation, hypothèses
concurrentes, ce qui reste incertain.

## Quality gates

- Chaque gap retenu à la Gate 1 a au moins une question active ; aucune question hors des gaps retenus.
- Chaque hypothèse a une prédiction, un critère de réfutation distinct, une méthode de test, au
  moins une métrique et au moins une preuve active.
- `question check` renvoie `OK`.

Le code vérifie la présence et la cohérence de ces éléments, pas leur qualité : un critère de
réfutation impossible à observer en pratique reste ta responsabilité (il sera examiné par le
reviewer et à la Gate 2).

## Failure behavior

| Situation | Comportement |
|---|---|
| Question refusée (gap non retenu, preuve inconnue ou retirée) | Corriger selon le message ; ne pas rattacher la question à un autre gap pour la faire passer. |
| Hypothèse impossible à réfuter | La reformuler ou l'abandonner ; ne pas écrire un critère de réfutation de pure forme. |
| Gap retenu dont les preuves ne permettent aucune hypothèse testable | Le dire dans le compte rendu et dans `limitations` ; formuler la question la plus étroite possible. |
| Le commentaire de la Gate 1 demande autre chose que ce que permet le corpus | Le signaler ; ne pas combler avec des connaissances hors corpus. |
