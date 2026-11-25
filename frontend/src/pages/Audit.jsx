import { useEffect, useState } from "react";
import { api, describeError } from "../services/api.js";
import { useAuth } from "../services/auth.jsx";
import { ApiResponse, Card, ErrorBox, RiskScore, Spinner, StatusBadge, fmtDate } from "../components/ui.jsx";

export default function Audit({ initialId }) {
  const { token } = useAuth();
  const [id, setId] = useState(initialId || "");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState(null);

  async function fetchAudit(value = id) {
    const v = value.trim();
    if (!/^[A-Za-z0-9_-]{6,40}$/.test(v)) { setFormError("Enter a valid transaction ID (6–40 letters/digits)."); return; }
    setFormError(null); setBusy(true);
    setRes(await api.audit(token, v));
    setBusy(false);
  }

  useEffect(() => { if (initialId) { setId(initialId); fetchAudit(initialId); } }, [initialId]); // eslint-disable-line

  const d = res?.ok ? res.data : null;
  return (
    <>
      <header className="page-head"><div><h1>Audit Details</h1><p>Calls <code>GET /api/v1/risk-score/audit/{"{transaction_id}"}</code>. Ownership is enforced server-side.</p></div></header>
      <Card>
        <form className="search" onSubmit={(e) => { e.preventDefault(); fetchAudit(); }}>
          <input placeholder="Transaction ID, e.g. TXN3F9A…" value={id} onChange={(e) => setId(e.target.value)} />
          <button className="btn primary" disabled={busy || !token}>Fetch audit</button>
        </form>
        <ErrorBox>{formError}</ErrorBox>
      </Card>
      {busy && <Spinner />}
      {res && !res.ok && <ErrorBox>{describeError(res)}</ErrorBox>}
      <div className="two-col">
        {d && (
          <Card title="Transaction">
            <dl className="details">
              <dt>Transaction ID</dt><dd><code>{d.transaction_id}</code></dd>
              <dt>Partner</dt><dd>{d.partner_id}</dd>
              <dt>Status</dt><dd><StatusBadge status={d.status} /></dd>
              <dt>Risk score</dt><dd><RiskScore value={d.risk_score} /></dd>
              <dt>Created</dt><dd>{fmtDate(d.created_at)}</dd>
              <dt>Updated</dt><dd>{fmtDate(d.updated_at)}</dd>
            </dl>
          </Card>
        )}
        {res && <Card title="API response"><ApiResponse res={res} /></Card>}
      </div>
    </>
  );
}
