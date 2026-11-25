import { useEffect, useState } from "react";
import { api, describeError } from "../services/api.js";
import { useAuth } from "../services/auth.jsx";
import { ApiResponse, Card, ErrorBox } from "../components/ui.jsx";

const ID_RE = /^[A-Za-z0-9_-]{3,64}$/;
const SINK = `${window.location.protocol}//${window.location.hostname}:8000/api/v1/dev/callback-sink`;

function validate(f) {
  const e = {};
  if (!ID_RE.test(f.partner_id)) e.partner_id = "3–64 letters, digits, '-' or '_'";
  if (!/^\d{12}$/.test(f.aadhaar_number)) e.aadhaar_number = "Must be exactly 12 digits (use TEST data only)";
  if (!ID_RE.test(f.device_id)) e.device_id = "3–64 letters, digits, '-' or '_'";
  try {
    const u = new URL(f.callback_url);
    if (!["https:", "http:"].includes(u.protocol)) throw new Error();
  } catch { e.callback_url = "Enter a valid URL (https://…)"; }
  return e;
}

export default function Initiate({ go }) {
  const { token, current } = useAuth();
  const [f, setF] = useState({ partner_id: "PARTNER001", aadhaar_number: "123456789012", device_id: "DEVICE001", callback_url: SINK });
  const [simulateOutage, setSimulateOutage] = useState(false);
  const [errors, setErrors] = useState({});
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (current?.partner_id) setF((p) => ({ ...p, partner_id: current.partner_id })); }, [current?.partner_id]);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  async function submit(ev) {
    ev.preventDefault();
    const errs = validate(f);
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true); setRes(null);
    const url = simulateOutage && f.callback_url.includes("callback-sink") && !f.callback_url.includes("fail_first")
      ? `${f.callback_url}?fail_first=2` : f.callback_url;
    const r = await api.initiate(token, {
      partner_id: f.partner_id,
      aadhaar_number: f.aadhaar_number,
      device_data: { device_id: f.device_id },
      callback_url: url,
    });
    setRes(r); setBusy(false);
  }

  const field = (k, label, props = {}) => (
    <label className={errors[k] ? "has-error" : ""}>
      <span>{label}</span>
      <input value={f[k]} onChange={set(k)} {...props} />
      {errors[k] && <em>{errors[k]}</em>}
    </label>
  );

  return (
    <>
      <header className="page-head"><div><h1>Initiate Risk Score</h1><p>Submits to <code>POST /api/v1/risk-score/initiate</code>. Aadhaar is masked before storage.</p></div></header>
      <div className="two-col">
        <Card title="Request">
          <form onSubmit={submit} noValidate>
            {field("partner_id", "Partner ID")}
            {field("aadhaar_number", "Aadhaar number (TEST data)", { inputMode: "numeric", maxLength: 12, autoComplete: "off" })}
            {field("device_id", "Device ID")}
            {field("callback_url", "Callback URL")}
            <label className="check">
              <input type="checkbox" checked={simulateOutage} onChange={(e) => setSimulateOutage(e.target.checked)} />
              <span>Simulate partner outage (dev sink returns 503 twice → shows retry/backoff)</span>
            </label>
            <button className="btn primary" disabled={busy || !token}>{busy ? "Submitting…" : "Submit"}</button>
            {!token && <ErrorBox>No token selected.</ErrorBox>}
          </form>
        </Card>
        <Card title="API response">
          {!res && <p className="muted">Submit the form to see the live API response.</p>}
          {res && res.ok && (
            <div className="alert success">
              Accepted. Transaction <code>{res.data.transaction_id}</code> is <b>{res.data.status}</b>.{" "}
              <button className="link" onClick={() => go("audit", res.data.transaction_id)}>Audit it →</button>
            </div>
          )}
          {res && !res.ok && <ErrorBox>{describeError(res)}</ErrorBox>}
          <ApiResponse res={res} />
        </Card>
      </div>
    </>
  );
}
