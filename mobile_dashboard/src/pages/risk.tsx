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
  const [engineBusy, setEngineBusy] = useState(false);

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

  async function stopEngine() {
    if (!window.confirm("Pause the trading engine? It will stop fetching candles and placing new orders until resumed.")) return;
    setEngineBusy(true);
    try {
      const res = await apiFetch("/engine/stop", { method: "POST" });
      setMessage(`Engine ${res.state}`);
    } finally {
      setEngineBusy(false);
    }
  }

  async function startEngine() {
    setEngineBusy(true);
    try {
      const res = await apiFetch("/engine/start", { method: "POST" });
      setMessage(`Engine ${res.state}`);
    } finally {
      setEngineBusy(false);
    }
  }

  return (
    <div>
      <Nav />
      <div style={{ padding: 16, maxWidth: 560, margin: "0 auto" }}>
        <Card emoji="⚙️" title="Engine Control">
          <div style={{ display: "grid", gap: 12 }}>
            <button onClick={startEngine} disabled={engineBusy} style={{ ...buttonStyle, background: engineBusy ? "#2a3340" : "#1f6feb" }}>
              ▶️ Start / Resume Engine
            </button>
            <button onClick={stopEngine} disabled={engineBusy} style={{ ...buttonStyle, background: engineBusy ? "#2a3340" : "#6b4f1f" }}>
              ⏸️ Stop / Pause Engine
            </button>
          </div>
        </Card>

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
