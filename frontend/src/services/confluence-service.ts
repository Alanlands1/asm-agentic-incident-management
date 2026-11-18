import { apiClient } from "@/lib/api-client";
import { ConfluenceConnection, ConfluencePage, ConfluencePageDetail, ConfluenceSpace, ConfluenceSync } from "@/types/confluence";

export const confluenceService = {
  getConnection: () => apiClient<ConfluenceConnection>("/confluence/connection"),
  getSpaces: () => apiClient<ConfluenceSpace[]>("/confluence/spaces"),
  saveSpaces: (spaces: { key: string; id: string; name: string }[]) =>
    apiClient("/confluence/spaces", { method: "PUT", body: JSON.stringify(spaces) }),
  syncNow: () => apiClient<ConfluenceSync>("/confluence/sync", { method: "POST" }),
  getSyncs: (limit = 20) => apiClient<ConfluenceSync[]>(`/confluence/syncs?limit=${limit}`),
  getPages: () => apiClient<ConfluencePage[]>("/confluence/pages"),
  getPage: (id: string) => apiClient<ConfluencePageDetail>(`/confluence/pages/${encodeURIComponent(id)}`),
};
