import { useState } from "react";
import type { Paper, ProjectView } from "../types";
import { fmtDate, label, money } from "../workflow";
import { Badge, Empty, Figures, type Tone } from "./ui";

const STATUS_FR: Record<string, string> = { candidate: "à trier", included: "incluse", excluded: "exclue" };
const STATUS_TONE: Record<string, Tone> = { included: "ok", excluded: "bad", candidate: "gate" };

// « §2 — … », ou les formes plus anciennes « §2 exclu : … », « §5 inclusion : … » : le statut est déjà affiché.
const REASON = /^§(\d+)\s*(?:(?:inclu|exclu)\w*\s*)?[—–:-]?\s*/i;

function Reason({ reason, sections }: { reason: string; sections: Record<string, string> }) {
  const match = reason.match(REASON);
  if (!match) return <div className="sub">Motif : {reason}</div>;
  const section = sections[match[1]];
  const rest = reason.slice(match[0].length);
  return (
    <div className="sub reason">
      <span className="badge" title="section de scope.md">§{match[1]}{section ? ` ${section}` : ""}</span>{" "}
      {rest.charAt(0).toUpperCase() + rest.slice(1)}
    </div>
  );
}

export function SearchTable({ project }: { project: ProjectView }) {
  if (!project.search_log.length) return null;
  return (
    <details open>
      <summary>{project.search_log.length} recherches (search-log.json)</summary>
      <div className="tablewrap"><table>
        <thead><tr><th>Id</th><th>Date</th><th>Requête</th><th>Période</th>
          <th>Sources <span className="sub">(examinés / disponibles)</span></th><th>Statut</th><th>Résultat</th></tr></thead>
        <tbody>
          {project.search_log.slice().reverse().map((x) => (
            <tr key={x.id}>
              <td><code>{x.id}</code></td>
              <td className="nowrap">{fmtDate(x.at)}</td>
              <td>{x.query} {x.gap_id && <Badge tone="gate">contradictoire {x.gap_id}</Badge>}</td>
              <td className="nowrap">{x.from ?? "…"} → {x.to ?? "…"}</td>
              <td>{x.sources.map((r) => (
                <div key={r.source} className="nowrap">{r.source} {r.status !== "ok" && <Badge tone="bad">{r.status}</Badge>}{" "}
                  <span className="sub">{r.hits}{r.total != null && ` / ${r.total}`}</span></div>
              ))}</td>
              <td><Badge tone={x.status === "completed" ? "ok" : "bad"}>{x.status}</Badge></td>
              <td className="nowrap"><b>{x.new}</b> <span className="sub">nouvelles</span><br />{x.matched} <span className="sub">déjà connues</span></td>
            </tr>
          ))}
        </tbody>
      </table></div>
    </details>
  );
}

export function CorpusTable({ project, only }: { project: ProjectView; only?: string }) {
  const [status, setStatus] = useState("");
  const [text, setText] = useState("");
  const all = only ? project.papers.all.filter((p) => p.status === only) : project.papers.all;
  if (!all.length) return null;
  const needle = text.trim().toLowerCase();
  const shown = all.filter((p: Paper) =>
    (!status || p.status === status) && (!needle || `${p.id} ${p.title} ${p.venue ?? ""}`.toLowerCase().includes(needle)));
  return (
    <details open={!only}>
      <summary>{all.length} publications {only ? "incluses" : "au corpus (papers.json)"}</summary>
      <div className="filters">
        {!only && (
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">tous les statuts</option>
            {Object.entries(project.papers.by_status).map(([s, n]) => <option key={s} value={s}>{STATUS_FR[s] ?? s} ({n})</option>)}
          </select>
        )}
        <input type="search" placeholder="filtrer : titre, id, revue" value={text} onChange={(e) => setText(e.target.value)} />
        {shown.length !== all.length && <span className="sub">{shown.length} affichées</span>}
      </div>
      <div className="tablewrap"><table>
        <thead><tr><th>Id</th><th>Titre</th><th>Année</th>{!only && <><th>Statut</th><th>Sources</th></>}<th>PDF</th></tr></thead>
        <tbody>
          {shown.map((p) => (
            <tr key={p.id}>
              <td><code>{p.id}</code></td>
              <td>
                {p.url ? <a href={p.url} target="_blank" rel="noopener noreferrer">{p.title}</a> : p.title}
                {p.venue && <div className="sub">{p.venue}</div>}
                {p.reason && !only && <Reason reason={p.reason} sections={project.scope_sections} />}
              </td>
              <td>{p.year}</td>
              {!only && <><td><Badge tone={STATUS_TONE[p.status]}>{STATUS_FR[p.status] ?? p.status}</Badge></td>
                <td className="sub">{p.sources.join(", ")}</td></>}
              <td>{p.pdf && <a href={p.pdf} target="_blank" rel="noopener noreferrer">local</a>}</td>
            </tr>
          ))}
        </tbody>
      </table></div>
    </details>
  );
}

export function HistoryTable({ project }: { project: ProjectView }) {
  return (
    <div className="tablewrap"><table>
      <thead><tr><th>Date</th><th>Transition</th><th>Par</th></tr></thead>
      <tbody>
        {project.history.slice().reverse().map((c, i) => (
          <tr key={i}>
            <td className="nowrap">{fmtDate(c.at)}</td>
            <td>{c.from_state && `${label(c.from_state)} → `}<b>{label(c.to_state)}</b> {c.forced && <Badge tone="bad">forcée</Badge>}</td>
            <td>{c.actor}</td>
          </tr>
        ))}
      </tbody>
    </table></div>
  );
}

export function QualityTable({ project }: { project: ProjectView }) {
  return (
    <div className="tablewrap"><table><tbody>
      {project.quality.map((i) => (
        <tr key={i.control + i.name}>
          <td>{i.ok === true && <Badge tone="ok">ok</Badge>}{i.ok === false && <Badge tone="bad">à voir</Badge>}</td>
          <td className="sub">{i.control}</td><td>{i.name}</td><td><b>{i.value}</b></td>
        </tr>
      ))}
    </tbody></table></div>
  );
}

export function CostsPanel({ project }: { project: ProjectView }) {
  const { costs } = project;
  if (!costs.responses) return <Empty>Aucune consommation enregistrée (research-lab costs sync).</Empty>;
  const rows = (o: Record<string, number>) =>
    Object.entries(o).sort((a, b) => b[1] - a[1]).map(([k, v]) => <tr key={k}><td>{label(k)}</td><td>{money(v)}</td></tr>);
  return (
    <>
      <Figures items={[[money(costs.total), "équivalent API"], [costs.responses, "réponses du modèle"]]} />
      <div className="grid2">
        <table><thead><tr><th>Agent</th><th>Coût</th></tr></thead><tbody>{rows(costs.by_agent)}</tbody></table>
        <table><thead><tr><th>État</th><th>Coût</th></tr></thead><tbody>{rows(costs.by_state)}</tbody></table>
      </div>
    </>
  );
}
