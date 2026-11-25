import { useAuth } from "../services/auth.jsx";

const NAV = [
  ["dashboard", "Dashboard", "▦"],
  ["initiate", "Initiate Risk Score", "⚡"],
  ["history", "Transaction History", "☰"],
  ["audit", "Audit Details", "🔍"],
];

export default function Sidebar({ page, go, open }) {
  const { devTokens, selected, setSelected, custom, setCustom, current, loadError } = useAuth();
  return (
    <aside className={`sidebar ${open ? "open" : ""}`}>
      <div className="brand">
        <span className="logo">◈</span>
        <div>
          <strong>RiskScore</strong>
          <small>UIDAI Sandbox</small>
        </div>
      </div>
      <nav>
        {NAV.map(([key, label, icon]) => (
          <button key={key} className={page === key ? "active" : ""} onClick={() => go(key)}>
            <span>{icon}</span> {label}
          </button>
        ))}
      </nav>
      <div className="identity">
        <label htmlFor="identity">Acting as (dev token)</label>
        <select id="identity" value={selected} onChange={(e) => setSelected(e.target.value)}>
          {Object.entries(devTokens).map(([k, v]) => (
            <option key={k} value={k}>{v.label}</option>
          ))}
          <option value="custom">Paste my own token…</option>
        </select>
        {selected === "custom" && (
          <textarea rows={3} placeholder="eyJ…" value={custom} onChange={(e) => setCustom(e.target.value)} />
        )}
        {current?.partner_id && <small>partner_id: <code>{current.partner_id}</code></small>}
        {loadError && <small className="warn">{loadError}</small>}
        <small className="muted">Development tokens only – not production credentials. Test (fake) Aadhaar data only.</small>
      </div>
    </aside>
  );
}
