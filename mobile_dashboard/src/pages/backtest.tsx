import { useState } from "react";
import Nav from "@/components/Nav";
import { apiFetch } from "@/lib/api";

export default function BacktestPage() {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setError(null);
    setResult(null);
    try {
      const run = await apiFetch("/backtest/run", {
        method: "POST",
        body: JSON.stringify({ start, end, source: "broker" }),
      });
      const results = await apiFetch(`/backtest/results/${run.backtest_id}`);
      setResult(results);
    } catch (err: any) {
      setError(err.message);
    }
  }

  return (
    <div>
      <Nav />
      <div style={{ padding: 16, display: "grid", gap: 8, maxWidth: 480 }}>
        <h2>Run Backtest</h2>
        <input placeholder="Start (YYYY-MM-DD)" value={start} onChange={(e) => setStart(e.target.value)} />
        <input placeholder="End (YYYY-MM-DD)" value={end} onChange={(e) => setEnd(e.target.value)} />
        <button onClick={run}>Run</button>
        {error && <span style={{ color: "#ff6b6b" }}>{error}</span>}
        {result && <pre>{JSON.stringify(result, null, 2)}</pre>}
      </div>
    </div>
  );
}
