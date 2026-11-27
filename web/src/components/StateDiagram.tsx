import type { KeyboardEvent } from "react";
import type { ProjectView, State } from "../types";
import { GATES, STATES } from "../workflow";

// Disposition en serpent : NEW → … → Gate 1 sur la première ligne, puis retour de droite à gauche.
const W = 168, H = 66;
const X = (col: number) => 110 + col * 196;
const Y = (row: number) => (row === 0 ? 110 : 330);
const POS: Record<State, [number, number]> = {
  NEW: [0, 0], SCOPING: [1, 0], LITERATURE_SEARCH: [2, 0], LITERATURE_REVIEW: [3, 0], GAP_ANALYSIS: [4, 0],
  AWAITING_GATE_1: [5, 0], PROBLEM_FORMULATION: [5, 1], SOLUTION_DESIGN: [4, 1], SCIENTIFIC_REVIEW: [3, 1],
  PROPOSAL_DRAFT: [2, 1], AWAITING_GATE_2: [1, 1], COMPLETED: [0, 1],
};
// Retours en arrière autorisés par le workflow : [depuis, vers, libellé, côté, profondeur de la courbe].
const LOOPS: [State, State, string, "top" | "bottom", number][] = [
  ["AWAITING_GATE_1", "LITERATURE_SEARCH", "révision (Gate 1)", "top", 70],
  ["SCIENTIFIC_REVIEW", "SOLUTION_DESIGN", "verdict défavorable", "bottom", 56],
  ["AWAITING_GATE_2", "SOLUTION_DESIGN", "révision (Gate 2)", "bottom", 104],
];

interface Props { project: ProjectView; states: State[]; selected: State; onSelect: (s: State) => void }

export function StateDiagram({ project, states, selected, onSelect }: Props) {
  // Vert : les états qui précèdent l'état actuel ; un retour en arrière forcé efface ce qui suivait.
  const rank = states.indexOf(project.state);
  const used: Record<string, number> = {};
  for (const c of project.history) if (c.from_state) used[`${c.from_state}>${c.to_state}`] = (used[`${c.from_state}>${c.to_state}`] ?? 0) + 1;

  const forward = states.slice(0, -1).map((a, i) => {
    const b = states[i + 1], [ca, ra] = POS[a], [cb, rb] = POS[b];
    const d = ra !== rb
      ? `M${X(ca)},${Y(ra) + H / 2} L${X(cb)},${Y(rb) - H / 2 - 6}`
      : cb > ca
        ? `M${X(ca) + W / 2},${Y(ra)} L${X(cb) - W / 2 - 6},${Y(rb)}`
        : `M${X(ca) - W / 2},${Y(ra)} L${X(cb) + W / 2 + 6},${Y(rb)}`;
    const n = states.indexOf(b) <= rank;
    return <path key={a} className={`edge ${n ? "used" : ""}`} d={d} markerEnd={`url(#${n ? "au" : "a"})`} />;
  });

  const loops = LOOPS.map(([a, b, text, side, depth]) => {
    const [ca, ra] = POS[a], [cb] = POS[b], s = side === "top" ? -1 : 1;
    const y0 = Y(ra) + (s * H) / 2, y1 = y0 + s * depth, ye = y0 + s * 6;
    const n = used[`${a}>${b}`];
    return (
      <g key={a + b}>
        <path className={`edge loop ${n ? "used" : ""}`} d={`M${X(ca)},${y0} C${X(ca)},${y1} ${X(cb)},${y1} ${X(cb)},${ye}`}
          markerEnd={`url(#${n ? "au" : "a"})`} />
        <text className="elabel" x={(X(ca) + X(cb)) / 2} y={y0 + s * depth * 0.75 + (s > 0 ? 14 : -4)} textAnchor="middle">
          {text}{n ? ` · ${n}×` : ""}
        </text>
      </g>
    );
  });

  const nodes = states.map((s) => {
    const [c, r] = POS[s], visits = project.visits[s] ?? 0, gate = GATES.has(s);
    const cls = ["node", gate && "gate", states.indexOf(s) < rank && "visited", s === project.state && "current", s === selected && "sel"]
      .filter(Boolean).join(" ");
    const onKey = (e: KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(s); } };
    return (
      <g key={s} className={cls} onClick={() => onSelect(s)} onKeyDown={onKey} tabIndex={0} role="button" aria-label={STATES[s].label}>
        <rect x={X(c) - W / 2} y={Y(r) - H / 2} width={W} height={H} rx={gate ? 22 : 10} />
        <text x={X(c)} y={Y(r) - 3} textAnchor="middle">{STATES[s].label}</text>
        <text className="code" x={X(c)} y={Y(r) + 16} textAnchor="middle">{gate ? "décision humaine" : s}</text>
        {visits > 1 && <text className="visits" x={X(c) + W / 2 - 8} y={Y(r) - H / 2 + 15} textAnchor="end">{visits}×</text>}
      </g>
    );
  });

  return (
    <div className="svgwrap">
      <svg viewBox="0 0 1220 480" role="img" aria-label="Diagramme d'état du projet">
        <defs>
          {[["a", "var(--pending)"], ["au", "var(--done)"]].map(([id, fill]) => (
            <marker key={id} id={id} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill={fill} />
            </marker>
          ))}
        </defs>
        {forward}{loops}{nodes}
      </svg>
    </div>
  );
}
