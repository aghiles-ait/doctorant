import type { State } from "./types";

export const STATES: Record<State, { label: string; description: string }> = {
  NEW: { label: "Nouveau", description: "Projet créé dans la base." },
  SCOPING: { label: "Périmètre", description: "Sujet, questions initiales, inclus / exclus, mots-clés, critères de sélection (scope.md)." },
  LITERATURE_SEARCH: { label: "Recherche biblio.", description: "Requêtes arXiv et OpenAlex journalisées ; corpus dédupliqué avec provenance." },
  LITERATURE_REVIEW: { label: "État de l'art", description: "Tri des publications, lecture du texte intégral, preuves EV-xxx vérifiées, literature-review.md." },
  GAP_ANALYSIS: { label: "Analyse des gaps", description: "Gaps établis par la littérature, recherches contradictoires, évaluation au regard des valeurs." },
  AWAITING_GATE_1: { label: "Gate 1", description: "Décision humaine : quels gaps retenir (ou révision de la recherche)." },
  PROBLEM_FORMULATION: { label: "Problématique", description: "Questions de recherche RQ-xxx et hypothèses falsifiables sur les gaps retenus." },
  SOLUTION_DESIGN: { label: "Solutions", description: "Au moins deux solutions par question, comparées critère par critère." },
  SCIENTIFIC_REVIEW: { label: "Revue critique", description: "Revue indépendante (agent scientific-reviewer) : verdict et objections OBJ-xxx." },
  PROPOSAL_DRAFT: { label: "Proposal", description: "Research Proposal rédigé depuis les livrables, bibliographie générée." },
  AWAITING_GATE_2: { label: "Gate 2", description: "Décision humaine : accepter le Proposal ou demander une révision." },
  COMPLETED: { label: "Terminé", description: "Projet terminé ; évaluation humaine des gaps et des hypothèses." },
};

// Ce que produit chaque état : effacé par un retour en arrière forcé vers un état antérieur.
export const PRODUCES: Partial<Record<State, string>> = {
  SCOPING: "scope.md",
  LITERATURE_SEARCH: "recherches et corpus (publications qu'aucun autre projet n'utilise)",
  LITERATURE_REVIEW: "tri, preuves, pages lues, literature-review.md",
  GAP_ANALYSIS: "gaps, évaluations sur les valeurs, recherches contradictoires et publications qu'elles seules ont apportées, brouillons",
  AWAITING_GATE_1: "soumissions et décisions de la Gate 1",
  PROBLEM_FORMULATION: "questions de recherche et hypothèses",
  SOLUTION_DESIGN: "solutions et comparaisons",
  SCIENTIFIC_REVIEW: "revues critiques, objections et réponses",
  PROPOSAL_DRAFT: "research-proposal.md, references.bib",
  AWAITING_GATE_2: "soumissions et décisions de la Gate 2",
  COMPLETED: "évaluations humaines",
};

export const GATES = new Set<State>(["AWAITING_GATE_1", "AWAITING_GATE_2"]);

export const label = (state: string) => STATES[state as State]?.label ?? state;

export const fmtDate = (s?: string | null) =>
  s ? new Date(s).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" }) : "";

export const money = (x: number) => x.toLocaleString("fr-FR", { style: "currency", currency: "USD" });
