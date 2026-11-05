---
name: gap-analysis
description: Analyse des gaps scientifiques. À partir de l'état de l'art et des preuves vérifiées (EV-xxx), identifie les questions non résolues, résultats contradictoires, évaluations manquantes et approches jamais comparées, les enregistre comme gaps GAP-xxx contestables, puis mène pour chacun une recherche contradictoire. À utiliser quand un projet est à l'état GAP_ANALYSIS.
allowed-tools: Read, Write(research/projects/*/drafts/*), Edit(research/projects/*/drafts/*), Bash(.venv/bin/research-lab *)
---

# gap-analysis — contrat v1.0

Un gap est un **manque de connaissance scientifique** établi à partir de la littérature (spec §4.2) :
une question non résolue, des résultats qui se contredisent, une propriété jamais évaluée, des
approches concurrentes jamais comparées. Il ne dépend pas de `research-values.yaml` : une solution
qui ne correspond pas aux valeurs du projet n'est pas un gap. Les valeurs servent ensuite à
**prioriser** les gaps (skill `values-alignment`).

Tout passe par `.venv/bin/research-lab`. Les seuls fichiers que tu écris sont des brouillons JSON
dans `research/projects/<id>/drafts/`, transmis à la CLI qui les valide et les enregistre.
`gaps.json` est régénéré depuis la base : ne jamais le modifier.

## Input

- Projet à l'état `GAP_ANALYSIS` (`project status <id>`).
- `research/projects/<id>/scope.md`, `literature-review.md`, `evidence-matrix.json`.
- Preuves : `.venv/bin/research-lab evidence list <id> --json`.

## Process

1. **Repérer les gaps** à partir de l'état de l'art et des preuves :
   - `unresolved_research_question` : question reconnue ouverte (souvent une preuve `limitation`) ;
   - `conflicting_results` : deux preuves qui se contredisent ;
   - `missing_evaluation` : propriété affirmée (`position`, `method`) mais jamais mesurée ou démontrée ;
   - `uncompared_approaches` : approches concurrentes du même problème jamais comparées.
   Un gap qui n'apparaît qu'en croisant plusieurs publications est légitime, mais le croisement
   est **ton interprétation** : l'écrire dans `rationale`, en citant les preuves.

2. **Écrire le brouillon** `research/projects/<id>/drafts/<nom>.json` :
   ```json
   {
     "title": "…",
     "description": "…",
     "category": "missing_evaluation",
     "rationale": "EV-004 affirme … ; aucune des preuves EV-007, EV-012 ne l'évalue …",
     "supporting_evidence": ["EV-004", "EV-007"],
     "contradicting_evidence": [],
     "evidence_strength": "medium",
     "open_questions": ["…"],
     "limitations": ["La recherche bibliographique peut être incomplète"],
     "objections": ["…"]
   }
   ```
   puis `.venv/bin/research-lab gap add <id> --file research/projects/<id>/drafts/<nom>.json --reason "…"`.
   Un nouveau gap est toujours `candidate`, nouveauté `unverified`.

3. **Recherche contradictoire (Q3)** pour chaque gap : chercher les travaux qui le combleraient déjà,
   avec les termes des approches concurrentes et des formulations différentes :
   ```
   .venv/bin/research-lab watch search <id> --for-gap GAP-xxx -q "…" [--from … --to …]
   ```
   Puis trier les nouvelles publications (`corpus list <id> --status candidate`, `corpus decide`),
   récupérer leur texte (`fulltext fetch`) et enregistrer les preuves utiles (`evidence add`),
   **en particulier celles qui contredisent le gap**.

4. **Réviser le gap** à la lumière de cette recherche : modifier le brouillon (repartir de
   `gap show <id> GAP-xxx`), puis
   `.venv/bin/research-lab gap revise <id> GAP-xxx --file … --reason "<ce qui a changé et pourquoi>"`.
   - `status` : `supported` (preuves d'au moins deux publications et recherche contradictoire faite),
     `candidate` (insuffisamment établi), `resolved` (des travaux le comblent : les citer en
     `contradicting_evidence`), `withdrawn` (erreur d'analyse).
   - `novelty_assessment` : `partially_addressed` si des travaux y répondent en partie (preuves
     contraires), `not_found_in_searches` si les recherches journalisées n'ont rien trouvé. Jamais
     « nouveau » : l'absence dans un corpus limité ne prouve pas l'absence dans la littérature.
   - `evidence_strength` : `high` exige des résultats établis (`empirical_result`, `theoretical_result`)
     de deux publications ; `medium`, un résultat établi ou deux publications ; sinon `low`.

5. **Contrôler** : `.venv/bin/research-lab gap check <id>`. Les erreurs liées à l'évaluation sur les
   valeurs se règlent avec le skill `values-alignment`.

## Output

- Gaps `GAP-xxx` versionnés dans la base ; `research/projects/<id>/gaps.json` (généré), avec pour
  chaque gap ses publications favorables et contraires et ses recherches contradictoires.
- Recherches contradictoires dans `search-log.json` (champ `gap_id`).

Compte rendu : nombre de gaps par statut et par catégorie, recherches contradictoires effectuées,
gaps remis en cause par ces recherches, limites.

## Quality gates

- Chaque gap cite au moins une preuve active ; la CLI refuse les preuves inconnues ou retirées.
- Observations (preuves) et interprétation (`rationale`) sont séparées.
- Les preuves contraires sont citées, pas omises ; les objections connues sont listées.
- Aucun gap `supported` sans recherche contradictoire ; aucune nouveauté déduite d'une absence.
- `gap check` sans erreur liée aux gaps.

## Failure behavior

| Situation | Comportement |
|---|---|
| Preuves insuffisantes pour établir un gap | Le laisser `candidate`, le dire ; statut `NEEDS_MORE_RESEARCH`. |
| Gap refusé par la CLI | Lire le message : ne pas gonfler `evidence_strength` ni le statut ; ajouter des preuves réelles ou rétrograder. |
| Recherche contradictoire qui trouve des travaux équivalents | Les inclure, citer leurs preuves en `contradicting_evidence`, passer le gap en `partially_addressed` ou `resolved`. |
| Aucun gap ne résiste | Le dire ; `NEEDS_MORE_RESEARCH`. Ne pas inventer de gap. |
| Citation invalide, `FulltextTampered` | `BLOCKED` : s'arrêter et le signaler. |
