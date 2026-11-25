import { useCallback, useEffect, useState } from "react";
import { api, describeError } from "../services/api.js";
import { useAuth } from "../services/auth.jsx";
import { Card, ErrorBox, RiskScore, Spinner, StatusBadge, fmtDate } from "../components/ui.jsx";

const PAGE = 10;

export default function History({ go }) {
  const { token } = useAuth();
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!token) return;
    const res = await api.list(token, { status, search: query, limit: PAGE, offset });
    setLoading(false);
    if (res.ok) { setData(res.data); setError(null); } else { setData(null); setError(describeError(res)); }
  }, [token, status, query, offset]);

  useEffect(() => { setLoading(true); load(); const t = setInterval(load, 4000); return () => clearInterval(t); }, [load]);

  const onSearch = (e) => { e.preventDefault(); setOffset(0); setQuery(search.trim()); };

  return (
    <>
      <header className="page-head"><div><h1>Transaction History</h1><p>Only transactions owned by the selected partner are listed.</p></div></header>
      <Card>
        <div className="toolbar">
          <form onSubmit={onSearch} className="search">
            <input placeholder="Search by transaction ID…" value={search} onChange={(e) => setSearch(e.target.value)} pattern="[A-Za-z0-9_-]*" maxLength={40} />
            <button className="btn">Search</button>
          </form>
          <select value={status} onChange={(e) => { setOffset(0); setStatus(e.target.value); }} aria-label="Filter by status">
            <option value="">All statuses</option>
            <option value="PENDING">Pending</option>
            <option value="COMPLETED">Completed</option>
            <option value="FAILED">Failed</option>
          </select>
        </div>
        <ErrorBox>{error}</ErrorBox>
        {loading && !data && <Spinner />}
        {data && (
          <>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Transaction ID</th><th>Partner</th><th>Masked Aadhaar</th><th>Risk score</th><th>Status</th><th>Created</th><th /></tr></thead>
                <tbody>
                  {data.items.length === 0 && <tr><td colSpan={7} className="empty">No transactions found.</td></tr>}
                  {data.items.map((t) => (
                    <tr key={t.transaction_id}>
                      <td><code>{t.transaction_id}</code></td>
                      <td>{t.partner_id}</td>
                      <td><code>{t.masked_aadhaar_number}</code></td>
                      <td><RiskScore value={t.risk_score} /></td>
                      <td><StatusBadge status={t.status} /></td>
                      <td>{fmtDate(t.created_at)}</td>
                      <td><button className="link" onClick={() => go("audit", t.transaction_id)}>Audit</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="pager">
              <span>{data.total} total</span>
              <div>
                <button className="btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>← Prev</button>
                <button className="btn" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>Next →</button>
              </div>
            </div>
          </>
        )}
      </Card>
    </>
  );
}
