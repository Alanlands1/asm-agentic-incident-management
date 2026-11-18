const getApiBase = () => {
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL;
  }
  if (typeof window !== "undefined") {
    // Client-side browser request: use same-origin proxy or default localhost:8000
    return "/api/v1";
  }
  return "http://127.0.0.1:8000/api/v1";
};

// The API's times without a zone are UTC; marked as such here so every page shows them in the viewer's local time.
const ZONELESS = /^\d{4}-\d\d-\d\dT\d\d:\d\d(:\d\d(\.\d+)?)?$/;
const utc = (_key: string, value: unknown) => (typeof value === "string" && ZONELESS.test(value) ? `${value}Z` : value);

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function apiClient<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const base = getApiBase();
  const url = `${base}${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`;
  const res = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers || {}),
    },
    ...options,
  });

  if (!res.ok) {
    let message = res.statusText;
    try {
      const errJson = await res.json();
      if (errJson?.detail) {
        message = typeof errJson.detail === "string" ? errJson.detail : JSON.stringify(errJson.detail);
      }
    } catch {
      // ignore
    }
    throw new ApiError(res.status, message || `HTTP request failed: ${res.status}`);
  }

  return JSON.parse(await res.text(), utc);
}
