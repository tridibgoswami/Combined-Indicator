import { useState } from "react";
import Nav from "@/components/Nav";
import { apiFetch } from "@/lib/api";

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
      <div style={{ padding: 16, display: "grid", gap: 12, maxWidth: 360 }}>
        <h2>Risk Control</h2>
        <button onClick={exitAll} style={{ background: "#b33", color: "white" }}>Emergency Exit All</button>
        <button onClick={disableLive} style={{ background: "#933", color: "white" }}>Disable Live Trading</button>
        {message && <span>{message}</span>}
      </div>
    </div>
  );
}
