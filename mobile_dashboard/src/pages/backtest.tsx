import { useState } from "react";
import Nav from "@/components/Nav";
import { apiFetch } from "@/lib/api";
import { Badge, Card, Empty, Row, fmtNum, pointsColor } from "@/components/ui";

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

function computeSummary(rows: any[]) {
  const closed = rows.filter((r) => r.status?.toUpperCase() === "CLOSED" || !r.status);
  const wins = closed.filter((r) => parseFloat(r.points) > 0);
  const losses = closed.filter((r) => parseFloat(r.points) < 0);
  const netPoints = closed.reduce((s, r) => s + (parseFloat(r.points) || 0), 0);
  const grossProfit = wins.reduce((s, r) => s + (parseFloat(r.points) || 0), 0);
  const grossLoss = Math.abs(losses.reduce((s, r) => s + (parseFloat(r.points) || 0), 0));
  const winRate = closed.length > 0 ? (wins.length / closed.length) * 100 : 0;
  const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? Infinity : 0;
  const best = closed.length > 0 ? Math.max(...closed.map((r) => parseFloat(r.points) || 0)) : 0;
  const worst = closed.length > 0 ? Math.min(...closed.map((r) => parseFloat(r.points) || 0)) : 0;
  return { total: closed.length, wins: wins.length, losses: losses.length, winRate, netPoints, grossProfit, grossLoss, profitFactor, best, worst };
}

function StatTile({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ background: "#0d1520", borderRadius: 10, padding: "12px 14px", flex: "1 1 45%", minWidth: 130 }}>
      <div style={{ fontSize: 11, color: "#8b97a5", marginBottom: 4, textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color: color || "#e6edf3" }}>{value}</div>
    </div>
  );
}

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
      const r = await apiFetch("/backtest/run", {
        method: "POST",
        body: JSON.stringify({ start, end, source: "broker" }),
      });
      const results = await apiFetch(`/backtest/results/${r.backtest_id}`);
      setResult(results);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setRunning(false);
    }
  }

  const rows: any[] = result?.rows ?? [];
  const summary = rows.length > 0 ? computeSummary(rows) : null;
  const closed = rows.filter((r) => r.status?.toUpperCase() === "CLOSED" || !r.status);

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
              width: "100%", padding: "12px 16px", borderRadius: 8, border: "none",
              background: running ? "#2a3340" : "#1f6feb",
              color: "white", fontSize: 15, fontWeight: 600,
              cursor: running ? "default" : "pointer",
            }}
          >
            {running ? "⏳ Running..." : "▶ Run Backtest"}
          </button>
          {error && <div style={{ color: "#ff6b6b", marginTop: 12, fontSize: 14 }}>{error}</div>}
        </Card>

        {summary && (
          <Card emoji="📊" title="Summary">
            <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 4 }}>
              <StatTile label="Total Trades" value={String(summary.total)} />
              <StatTile label="Win Rate" value={`${fmtNum(summary.winRate, 1)}%`} color={summary.winRate >= 50 ? "#5fd98a" : "#ff6b6b"} />
              <StatTile label="Net Points" value={fmtNum(summary.netPoints)} color={pointsColor(summary.netPoints)} />
              <StatTile label="Profit Factor" value={isFinite(summary.profitFactor) ? fmtNum(summary.profitFactor) : "∞"} color={summary.profitFactor >= 1 ? "#5fd98a" : "#ff6b6b"} />
              <StatTile label="Wins" value={String(summary.wins)} color="#5fd98a" />
              <StatTile label="Losses" value={String(summary.losses)} color="#ff6b6b" />
              <StatTile label="Best Trade" value={fmtNum(summary.best)} color="#5fd98a" />
              <StatTile label="Worst Trade" value={fmtNum(summary.worst)} color="#ff6b6b" />
            </div>
          </Card>
        )}

        {closed.length > 0 && (
          <Card emoji="📋" title={`Trades (${closed.length})`}>
            {[...closed].reverse().map((r, i) => {
              const pts = parseFloat(r.points) || 0;
              const pnl = parseFloat(r.pnl_value) || 0;
              return (
                <div key={i} style={{ borderBottom: i === closed.length - 1 ? "none" : "1px solid #1c232c", padding: "10px 0" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                    <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                      <Badge>{r.entry_signal || r.direction}</Badge>
                      {r.exit_reason && <span style={{ fontSize: 11, color: "#8b97a5" }}>{r.exit_reason}</span>}
                    </div>
                    <span style={{ fontWeight: 700, color: pointsColor(pts) }}>{pts >= 0 ? "+" : ""}{fmtNum(pts)} pts</span>
                  </div>
                  <Row label="Entry" value={`${fmtNum(r.entry_price)} @ ${(r.entry_time || "").slice(0, 16)}`} />
                  <Row label="Exit" value={`${fmtNum(r.exit_price)} @ ${(r.exit_time || "").slice(0, 16)}`} />
                  {pnl !== 0 && (
                    <Row label="PnL (₹)" value={<span style={{ color: pointsColor(pnl) }}>₹{fmtNum(pnl)}</span>} />
                  )}
                </div>
              );
            })}
          </Card>
        )}

        {result && rows.length === 0 && <Empty text="No closed trades in this date range" />}
      </div>
    </div>
  );
}
