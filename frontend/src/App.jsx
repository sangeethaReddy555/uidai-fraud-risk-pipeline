import { useState } from "react";
import Sidebar from "./components/Sidebar.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Initiate from "./pages/Initiate.jsx";
import History from "./pages/History.jsx";
import Audit from "./pages/Audit.jsx";

export default function App() {
  const [page, setPage] = useState("dashboard");
  const [auditId, setAuditId] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);

  const go = (p, id) => {
    if (id) setAuditId(id);
    setPage(p);
    setMenuOpen(false);
  };

  return (
    <div className="shell">
      <button className="hamburger" aria-label="Toggle menu" onClick={() => setMenuOpen((o) => !o)}>☰</button>
      <Sidebar page={page} go={go} open={menuOpen} />
      <main className="content">
        {page === "dashboard" && <Dashboard go={go} />}
        {page === "initiate" && <Initiate go={go} />}
        {page === "history" && <History go={go} />}
        {page === "audit" && <Audit initialId={auditId} />}
      </main>
    </div>
  );
}
