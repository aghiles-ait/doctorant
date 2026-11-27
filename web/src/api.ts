import type { Config, ProjectSummary, ProjectView, Workflow } from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const text = await response.text();
    let detail = text;
    try { detail = JSON.parse(text).detail ?? text; } catch { /* texte brut */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return response.headers.get("content-type")?.includes("json") ? response.json() : (response.text() as Promise<T>);
}

const get = <T>(url: string) => request<T>(url);
const post = <T>(url: string, body?: unknown) =>
  request<T>(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body ?? {}) });
const project = (id: string) => `/api/projects/${encodeURIComponent(id)}`;

export interface SearchBody {
  query: string; date_from?: string; date_to?: string; sources?: string[]; max_results?: number; gap_id?: string;
}

export interface SearchResult {
  search_id: string; status: string; gap_id: string | null; new_paper_ids: string[]; matched_paper_ids: string[];
  results: { source: string; status: string; hits: number; total_available: number | null; error: string | null }[];
}

export interface FulltextResult { paper_id: string; status: string; page_count: number | null; error: string | null }

export const api = {
  workflow: () => get<Workflow>("/api/workflow"),
  config: () => get<Config>("/api/config"),
  projects: () => get<ProjectSummary[]>("/api/projects"),
  project: (id: string) => get<ProjectView>(project(id)),
  document: (id: string, name: string) => get<string>(`${project(id)}/documents/${encodeURIComponent(name)}`),

  // Écritures : mêmes opérations et mêmes contrôles que la CLI.
  updateConfig: (name: string, data: Record<string, unknown>) =>
    request<{ values_changed: boolean; config_changed: boolean }>(`/api/config/${encodeURIComponent(name)}`, {
      method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ data }),
    }),
  createProject: (project_id: string, topic: string) => post<ProjectSummary>("/api/projects", { project_id, topic }),
  uploadScope: (id: string, text: string) =>
    request<{ sections: Record<string, string> }>(`${project(id)}/documents/scope.md`, {
      method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ text }),
    }),
  deleteProject: (id: string) =>
    post<{ papers: number; papers_kept: number }>(`${project(id)}/delete`, { confirm: id }),
  transition: (id: string, target: string, force = false) => post<{ state: string }>(`${project(id)}/transition`, { target, force }),
  search: (id: string, body: SearchBody) => post<SearchResult>(`${project(id)}/search`, body),
  fetchFulltext: (id: string) => post<FulltextResult[]>(`${project(id)}/fulltext`),
  repair: (id: string) => post<{ stale_exports: string[] }>(`${project(id)}/repair`),
  syncCosts: () => post<{ responses: number }>("/api/costs/sync"),
  backup: () => post<{ path: string; schema_version: number }>("/api/backup"),
};
