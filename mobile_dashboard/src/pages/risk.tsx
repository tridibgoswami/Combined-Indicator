import { useState } from "react";
import Nav from "@/components/Nav";
import { apiFetch } from "@/lib/api";
import { Card } from "@/components/ui";

const buttonStyle: React.CSSProperties = {
  width: "100%",
  padding: "14px 16px",
  borderRadius: 8,
  border: "none",
  color: "white",
  fontSize: 15,
  fontWeight: 600,
  cursor: "pointer",
};

export default function RiskPage() {
  const [message, setMessage] = useState<string | null>(null);

  async function exitAll() {
    if (!window.confirm("Flatten all open positions now?")) return;
    const res = await apiFetch("/risk/exit-all", { method: "POST" });
    setMessage(res.message);
  }

  async function disableLive() {
    if (!window.confirm("Disable live trading immediately (emergency stop)?")) return;
    const res = await apiFetch("/risk/disable-live-trading", { method: "POST" });
    setMessage(res.message);
  }

  return (
    <div>
      <Nav />
      <div style={{ padding: 16, maxWidth: 560, margin: "0 auto" }}>
        <Card emoji="🚨" title="Risk Control">
          <div style={{ display: "grid", gap: 12 }}>
            <button onClick={exitAll} style={{ ...buttonStyle, background: "#b33" }}>
              🛑 Emergency Exit All
            </button>
            <button onClick={disableLive} style={{ ...buttonStyle, background: "#933" }}>
              ⛔ Disable Live Trading
            </button>
            {message && <div style={{ color: "#5fd98a", fontSize: 14, marginTop: 4 }}>✅ {message}</div>}
          </div>
        </Card>
      </div>
    </div>
  );
}
