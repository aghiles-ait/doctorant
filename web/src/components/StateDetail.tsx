import type { ReactNode } from "react";
import type { GateRound, ProjectView, State, Workflow } from "../types";
import { STATES, fmtDate } from "../workflow";
import { CorpusTable, SearchTable } from "./tables";
import { Badge, Empty, Figures, verdictTone } from "./ui";

interface Props { project: ProjectView; workflow: Workflow; state: State; onOpenDocument: (name: string) => void }

export function StateDetail({ project, workflow, state, onOpenDocument }: Props) {
  const visits = project.visits[state] ?? 0;
  const status = state === project.state ? <Badge tone="cur">état actuel</Badge>
    : visits ? <Badge tone="ok">{visits > 1 ? `visité ${visits} fois` : "franchi"}</Badge> : <Badge>à venir</Badge>;
  const doc = (name: string) => project.documents.includes(name)
    ? <button className="file" onClick={() => onOpenDocument(name)}>📄 lire {name}</button> : null;
  return (
    <div className="card">
      <h3>{STATES[state].label} <span className="sub">{state}</span> {status}</h3>
      <p className="sub">{STATES[state].description}</p>
      <div className="files">
        {workflow.deliverables[state].map((name) => {
          const f = project.files[name];
          return f?.exists
            ? <a key={name} className="file" href={f.href} target="_blank" rel="noopener noreferrer">✓ {name}</a>
            : <span key={name} className="file missing">— {name}</span>;
        })}
      </div>
      {DETAILS[state](project, doc)}
    </div>
  );
}

type Detail = (p: ProjectView, doc: (name: string) => ReactNode) => ReactNode;

function GateRounds({ rounds, gate }: { rounds: GateRound[]; gate: string }) {
  if (!rounds.length) return <Empty>Pas encore soumis à la {gate}.</Empty>;
  return (
    <>
      {rounds.map((r) => {
        const d = r.decision;
        return (
          <div className="item" key={r.round}>
            <div className="h"><b>Tour {r.round}</b>
              <Badge>soumis le {fmtDate(r.submission.submitted_at)}</Badge>
              <Badge tone={r.submission.check_status === "OK" ? "ok" : "gate"}>contrôle {r.submission.check_status}</Badge>
              {d ? <Badge tone={verdictTone(d.decision)}>{d.decision === "approve" ? "approuvé" : "révision demandée"}</Badge>
                : <Badge tone="gate">en attente de ta décision</Badge>}
            </div>
            {d && <p>« {d.comment} » — {d.approver}, {fmtDate(d.at)}</p>}
            {d && Object.keys(d.selected_gaps).length > 0 &&
              <p>Gaps retenus : {Object.keys(d.selected_gaps).map((g) => <code key={g}>{g} </code>)}</p>}
          </div>
        );
      })}
    </>
  );
}

