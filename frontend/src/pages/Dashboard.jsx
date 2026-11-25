import { useCallback, useEffect, useState } from "react";
import { api, describeError } from "../services/api.js";
import { useAuth } from "../services/auth.jsx";
import { Card, ErrorBox, Spinner } from "../components/ui.jsx";

const Stat = ({ label, value, tone }) => (
  <div className={`stat ${tone}`}>
    <span>{label}</span>
    <strong>{value}</strong>
  </div>
);

export default function Dashboard({ go }) {
  const { token } = useAuth();
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!token) return;
    const res = await api.stats(token);
    setLoading(false);
    if (res.ok) { setStats(res.data); setError(null); } else { setStats(null); setError(describeError(res)); }
  }, [token]);

  useEffect(() => {
    setLoading(true);
    load();
    const t = setInterval(load, 3000); // live refresh so PENDING -> COMPLETED is visible
    return () => clearInterval(t);
  }, [load]);

  const b = stats?.risk_buckets || { low: 0, medium: 0, high: 0 };
  const scored = b.low + b.medium + b.high || 1;

  return (
    <>
      <header className="page-head">
        <div><h1>Dashboard</h1><p>Overview of risk evaluations for the selected partner.</p></div>
        <button className="btn primary" onClick={() => go("initiate")}>+ Initiate Risk Score</button>
      </header>
      <ErrorBox>{error}</ErrorBox>
      {loading && !stats && <Spinner />}
      {stats && (
        <>
          <div className="stats-grid">
            <Stat label="Total transactions" value={stats.total} tone="blue" />
            <Stat label="Pending" value={stats.pending} tone="amber" />
            <Stat label="Completed" value={stats.completed} tone="green" />
            <Stat label="Failed" value={stats.failed} tone="red" />
          </div>
          <Card title="Risk score information">
            <div className="risk-info">
              <div className="avg"><span>Average risk score</span><strong>{stats.average_risk_score ?? "—"}</strong></div>
              <div className="buckets">
                {[["Low (1–33)", "low"], ["Medium (34–66)", "medium"], ["High (67–100)", "high"]].map(([label, k]) => (
                  <div key={k} className="bucket">
                    <div className="bucket-head"><span>{label}</span><strong>{b[k]}</strong></div>
                    <div className="bar"><div className={`fill ${k}`} style={{ width: `${(b[k] / scored) * 100}%` }} /></div>
                  </div>
                ))}
              </div>
            </div>
          </Card>
        </>
      )}
    </>
  );
}
