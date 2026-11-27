import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import type { Config } from "../types";
import { BackupButton } from "./actions";
import { ConfigEditor } from "./ConfigEditor";
import { DocumentDialog } from "./DocumentDialog";
import { Badge, Empty } from "./ui";

// Libellés des seuils de config/research-policy.yaml, par étape du workflow.
const POLICY: [string, [keyof Config["policy"], string][]][] = [
  ["Recherche bibliographique", [
    ["min_corpus_size", "Taille minimale du corpus (en dessous : NEEDS_MORE_RESEARCH)"],
    ["max_examinable_results", "Résultats annoncés à examiner tous ; au-delà, requête trop large à affiner"],
    ["allow_partial_search", "Fusion des résultats quand une source échoue (--allow-partial)"],
  ]],
  ["État de l'art", [
    ["min_quote_chars", "Longueur minimale d'un extrait cité comme preuve (lettres et chiffres)"],
    ["require_full_reading", "Texte principal des publications incluses lu en entier avant l'analyse des gaps"],
  ]],
  ["Analyse des gaps", [["min_supporting_papers", "Publications distinctes exigées pour un gap « supported »"]]],
  ["Solutions", [["min_solution_alternatives", "Solutions actives et comparées par question de recherche"]]],
  ["Revue critique", [
    ["min_verified_evidence", "Preuves du raisonnement que le reviewer relit lui-même"],
    ["max_review_rounds", "Tours de revue avant d'en référer à l'humain"],
  ]],
];

const show = (v: unknown) => (typeof v === "boolean" ? (v ? "oui" : "non") : Array.isArray(v) ? v.join(", ") : String(v));

function Section({ title, file, children, onOpen, onEdit }: {
  title: string; file: string; children: ReactNode; onOpen: (f: string) => void; onEdit: (f: string) => void;
}) {
  return (
    <div className="card">
      <h3>{title} <button className="file small" onClick={() => onOpen(file)}>config/{file}</button>
        <button className="act small" onClick={() => onEdit(file)}>Modifier</button></h3>
      {children}
    </div>
  );
}

function Rows({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <div className="tablewrap"><table><tbody>
      {rows.map(([name, value], i) => <tr key={i}><td>{name}</td><td className="num"><b>{value}</b></td></tr>)}
    </tbody></table></div>
  );
}

