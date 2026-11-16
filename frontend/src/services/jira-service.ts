import { apiClient } from "@/lib/api-client";
import { JiraConnection, JiraProject, JiraSync } from "@/types/jira";

export const jiraService = {
  getConnection: () => apiClient<JiraConnection>("/jira/connection"),
  getProjects: () => apiClient<JiraProject[]>("/jira/projects"),
  saveProjects: (projects: { key: string; name: string; team?: string | null }[]) =>
    apiClient("/jira/projects", { method: "PUT", body: JSON.stringify(projects) }),
  syncNow: () => apiClient<JiraSync>("/jira/sync", { method: "POST" }),
  getSyncs: (limit = 20) => apiClient<JiraSync[]>(`/jira/syncs?limit=${limit}`),
};
