import type { ProjectView } from "../types";
import { label } from "../workflow";

export function NextStep({ project }: { project: ProjectView }) {
  const r = project.resume;
  const blockers = Object.entries(r.next_steps);
  return (
    <div className={`next ${r.waiting_for_human ? "human" : ""}`}>
      <b>{r.waiting_for_human ? "À toi de décider" : "Prochaine étape"} — {r.step}</b>
      {r.action}
      {r.human_instructions && <p className="sub">Dernière décision humaine : {r.human_instructions}</p>}
      {blockers.length > 0 && (
        <ul>
          {blockers.map(([target, problems]) => (
            <li key={target}>{label(target)} : {problems.length ? problems.join(" ; ") : <b>possible</b>}</li>
          ))}
        </ul>
      )}
      {r.stale_exports.length > 0 &&
        <p className="sub">⚠ Exports périmés : {r.stale_exports.join(", ")} (project resume --repair)</p>}
    </div>
  );
}
