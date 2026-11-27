import { useState } from "react";
import type { ProjectSummary, State } from "../types";
import { STATES } from "../workflow";
import { NewProjectDialog } from "./actions";
import { Badge } from "./ui";

interface Props { projects: ProjectSummary[]; states: State[]; selected?: string; onSelect: (id: string) => void }

export function ProjectList({ projects, states, selected, onSelect }: Props) {
  const [creating, setCreating] = useState(false);
  return (
    <>
      <button className="act wide" onClick={() => setCreating(true)}>+ Nouveau projet</button>
      {!projects.length && <p className="empty">Aucun projet dans la base.</p>}
      {projects.map((p) => (
        <button key={p.id} className={`pcard ${p.id === selected ? "sel" : ""}`} onClick={() => onSelect(p.id)}>
          <div className="t">{p.topic}</div>
          <div className="id">{p.id}</div>
          <div className="bar"><i style={{ width: `${(100 * states.indexOf(p.state)) / (states.length - 1)}%` }} /></div>
          <Badge tone={p.state === "COMPLETED" ? "ok" : "cur"}>{STATES[p.state].label}</Badge>{" "}
          {p.waiting_for_human && <Badge tone="gate">à toi de décider</Badge>}
        </button>
      ))}
      {creating && <NewProjectDialog onCreated={onSelect} onClose={() => setCreating(false)} />}
    </>
  );
}
