import { useState } from "react";
import Nav from "@/components/Nav";
import { apiFetch } from "@/lib/api";
import { Card } from "@/components/ui";

const fieldStyle: React.CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  padding: "10px 12px",
  borderRadius: 8,
  border: "1px solid #232b35",
  background: "#0b0f14",
  color: "#e6edf3",
  fontSize: 15,
};

const labelStyle: React.CSSProperties = {
  display: "block",
  marginBottom: 6,
  fontSize: 13,
  color: "#8b97a5",
};

export default function BacktestPage() {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  async function run() {
    setError(null);
    setResult(null);
    setRunning(true);
    try {
      const run = await apiFetch("/backtest/run", {
        method: "POST",
        body: JSON.stringify({ start, end, source: "broker" }),
      });
      const results = await apiFetch(`/backtest/results/${run.backtest_id}`);
      setResult(results);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div>
      <Nav />
      <div style={{ padding: 16, maxWidth: 560, margin: "0 auto" }}>
        <Card emoji="🧪" title="Run Backtest">
          <div style={{ marginBottom: 12 }}>
            <label style={labelStyle}>Start (YYYY-MM-DD)</label>
            <input style={fieldStyle} placeholder="2026-06-01" value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div style={{ marginBottom: 12 }}>
            <label style={labelStyle}>End (YYYY-MM-DD)</label>
            <input style={fieldStyle} placeholder="2026-06-22" value={end} onChange={(e) => setEnd(e.target.value)} />
          </div>
          <button
            onClick={run}
            disabled={running}
            style={{
              width: "100%",
              padding: "12px 16px",
              borderRadius: 8,
              border: "none",
              background: running ? "#2a3340" : "#1f6feb",
              color: "white",
              fontSize: 15,
              fontWeight: 600,
              cursor: running ? "default" : "pointer",
            }}
          >
            {running ? "⏳ Running..." : "▶️ Run Backtest"}
          </button>
          {error && <div style={{ color: "#ff6b6b", marginTop: 12 }}>{error}</div>}
        </Card>

        {result && (
          <Card emoji="📊" title="Results">
            <pre
              style={{
                fontSize: 12,
                overflowX: "auto",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              {JSON.stringify(result, null, 2)}
            </pre>
          </Card>
        )}
      </div>
    </div>
  );
}
