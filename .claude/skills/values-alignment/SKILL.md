---
name: values-alignment
description: Évalue chaque gap actif (GAP-xxx) au regard de chaque valeur de config/research-values.yaml, avec justification et compromis explicites, et obtient un classement de priorité calculé par le code. À utiliser après gap-analysis, à l'état GAP_ANALYSIS, pour préparer la Gate 1.
allowed-tools: Read, Write(research/projects/*/drafts/*), Edit(research/projects/*/drafts/*), Bash(.venv/bin/research-lab *)
---

# values-alignment — contrat v1.0

Les valeurs (`config/research-values.yaml`) **ne créent pas de gaps** et ne modifient pas leur
statut : elles mesurent à quel point combler un gap servirait ces valeurs, pour aider l'humain
à choisir à la Gate 1. Le score et le classement sont calculés par le code
(`config/scoring.yaml`) ; tu fournis les évaluations et leurs justifications.

## Input

- Projet à l'état `GAP_ANALYSIS`, gaps enregistrés (`gap list <id>`).
- `config/research-values.yaml` : valeurs, descriptions, échelle (0 à 5), règles d'évaluation.
- Pour chaque gap : `gap show <id> GAP-xxx` et ses preuves.

## Process

1. Pour chaque gap `candidate` ou `supported`, écrire `research/projects/<id>/drafts/alignment-GAP-xxx.json` :
   ```json
   {
     "scores": {
       "privacy":          {"score": 4, "justification": "…"},
       "freedom":          {"score": null, "justification": "Sans rapport avec … (non applicable)"},
       "sovereignty":      {"score": 2, "justification": "…"},
       "governance":       {"score": 5, "justification": "…"},
       "decentralization": {"score": 3, "justification": "…"},
       "verifiability":    {"score": 5, "justification": "…"}
     },
     "tradeoffs": ["Rendre la gouvernance vérifiable expose davantage de données (verifiability contre privacy)"]
   }
   ```
   - Toutes les valeurs du fichier, ni plus ni moins ; `null` = non applicable, justifié aussi.
   - Le score porte sur **ce que permettrait de combler le gap**, pas sur la qualité des publications.
   - Une justification s'appuie sur le contenu du gap et ses preuves (`EV-xxx`), pas sur une préférence.
   - `tradeoffs` : les tensions entre valeurs. Liste vide seulement si aucune n'est identifiée.

2. `.venv/bin/research-lab alignment set <id> GAP-xxx --file research/projects/<id>/drafts/alignment-GAP-xxx.json`
   La CLI vérifie l'évaluation et calcule l'alignement (0 à 1) et la priorité (0 à 1).

3. Toute révision d'un gap rend son évaluation périmée : la refaire. Un changement de
   `research-values.yaml` ou `scoring.yaml` aussi.

4. `.venv/bin/research-lab alignment show <id>` (classement) puis `gap check <id>` jusqu'à ne plus avoir d'erreur.

## Output

- Évaluations historisées dans la base ; `research/projects/<id>/alignment.json` (généré) :
  gaps actifs classés par priorité, scores par valeur, justifications, compromis.

Compte rendu : classement, principaux compromis, gaps dont l'évaluation est incertaine.

## Quality gates

- Chaque gap actif a une évaluation à jour (`gap check` sans erreur).
- Chaque score est justifié ; les compromis sont explicites.
- Un gap peu aligné sur les valeurs reste présenté : la priorité informe la Gate 1, elle ne filtre pas.

## Failure behavior

| Situation | Comportement |
|---|---|
| Évaluation refusée | Corriger selon le message (valeur manquante, score hors échelle, justification vide). |
| Aucune valeur applicable à un gap (refusé par la CLI) | Noter 0 les valeurs que le gap ne sert pas, avec justification : il reste présenté à la Gate 1, en bas du classement. |
| Doute sur un score | Le dire dans la justification plutôt que de choisir un score extrême. |
