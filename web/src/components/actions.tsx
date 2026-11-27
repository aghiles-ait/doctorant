import { useEffect, useRef, useState, type ButtonHTMLAttributes, type FormEvent, type ReactNode } from "react";
import { api, type FulltextResult, type SearchResult } from "../api";
import type { Config, ProjectView, State } from "../types";
import { GATES, PRODUCES, STATES, label } from "../workflow";
import { Badge } from "./ui";

// Écritures dans la base depuis l'interface : les mêmes opérations que la CLI, refusées par le serveur dans les
// mêmes cas. Les décisions humaines (gates, eval rate) n'y figurent pas : elles restent dans le terminal.

function useAction<A extends unknown[], T>(run: (...args: A) => Promise<T>, onDone?: (result: T) => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [result, setResult] = useState<T>();
  const go = async (...args: A) => {
    setBusy(true);
    setError(undefined);
    try {
      const r = await run(...args);
      setResult(r);
      onDone?.(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return { go, busy, error, result };
}

const Failure = ({ error }: { error?: string }) => (error ? <p className="err-msg">✗ {error}</p> : null);

function Button({ busy, children, ...props }: { busy?: boolean } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button className="act" {...props} disabled={busy || props.disabled}>{busy ? "En cours…" : children}</button>;
}

// --- projet ------------------------------------------------------------------

export function NewProjectDialog({ onCreated, onClose }: { onCreated: (id: string) => void; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [id, setId] = useState("");
  const [topic, setTopic] = useState("");
  const create = useAction(api.createProject, (p) => { onCreated(p.id); ref.current?.close(); });
  useEffect(() => { ref.current?.showModal(); }, []);
  const submit = (e: FormEvent) => { e.preventDefault(); create.go(id.trim(), topic.trim()); };
  return (
    <dialog ref={ref} onClose={onClose} className="small">
      <div className="dh"><b>Nouveau projet</b><button onClick={() => ref.current?.close()}>Fermer</button></div>
      <form className="form" onSubmit={submit}>
        <label>Identifiant
          <input value={id} onChange={(e) => setId(e.target.value)} required pattern="[a-z0-9][a-z0-9\-]*"
            placeholder="ex. federated-learning-privacy" autoFocus />
          <span className="sub">Minuscules, chiffres et tirets ; il ne changera plus.</span>
        </label>
        <label>Sujet de recherche
          <textarea value={topic} onChange={(e) => setTopic(e.target.value)} required rows={3} />
        </label>
        <p className="sub">Le projet est créé à l'état Nouveau. La suite (périmètre, recherche…) revient à l'agent doctorant.</p>
        <Failure error={create.error} />
        <Button busy={create.busy} type="submit">Créer le projet</Button>
      </form>
    </dialog>
  );
}

export function DeleteProjectDialog({ project, onDeleted, onClose }: { project: ProjectView; onDeleted: () => void; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [typed, setTyped] = useState("");
  const remove = useAction(() => api.deleteProject(project.id), () => { ref.current?.close(); onDeleted(); });
  useEffect(() => { ref.current?.showModal(); }, []);
  const submit = (e: FormEvent) => { e.preventDefault(); remove.go(); };
  return (
    <dialog ref={ref} onClose={onClose} className="small">
      <div className="dh"><b>Supprimer le projet</b><button onClick={() => ref.current?.close()}>Fermer</button></div>
      <form className="form" onSubmit={submit}>
        <p>Suppression <b>définitive</b> de <code>{project.id}</code> : historique, tri, preuves, gaps, décisions aux
          gates, questions, solutions, revues et le dossier du projet. Les publications utilisées par un autre projet
          sont conservées ; aucun identifiant ne sera réattribué.</p>
        <p className="sub">Pour garder une copie : Paramètres → Sauvegarder le laboratoire, avant de supprimer.</p>
        <label>Retaper l'identifiant pour confirmer
          <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={project.id} autoFocus /></label>
        <Failure error={remove.error} />
        <Button busy={remove.busy} type="submit" disabled={typed !== project.id} className="act danger">
          Supprimer définitivement</Button>
      </form>
    </dialog>
  );
}

// --- transitions -------------------------------------------------------------

export function Transitions({ project, onChanged }: { project: ProjectView; onChanged: () => void }) {
  const move = useAction((target: string, force: boolean) => api.transition(project.id, target, force), onChanged);
  const [target, setTarget] = useState<State | "">("");
  const fromGate = GATES.has(project.state);
  const forceable = (Object.keys(STATES) as State[])
    .filter((s) => s !== project.state && !GATES.has(s) && s !== "COMPLETED");
  const states = Object.keys(STATES) as State[];
  const force = () => {
    if (!target) return;
    const back = states.indexOf(target) < states.indexOf(project.state);
    const erased = states.slice(states.indexOf(target) + 1).filter((s) => PRODUCES[s])
      .map((s) => `• ${label(s)} : ${PRODUCES[s]}`);
    const ok = confirm(back
      ? `Revenir à « ${label(target)} » ?\n\nSuppression DÉFINITIVE de tout ce qu'ont produit les états suivants, `
        + `et de leurs passages dans l'historique :\n${erased.join("\n")}\n\nLes identifiants supprimés ne seront pas réattribués.`
      : `Forcer le passage de « ${label(project.state)} » à « ${label(target)} », sans contrôle des préconditions ?\n\n`
        + "La transition est tracée comme forcée dans l'historique.");
    if (ok) move.go(target, true);
  };
  const next = Object.entries(project.resume.next_steps).filter(([t]) => !GATES.has(t as State) && !fromGate);
  return (
    <div className="actions">
      {next.map(([t, problems]) => (
        <Button key={t} busy={move.busy} disabled={problems.length > 0} title={problems.join(" ; ")}
          onClick={() => move.go(t, false)}>Passer à « {label(t)} »</Button>
      ))}
      <details>
        <summary>Revenir à un état antérieur ou forcer une transition</summary>
        {fromGate ? <p className="sub">Impossible depuis une gate : la décision est humaine, dans le terminal
          (research-lab gate approve / revise).</p> : (
          <div className="filters">
            <select value={target} onChange={(e) => setTarget(e.target.value as State)}>
              <option value="">État cible…</option>
              {forceable.map((s) => <option key={s} value={s}>{STATES[s].label} ({s})</option>)}
            </select>
            <Button busy={move.busy} disabled={!target} onClick={force}>Forcer</Button>
            <span className="sub">Les gates et « Terminé » ne s'atteignent jamais ainsi.</span>
          </div>
        )}
      </details>
      <Failure error={move.error} />
    </div>
  );
}

export function RepairButton({ project, onChanged }: { project: ProjectView; onChanged: () => void }) {
  const repair = useAction(() => api.repair(project.id), onChanged);
  return <><Button busy={repair.busy} onClick={() => repair.go()}>Régénérer les exports</Button><Failure error={repair.error} /></>;
}

// --- périmètre -------------------------------------------------------------------

export function ScopeUpload({ project, onChanged }: { project: ProjectView; onChanged: () => void }) {
  const upload = useAction((text: string) => api.uploadScope(project.id, text), onChanged);
  const exists = project.documents.includes("scope.md");
  const pick = async (file?: File) => { if (file) upload.go(await file.text()); };
  return (
    <Action note={"Fichier Markdown avec des sections numérotées (« ## 1. Question », « ## 2. Périmètre »…) : "
      + "les raisons de tri les citeront (« §2 — … »)."}>
      <label className="act">
        {upload.busy ? "Envoi…" : exists ? "Remplacer scope.md" : "Déposer un scope.md"}
        <input type="file" accept=".md,text/markdown,text/plain" hidden
          onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
      </label>
      {upload.result && <span className="sub">✓ sections : {Object.entries(upload.result.sections)
        .map(([n, t]) => `§${n} ${t}`).join(", ")}</span>}
      <Failure error={upload.error} />
    </Action>
  );
}

// --- recherche bibliographique -------------------------------------------------

export function SearchForm({ project, onChanged, forGap = false }: { project: ProjectView; onChanged: () => void; forGap?: boolean }) {
  const [config, setConfig] = useState<Config>();
  useEffect(() => { api.config().then(setConfig, () => undefined); }, []);
  const last = project.search_log.filter((s) => !s.gap_id).at(-1);
  const gaps = project.gaps.filter((g) => g.status === "candidate" || g.status === "supported");
  const [query, setQuery] = useState("");
  const [from, setFrom] = useState(last?.from ?? "");
  const [to, setTo] = useState(last?.to ?? "");
  const [gap, setGap] = useState(gaps[0]?.gap_id ?? "");
  const [sources, setSources] = useState<string[]>();
  const [max, setMax] = useState("");
  const search = useAction(api.search, onChanged);
  const providers = config ? Object.entries(config.sources.providers).filter(([, p]) => p.enabled).map(([n]) => n) : [];
  const chosen = sources ?? config?.sources.default_sources ?? [];
  const toggle = (s: string) => setSources(chosen.includes(s) ? chosen.filter((x) => x !== s) : [...chosen, s]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    search.go(project.id, {
      query: query.trim(), date_from: from || undefined, date_to: to || undefined, sources: chosen,
      max_results: max ? Number(max) : undefined, gap_id: forGap ? gap : undefined,
    });
  };
  if (forGap && !gaps.length) return null;
  return (
    <form className="form panel" onSubmit={submit}>
      <b>{forGap ? "Recherche contradictoire" : "Nouvelle requête"}</b>
      <p className="sub">{forGap ? "Chercher des travaux qui combleraient déjà un gap ; les nouvelles publications restent à trier."
        : "Une requête de quelques mots-clés, \"expression exacte\" entre guillemets. Elle est journalisée (SEARCH-xxx) ; "
          + "les nouvelles publications arrivent au statut « à trier »."}</p>
      {forGap && <label>Gap
        <select value={gap} onChange={(e) => setGap(e.target.value)}>
          {gaps.map((g) => <option key={g.gap_id} value={g.gap_id}>{g.gap_id} — {g.title}</option>)}
        </select></label>}
      <label>Requête<input value={query} onChange={(e) => setQuery(e.target.value)} required
        placeholder='ex. "decentralized autonomous organization" governance' /></label>
      <div className="row">
        <label>Du<input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label>Au<input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
        <label>Résultats max. par source<input type="number" min={1} value={max} onChange={(e) => setMax(e.target.value)}
          placeholder={String(config?.sources.default_max_results ?? "")} /></label>
      </div>
      <div className="row">
        {providers.map((s) => (
          <label key={s} className="check"><input type="checkbox" checked={chosen.includes(s)} onChange={() => toggle(s)} /> {s}</label>
        ))}
      </div>
      <Failure error={search.error} />
      {search.result && <SearchOutcome result={search.result} />}
      <Button busy={search.busy} type="submit" disabled={!chosen.length}>Lancer la recherche</Button>
    </form>
  );
}

function SearchOutcome({ result }: { result: SearchResult }) {
  return (
    <div className="outcome">
      <b>{result.search_id}</b> <Badge tone={result.status === "completed" ? "ok" : "bad"}>{result.status}</Badge>{" "}
      {result.new_paper_ids.length} nouvelles publications, {result.matched_paper_ids.length} déjà connues
      {result.results.map((r) => (
        <div key={r.source} className="sub">{r.source} : {r.status === "ok"
          ? `${r.hits} résultats sur ${r.total_available ?? "?"} disponibles` : `erreur — ${r.error}`}</div>
      ))}
      {result.status === "failed" && <div className="sub">Corpus inchangé : relancer la même requête.</div>}
    </div>
  );
}

// --- texte intégral, coûts, sauvegarde --------------------------------------------

export function FulltextButton({ project, onChanged }: { project: ProjectView; onChanged: () => void }) {
  const fetchAll = useAction(() => api.fetchFulltext(project.id), onChanged);
  const counts = (rows: FulltextResult[]) => Object.entries(
    rows.reduce<Record<string, number>>((acc, r) => ({ ...acc, [r.status]: (acc[r.status] ?? 0) + 1 }), {}),
  ).map(([s, n]) => `${n} ${s}`).join(", ");
  return (
    <Action note="Télécharge le PDF en accès libre des publications incluses qui ne l'ont pas encore ; peut prendre plusieurs minutes.">
      <Button busy={fetchAll.busy} onClick={() => fetchAll.go()}>Récupérer les textes intégraux</Button>
      {fetchAll.result && <span className="sub">{counts(fetchAll.result) || "aucune publication incluse"}</span>}
      <Failure error={fetchAll.error} />
    </Action>
  );
}

export function SyncCostsButton({ onChanged }: { onChanged: () => void }) {
  const sync = useAction(api.syncCosts, onChanged);
  return <Button busy={sync.busy} onClick={() => sync.go()} className="act small">Synchroniser</Button>;
}

export function BackupButton() {
  const backup = useAction(api.backup);
  return (
    <Action note="Copie cohérente de la base, des textes intégraux et des dossiers des projets dans backups/<date>/.">
      <Button busy={backup.busy} onClick={() => backup.go()}>Sauvegarder le laboratoire</Button>
      {backup.result && <span className="sub">✓ {backup.result.path} (schéma v{backup.result.schema_version})</span>}
      <Failure error={backup.error} />
    </Action>
  );
}

function Action({ note, children }: { note: string; children: ReactNode }) {
  return <div className="actions"><div className="row">{children}</div><p className="sub">{note}</p></div>;
}
