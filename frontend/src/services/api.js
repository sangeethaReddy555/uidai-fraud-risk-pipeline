// Thin fetch wrapper. Every call hits the real FastAPI backend; nothing is mocked.
const BASE = import.meta.env.VITE_API_BASE_URL || "";

export async function request(path, { method = "GET", token, body, headers = {} } = {}) {
  const started = performance.now();
  let res;
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      headers: {
        ...(body ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    return { ok: false, status: 0, ms: 0, data: { detail: "Cannot reach the API. Is the backend running?" } };
  }
  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  return { ok: res.ok, status: res.status, ms: Math.round(performance.now() - started), data };
}

export const api = {
  devTokens: () => request("/api/v1/dev/tokens"),
  stats: (token) => request("/api/v1/risk-score/stats", { token }),
  list: (token, { status, search, limit = 20, offset = 0 } = {}) => {
    const q = new URLSearchParams({ limit, offset });
    if (status) q.set("status", status);
    if (search) q.set("search", search);
    return request(`/api/v1/risk-score/transactions?${q}`, { token });
  },
  initiate: (token, body) => request("/api/v1/risk-score/initiate", { method: "POST", token, body }),
  audit: (token, id) => request(`/api/v1/risk-score/audit/${encodeURIComponent(id)}`, { token }),
};

// Human-friendly explanation for HTTP errors shown in the UI.
export function describeError(res) {
  const d = res.data;
  if (res.status === 0) return d.detail;
  if (res.status === 401) return `401 Unauthorized – ${d?.detail || "token missing or invalid"}`;
  if (res.status === 403) return `403 Forbidden – ${d?.detail || "not permitted"}`;
  if (res.status === 404) return "404 Not found – no such transaction for your partner account.";
  if (res.status === 422 && d?.errors) return `422 Validation failed – ${d.errors.map((e) => `${e.field}: ${e.message}`).join("; ")}`;
  if (res.status === 429) return "429 Too many requests – slow down and retry shortly.";
  return `${res.status} – ${d?.detail || "Request failed"}`;
}
