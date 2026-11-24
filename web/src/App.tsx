import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { DocumentDialog } from "./components/DocumentDialog";
import { NextStep } from "./components/NextStep";
import { ProjectList } from "./components/ProjectList";
import { StateDetail } from "./components/StateDetail";
import { StateDiagram } from "./components/StateDiagram";
import { CostsPanel, HistoryTable, QualityTable } from "./components/tables";
import type { ProjectSummary, ProjectView, State, Workflow } from "./types";
import { STATES, fmtDate } from "./workflow";

// Adresse : #/<projet>/<état sélectionné>
function readHash(): { id?: string; state?: State } {
  const [id, state] = decodeURIComponent(location.hash.replace(/^#\/?/, "")).split("/");
  return { id: id || undefined, state: state in STATES ? (state as State) : undefined };
}

export function App() {
  const [workflow, setWorkflow] = useState<Workflow>();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<ProjectView>();
  const [selected, setSelected] = useState(readHash);
  const [document, setDocument] = useState<{ name: string; text: string | null }>();
  const [updatedAt, setUpdatedAt] = useState<Date>();
  const [error, setError] = useState<string>();

  const projectId = selected.id ?? projects[0]?.id;
  const state = selected.state ?? project?.state;

  // Données lues dans la base à l'ouverture de la page et à chaque changement de projet.
  const load = useCallback(async () => {
    try {
      const [wf, list] = await Promise.all([workflow ? Promise.resolve(workflow) : api.workflow(), api.projects()]);
      setWorkflow(wf);
      setProjects(list);
      const id = projectId ?? list[0]?.id;
      setProject(id ? await api.project(id) : undefined);
      setUpdatedAt(new Date());
      setError(undefined);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [projectId, workflow]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (projectId) history.replaceState(null, "", `#/${projectId}/${state ?? ""}`);
  }, [projectId, state]);

  const openDocument = async (name: string) => {
    if (!project) return;
    setDocument({ name, text: null });
    setDocument({ name, text: await api.document(project.id, name) });
  };

  return (
    <>
      <header className="top">
        <h1>Laboratoire doctorant</h1>
        <span className="gen">
          {error ? <span className="err">Serveur injoignable : {error}</span>
            : updatedAt && `données du ${updatedAt.toLocaleTimeString("fr-FR")} · recharger la page pour actualiser`}
        </span>
      </header>
      <div className="layout">
        <aside>
          <h2>Projets</h2>
          {workflow && <ProjectList projects={projects} states={workflow.states} selected={projectId}
            onSelect={(id) => { setSelected({ id }); setProject(undefined); }} />}
        </aside>
        <main>
          {!project || !workflow || !state ? <p className="empty">{error ? "" : "Chargement…"}</p> : (
            <>
              <div className="phead">
                <h2>{project.topic}</h2>
                <div className="meta"><code>{project.id}</code> · {STATES[project.state].label} depuis le{" "}
                  {fmtDate(project.history.at(-1)?.at)} · créé le {fmtDate(project.created_at)}</div>
              </div>
              <NextStep project={project} />
              <div className="card diagram">
                <h3>Diagramme d'état <span className="sub">— cliquer sur un état pour voir ses livrables</span></h3>
                <StateDiagram project={project} states={workflow.states} selected={state}
                  onSelect={(s) => setSelected({ id: project.id, state: s })} />
                <div className="legend">
                  <span className="l-cur">état actuel</span><span className="l-done">franchi</span>
                  <span className="l-gate">gate franchie</span><span>à venir</span>
                  <span>N× : nombre de passages · pointillés : retours en arrière</span>
                </div>
              </div>
              <StateDetail project={project} workflow={workflow} state={state} onOpenDocument={openDocument} />
              <div className="grid2">
                <div className="card"><h3>Historique</h3><HistoryTable project={project} /></div>
                <div>
                  <div className="card"><h3>Qualité (indicateurs calculés)</h3><QualityTable project={project} /></div>
                  <div className="card"><h3>Coûts</h3><CostsPanel project={project} /></div>
                </div>
              </div>
            </>
          )}
        </main>
      </div>
      {document && project && <DocumentDialog title={`${project.id} / ${document.name}`} text={document.text}
        onClose={() => setDocument(undefined)} />}
    </>
  );
}
