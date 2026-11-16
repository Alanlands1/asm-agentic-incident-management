import { ApiError } from "@/lib/api-client";
import { AdminChange, AdminDocument, AdminSetting, AdminYaml, Json, SettingValue } from "@/types/admin";

// Goes through the Next.js server route, which adds the admin key.
async function admin<T>(path: string, init?: RequestInit & { by?: string }): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (init?.by) headers["X-Admin-User"] = init.by;
  const res = await fetch(`/api/admin${path}`, { ...init, headers, cache: "no-store" });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      if (body?.detail) message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      // not JSON: keep the status text
    }
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

export const adminService = {
  listSettings: () => admin<AdminSetting[]>("/settings"),
  putSetting: (key: string, value: SettingValue, by: string) =>
    admin<AdminSetting>(`/settings/${key}`, { method: "PUT", body: JSON.stringify({ value }), by }),
  resetSetting: (key: string, by: string) => admin<AdminSetting>(`/settings/${key}`, { method: "DELETE", by }),
  getDocument: (name: string) => admin<AdminDocument>(`/documents/${name}`),
  putDocument: (name: string, document: Json, by: string) =>
    admin<AdminDocument>(`/documents/${name}`, { method: "PUT", body: JSON.stringify({ document }), by }),
  getYaml: (name: string) => admin<AdminYaml>(`/documents/${name}/yaml`),
  putYaml: (name: string, text: string, by: string) =>
    admin<AdminYaml>(`/documents/${name}/yaml`, { method: "PUT", body: JSON.stringify({ text }), by }),
  resetDocument: (name: string, by: string) => admin(`/documents/${name}`, { method: "DELETE", by }),
  listChanges: (limit = 50) => admin<AdminChange[]>(`/changes?limit=${limit}`),
};
