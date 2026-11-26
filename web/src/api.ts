import type { Config, ProjectSummary, ProjectView, Workflow } from "./types";

async function get<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} : ${response.status} ${await response.text()}`);
  return response.headers.get("content-type")?.includes("json") ? response.json() : (response.text() as Promise<T>);
}

export const api = {
  workflow: () => get<Workflow>("/api/workflow"),
  config: () => get<Config>("/api/config"),
  projects: () => get<ProjectSummary[]>("/api/projects"),
  project: (id: string) => get<ProjectView>(`/api/projects/${encodeURIComponent(id)}`),
  document: (id: string, name: string) =>
    get<string>(`/api/projects/${encodeURIComponent(id)}/documents/${encodeURIComponent(name)}`),
};
