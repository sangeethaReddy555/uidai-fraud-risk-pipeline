import { createContext, useContext, useEffect, useState } from "react";
import { api } from "./api.js";

const AuthCtx = createContext(null);
export const useAuth = () => useContext(AuthCtx);

// Dev-only identity switcher. Tokens come from GET /api/v1/dev/tokens (development tokens, NOT production credentials)
// or can be pasted manually. The token is kept in memory only.
export function AuthProvider({ children }) {
  const [devTokens, setDevTokens] = useState({});
  const [selected, setSelected] = useState("partner_a");
  const [custom, setCustom] = useState("");
  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    api.devTokens().then((r) => {
      if (r.ok) setDevTokens(r.data.tokens);
      else setLoadError(r.status === 404 ? "Dev tokens disabled – paste a token." : r.data?.detail || "Could not load dev tokens");
    });
  }, []);

  const current = selected === "custom" ? { token: custom, label: "Custom token", partner_id: "" } : devTokens[selected];
  return (
    <AuthCtx.Provider value={{ devTokens, selected, setSelected, custom, setCustom, current, token: current?.token || "", loadError }}>
      {children}
    </AuthCtx.Provider>
  );
}