const DETAILS: Record<State, Detail> = {
  NEW: (p) => <Figures items={[[fmtDate(p.created_at), "création"], [p.history.length, "changements d'état"]]} />,

  SCOPING: (_p, doc) => <p>{doc("scope.md") ?? <span className="empty">scope.md pas encore rédigé.</span>}</p>,

  LITERATURE_SEARCH: (p) => (
    <>
      <Figures items={[
        [p.searches.total, "recherches journalisées"], [p.searches.contradictory, "dont contradictoires (gaps)"],
        [p.papers.all.length, "publications au corpus"], [p.papers.by_status.candidate ?? 0, "à trier"],
      ]} />
      <SearchTable project={p} />
      <CorpusTable project={p} />
    </>
  ),

  LITERATURE_REVIEW: (p, doc) => (
    <>
      <Figures items={[
        [p.papers.by_status.included ?? 0, "incluses"], [p.papers.by_status.excluded ?? 0, "exclues"],
        [p.evidence.total, "preuves EV-xxx actives"],
        [p.reading.error ? "!" : `${p.reading.complete}/${p.reading.total}`, "textes intégraux lus en entier"],
      ]} />
      <p>{doc("literature-review.md")}</p>
      <p className="sub">Preuves par type : {Object.entries(p.evidence.by_type).map(([k, v]) => `${k} ${v}`).join(" · ") || "aucune"}</p>
      <CorpusTable project={p} only="included" />
    </>
  ),

  GAP_ANALYSIS: (p) => {
    if (!p.alignment.length) return <Empty>Aucun gap enregistré.</Empty>;
    const gaps = Object.fromEntries(p.gaps.map((g) => [g.gap_id, g]));
    return p.alignment.map((a) => {
      const g = gaps[a.gap_id];
      return (
        <div className="item" key={a.gap_id}>
          <div className="h"><code>{a.gap_id}</code> <Badge>#{a.rank}</Badge>
            <Badge tone={a.status === "supported" ? "ok" : ""}>{a.status}</Badge>
            <Badge>preuves {a.evidence_strength}</Badge> <Badge tone="cur">priorité {a.priority_score}</Badge></div>
          <p><b>{a.title}</b></p>
          {g && <details><summary>détail</summary>
            <p>{g.description}</p><p className="sub">{g.rationale}</p>
            <p className="sub">Nouveauté : {g.novelty_assessment} · publications favorables {g.supporting_papers.length},
              contraires {g.contradicting_papers.length} · recherches contradictoires {g.contradictory_searches.length}</p>
          </details>}
        </div>
      );
    });
  },

  AWAITING_GATE_1: (p) => <GateRounds rounds={p.gate_1} gate="Gate 1" />,

  PROBLEM_FORMULATION: (p) => p.questions.length ? p.questions.map((q) => (
    <div className="item" key={q.question_id}>
      <div className="h"><code>{q.question_id}</code> <Badge>v{q.version}</Badge>
        <Badge tone={q.status === "active" ? "ok" : ""}>{q.status}</Badge> {q.gap_ids.map((g) => <Badge key={g}>{g}</Badge>)}</div>
      <p>{q.question}</p>
      <details><summary>{q.hypotheses.length} hypothèses</summary>
        {q.hypotheses.map((h) => (
          <div className="hyp" key={h.hypothesis_id}>
            <b>{h.hypothesis_id}</b> {h.statement}
            <p className="sub"><b>Prédiction :</b> {h.prediction}</p>
            <p className="sub"><b>Réfutée si :</b> {h.refutation_criterion}</p>
          </div>
        ))}
      </details>
    </div>
  )) : <Empty>Aucune question de recherche.</Empty>,

  SOLUTION_DESIGN: (p) => p.solutions.length ? p.solutions.map((q) => (
    <div className="item" key={q.question_id}>
      <div className="h"><code>{q.question_id}</code> {q.comparison_stale && <Badge tone="bad">comparaison périmée</Badge>}</div>
      {q.solutions.map((s) => (
        <div className="hyp" key={s.solution_id}>
          <div className="h"><code>{s.solution_id}</code> <Badge>v{s.version}</Badge>
            <Badge tone={s.status === "proposed" ? "ok" : ""}>{s.status}</Badge>
            {s.addressed_hypotheses.map((h) => <Badge key={h}>{h}</Badge>)}</div>
          <b>{s.title}</b>
          <details><summary>résumé</summary><p>{s.summary}</p></details>
        </div>
      ))}
      {q.comparison ? <>
        <p><b>Recommandation :</b> {q.comparison.recommendation ?? "aucune"}</p>
        <p className="sub">{q.comparison.justification}</p>
      </> : <Empty>Pas encore de comparaison.</Empty>}
    </div>
  )) : <Empty>Aucune solution.</Empty>,

  SCIENTIFIC_REVIEW: (p) => p.reviews.length ? p.reviews.slice().reverse().map((r, i) => (
    <div className="item" key={r.round}>
      <div className="h"><b>Tour {r.round}</b> <Badge tone={verdictTone(r.verdict)}>{r.verdict}</Badge>
        <Badge>{r.objections.length} objections</Badge> <span className="sub">{fmtDate(r.at)}</span></div>
      {i === 0 ? <p>{r.summary}</p> : <details><summary>synthèse du reviewer</summary><p>{r.summary}</p></details>}
      <details><summary>objections</summary>
        {r.objections.map((o) => (
          <div className="hyp" key={o.objection_id}>
            <div className="h"><code>{o.objection_id}</code> <Badge tone={o.severity === "minor" ? "" : "bad"}>{o.severity}</Badge>
              {o.targets.map((t) => <Badge key={t}>{t}</Badge>)}</div>
            <p>{o.statement}</p>
            {o.response ? <p className="sub"><b>Réponse ({o.response.action}) :</b> {o.response.response}</p>
              : <p className="sub">Sans réponse.</p>}
          </div>
        ))}
      </details>
    </div>
  )) : <Empty>Aucune revue enregistrée.</Empty>,

  PROPOSAL_DRAFT: (p, doc) => p.proposal ? <>
    <p><Badge tone={p.proposal.status === "OK" ? "ok" : "bad"}>proposal check {p.proposal.status}</Badge></p>
    {p.proposal.errors.map((e) => <p key={e} className="sub">✗ {e}</p>)}
    {p.proposal.warnings.map((e) => <p key={e} className="sub">⚠ {e}</p>)}
    <p>{doc("research-proposal.md")}</p>
  </> : <Empty>Proposal pas encore rédigé.</Empty>,

  AWAITING_GATE_2: (p) => <GateRounds rounds={p.gate_2} gate="Gate 2" />,

  COMPLETED: (p) => p.ratings.length ? p.ratings.slice().reverse().map((s) => (
    <div className="item" key={s.session_id}>
      <div className="h"><code>{s.session_id}</code> <Badge>{s.rater}</Badge> <span className="sub">{fmtDate(s.at)}</span></div>
      {s.ratings.map((r) => (
        <p key={r.target}><code>{r.target}</code>{" "}
          {Object.entries(r.scores).map(([k, v]) => <span key={k}>{k} <b>{v}</b> · </span>)}
          {r.comment && <span className="sub">— {r.comment}</span>}</p>
      ))}
    </div>
  )) : <Empty>Pas encore d'évaluation humaine (research-lab eval rate, dans ton terminal).</Empty>,
};
