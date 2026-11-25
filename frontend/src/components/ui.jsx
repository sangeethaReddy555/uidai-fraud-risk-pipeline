import { useState } from "react";

export const Card = ({ title, children, className = "" }) => (
  <section className={`card ${className}`}>
    {title && <h3>{title}</h3>}
    {children}
  </section>
);

export const StatusBadge = ({ status }) => <span className={`badge ${String(status).toLowerCase()}`}>{status}</span>;

export const Spinner = ({ label = "Loading…" }) => (
  <div className="spinner-wrap" role="status"><span className="spinner" /> {label}</div>
);

export const ErrorBox = ({ children }) => (children ? <div className="alert error" role="alert">{children}</div> : null);

export function ApiResponse({ res }) {
  if (!res) return null;
  return (
    <div className="api-response">
      <div className="api-meta">
        <span className={`http ${res.ok ? "ok" : "bad"}`}>HTTP {res.status || "ERR"}</span>
        <span>{res.ms} ms</span>
      </div>
      <pre>{JSON.stringify(res.data, null, 2)}</pre>
    </div>
  );
}

export function RiskScore({ value }) {
  if (value == null) return <span className="muted">—</span>;
  const level = value >= 67 ? "high" : value >= 34 ? "medium" : "low";
  return <span className={`score ${level}`}>{value}</span>;
}

export const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString() : "—");

export function useLoader() {
  const [state, setState] = useState({ loading: false, error: null });
  return [state, setState];
}