export function ConfigPage() {
  const [config, setConfig] = useState<Config>();
  const [error, setError] = useState<string>();
  const [file, setFile] = useState<string>();
  const [editing, setEditing] = useState<string>();
  const [saved, setSaved] = useState<string>();
  const load = () => api.config().then(setConfig, (e) => setError(String(e)));
  useEffect(() => { load(); }, []);

  if (error) return <Empty>{error}</Empty>;
  if (!config) return <Empty>Chargement…</Empty>;
  const { policy, values, scoring, sources, costs } = config;
  const totalWeight = Object.values(values.values).reduce((a, v) => a + v.weight, 0);

  return (
    <>
      <div className="phead">
        <h2>Paramètres</h2>
        <div className="meta">Communs à tous les projets, lus dans <code>config/</code>. « Modifier » ouvre un formulaire
          pré-rempli ; le fichier est validé avant d'être écrit, commentaires conservés.</div>
      </div>
      {saved && <div className="next"><b>✓ Enregistré</b>{saved}</div>}
      <div className="next">
        <b>Traçabilité</b>
        Chaque recherche enregistre l'empreinte de la configuration (sources et politique) en vigueur, et chaque évaluation
        sur les valeurs celle des valeurs et des scores. Modifier ces fichiers ne change pas le passé : les évaluations
        faites avec d'anciennes valeurs deviennent périmées et sont à refaire.
        <p className="sub">Configuration actuelle <code>{config.config_hash.slice(7, 19)}</code> · valeurs et scores{" "}
          <code>{config.values_hash.slice(7, 19)}</code></p>
      </div>

      <Section title="Politique de recherche" file="research-policy.yaml" onOpen={setFile} onEdit={setEditing}>
        <p className="sub">Seuils appliqués par le code aux transitions du workflow et aux contrôles.</p>
        {POLICY.map(([step, keys]) => (
          <div key={step} className="item">
            <div className="h"><b>{step}</b></div>
            <Rows rows={keys.map(([key, text]) => [<>{text} <span className="sub">{key}</span></>, show(policy[key])])} />
          </div>
        ))}
      </Section>

      <div className="grid2">
        <Section title="Valeurs du laboratoire" file="research-values.yaml" onOpen={setFile} onEdit={setEditing}>
          <p className="sub">Servent à évaluer et prioriser les gaps, jamais à en créer. Échelle {values.evaluation.scale[0]} à{" "}
            {values.evaluation.scale.at(-1)}{values.evaluation.allow_not_applicable && ", « non applicable » permis"}.</p>
          {Object.entries(values.values).map(([name, v]) => (
            <div key={name} className="item">
              <div className="h"><b>{name}</b> <Badge tone="cur">poids {v.weight}</Badge>
                <span className="sub">{Math.round((100 * v.weight) / totalWeight)} % de l'alignement</span></div>
              <p className="sub">{v.description}</p>
            </div>
          ))}
        </Section>

        <div>
          <Section title="Priorité des gaps" file="scoring.yaml" onOpen={setFile} onEdit={setEditing}>
            <p className="sub">priorité = {Object.entries(scoring.priority.weights).map(([k, w]) => `${w} × ${k}`).join(" + ")}</p>
            <Rows rows={Object.entries(scoring.priority.evidence_strength).map(([k, v]) => [`force des preuves « ${k} »`, v])} />
          </Section>

          <Section title="Évaluation humaine" file="research-policy.yaml" onOpen={setFile} onEdit={setEditing}>
            <p className="sub">Notes de {policy.evaluation.scale[0]} à {policy.evaluation.scale.at(-1)} (`eval rate`) ; objectif du
              MVP : {policy.evaluation.min_rated_topics} sujets évalués.</p>
            <div className="item"><div className="h"><b>Gaps</b></div>
              <Rows rows={Object.entries(policy.evaluation.gap_criteria).map(([k, v]) => [v, <code key={k}>{k}</code>])} /></div>
            <div className="item"><div className="h"><b>Hypothèses</b></div>
              <Rows rows={Object.entries(policy.evaluation.hypothesis_criteria).map(([k, v]) => [v, <code key={k}>{k}</code>])} /></div>
          </Section>
        </div>
      </div>

      <Section title="Sources académiques" file="academic-sources.yaml" onOpen={setFile} onEdit={setEditing}>
        <p className="sub">Par défaut : {sources.default_sources.join(", ")}, {sources.default_max_results} résultats par source.
          Relances : {sources.retry.max_attempts} tentatives, attentes de {sources.retry.delays_seconds.join(", ")} s
          (Retry-After respecté jusqu'à {sources.retry.max_retry_after_seconds} s).</p>
        <div className="tablewrap"><table>
          <thead><tr><th>Source</th><th>Active</th><th>Adresse</th><th>Page</th><th>Intervalle</th><th>Restrictions</th></tr></thead>
          <tbody>
            {Object.entries(sources.providers).map(([name, p]) => (
              <tr key={name}>
                <td><b>{name}</b></td>
                <td>{p.enabled ? <Badge tone="ok">oui</Badge> : <Badge tone="bad">non</Badge>}</td>
                <td className="sub">{p.base_url}</td>
                <td>{p.page_size}</td>
                <td className="nowrap">{p.min_interval_seconds} s</td>
                <td>{p.categories.length > 0 && <div>catégories : {p.categories.join(", ")}</div>}
                  {p.filters.map((f) => <div key={f}><code>{f}</code></div>)}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
        <p className="sub">Texte intégral : PDF de {sources.fulltext.max_pdf_mb} Mo au plus, au moins{" "}
          {sources.fulltext.min_extracted_chars} caractères extraits, {sources.fulltext.max_show_chars} caractères affichés par
          appel de `fulltext show`.</p>
      </Section>

      <Section title="Coûts" file="costs.yaml" onOpen={setFile} onEdit={setEditing}>
        <p className="sub">Prix en dollars par million de jetons (équivalent API). Agents rattachés à un projet :{" "}
          {costs.research_agents.join(", ")}.</p>
        <div className="tablewrap"><table>
          <thead><tr><th>Modèle</th><th>Entrée</th><th>Sortie</th><th>Écriture cache 5 min</th><th>Écriture cache 1 h</th><th>Lecture cache</th></tr></thead>
          <tbody>
            {Object.entries(costs.prices).map(([model, p]) => (
              <tr key={model}><td><code>{model}</code></td><td>{p.input}</td><td>{p.output}</td><td>{p.cache_write_5m}</td>
                <td>{p.cache_write_1h}</td><td>{p.cache_read}</td></tr>
            ))}
          </tbody>
        </table></div>
      </Section>

      <div className="card">
        <h3>Sauvegarde</h3>
        <BackupButton />
      </div>

      {editing && <ConfigEditor key={editing} file={editing} data={config.data[editing]}
        informative={config.informative[editing] ?? {}}
        onSaved={(message) => { setSaved(message); load(); }} onClose={() => setEditing(undefined)} />}
      {file && <DocumentDialog title={`config/${file}`} text={config.files[file] ?? ""} raw onClose={() => setFile(undefined)} />}
    </>
  );
}
