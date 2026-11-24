// Données renvoyées par l'API (src/research_lab/views.py).

export type State =
  | "NEW" | "SCOPING" | "LITERATURE_SEARCH" | "LITERATURE_REVIEW" | "GAP_ANALYSIS" | "AWAITING_GATE_1"
  | "PROBLEM_FORMULATION" | "SOLUTION_DESIGN" | "SCIENTIFIC_REVIEW" | "PROPOSAL_DRAFT" | "AWAITING_GATE_2"
  | "COMPLETED";

export interface Workflow { states: State[]; deliverables: Record<State, string[]> }

export interface ProjectSummary { id: string; topic: string; state: State; updated_at: string; waiting_for_human: boolean }

export interface StateChange { from_state: State | null; to_state: State; at: string; actor: string; forced: boolean }

export interface Paper {
  id: string; title: string; year: number | null; venue: string | null; status: string; url: string | null;
  pdf: string | null; sources: string[]; searches: string[]; reason: string | null;
}

export interface Search {
  id: string; at: string; query: string; from: string | null; to: string | null; status: string; gap_id: string | null;
  new: number; matched: number; sources: { source: string; status: string; total: number | null; hits: number }[];
}

export interface Gap {
  gap_id: string; title: string; description: string; rationale: string; status: string; novelty_assessment: string;
  supporting_papers: string[]; contradicting_papers: string[]; contradictory_searches: string[];
}

export interface Alignment {
  rank: number; gap_id: string; title: string; status: string; evidence_strength: string; priority_score: number;
}

export interface GateRound {
  round: number;
  submission: { submitted_at: string; check_status: string };
  decision: { decision: string; comment: string; approver: string; at: string; selected_gaps: Record<string, number> } | null;
}

export interface Hypothesis { hypothesis_id: string; statement: string; prediction: string; refutation_criterion: string }

export interface Question {
  question_id: string; version: number; status: string; question: string; gap_ids: string[]; hypotheses: Hypothesis[];
}

export interface Solution {
  solution_id: string; version: number; status: string; title: string; summary: string; addressed_hypotheses: string[];
}

export interface SolutionGroup {
  question_id: string; solutions: Solution[]; comparison_stale: boolean;
  comparison: { recommendation: string | null; justification: string } | null;
}

export interface Objection {
  objection_id: string; severity: string; targets: string[]; statement: string;
  response: { action: string; response: string } | null;
}

export interface Review { round: number; verdict: string; summary: string; at: string; objections: Objection[] }

export interface Indicator { control: string; name: string; value: string; ok: boolean | null }

export interface RatingSession {
  session_id: string; rater: string; at: string;
  ratings: { target: string; scores: Record<string, number>; comment: string }[];
}

export interface ProjectView {
  id: string; topic: string; state: State; created_at: string; updated_at: string;
  history: StateChange[]; visits: Partial<Record<State, number>>;
  resume: {
    step: string; action: string; waiting_for_human: boolean; human_instructions: string | null;
    next_steps: Record<string, string[]>; stale_exports: string[]; last_change_forced: boolean;
  };
  files: Record<string, { exists: boolean; href: string }>;
  papers: { by_status: Record<string, number>; all: Paper[] };
  search_log: Search[];
  searches: { total: number; contradictory: number };
  evidence: { total: number; by_type: Record<string, number> };
  reading: { complete?: number; total?: number; error?: string };
  gaps: Gap[]; alignment: Alignment[]; gate_1: GateRound[]; gate_2: GateRound[];
  questions: Question[]; solutions: SolutionGroup[]; reviews: Review[];
  proposal: { status: string; errors: string[]; warnings: string[] } | null;
  quality: Indicator[]; ratings: RatingSession[];
  costs: { total: number; responses: number; by_agent: Record<string, number>; by_state: Record<string, number> };
  documents: string[];
}
