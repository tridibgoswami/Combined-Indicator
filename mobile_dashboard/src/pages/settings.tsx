import { useEffect, useState } from "react";
import Nav from "@/components/Nav";
import { apiFetch } from "@/lib/api";
import { Badge, Card } from "@/components/ui";

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

export default function SettingsPage() {
  const [config, setConfig] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    apiFetch("/config").then(setConfig).catch((e) => setError(e.message));
  }, []);

  async function patch(path: string, value: any) {
    setError(null);
    setSaved(null);
    try {
      const updated = await apiFetch("/config", { method: "PATCH", body: JSON.stringify({ path, value }) });
      setConfig(updated);
      setSaved(path);
      setTimeout(() => setSaved(null), 2000);
    } catch (err: any) {
      setError(err.message);
    }
  }

  return (
    <div>
      <Nav />
      <div style={{ padding: 16, maxWidth: 560, margin: "0 auto" }}>
        {error && (
          <Card emoji="⚠️" title="Could not load settings">
            <span style={{ color: "#ff6b6b" }}>{error}</span>
          </Card>
        )}

        <Card emoji="🛠️" title="Execution">
          <div style={{ marginBottom: 16 }}>
            <label style={labelStyle}>Execution mode</label>
            <select
              style={fieldStyle}
              value={config?.execution?.instrument_mode || "FUTURES"}
              onChange={(e) => patch("execution.instrument_mode", e.target.value)}
            >
              <option value="FUTURES">FUTURES</option>
              <option value="OPTION_BUYING">OPTION_BUYING</option>
              <option value="OPTION_SELLING">OPTION_SELLING</option>
            </select>
          </div>
          <div>
            <label style={labelStyle}>Paper/live mode</label>
            <select
              style={fieldStyle}
              value={config?.execution?.mode || "PAPER"}
              onChange={(e) => patch("execution.mode", e.target.value)}
            >
              <option value="PAPER">PAPER</option>
              <option value="LIVE">LIVE</option>
            </select>
            <div style={{ marginTop: 6 }}>
              <Badge>{config?.execution?.mode || "PAPER"}</Badge>
            </div>
          </div>
        </Card>

        <Card emoji="🛡️" title="Risk">
          <div>
            <label style={labelStyle}>MAE points</label>
            <input
              style={fieldStyle}
              type="number"
              defaultValue={config?.risk_management?.mae_points}
              onBlur={(e) => patch("risk_management.mae_points", Number(e.target.value))}
            />
          </div>
        </Card>

        <Card emoji="📐" title="Options">
          <div style={{ marginBottom: 16 }}>
            <label style={labelStyle}>Option buying target delta</label>
            <input
              style={fieldStyle}
              type="number"
              step="0.05"
              defaultValue={config?.option_execution?.strike_selection?.target_delta}
              onBlur={(e) => patch("option_execution.strike_selection.target_delta", Number(e.target.value))}
            />
          </div>
          <div>
            <label style={labelStyle}>Option selling hedge distance (points)</label>
            <input
              style={fieldStyle}
              type="number"
              defaultValue={config?.option_execution?.option_selling?.hedge_distance_points}
              onBlur={(e) => patch("option_execution.option_selling.hedge_distance_points", Number(e.target.value))}
            />
          </div>
        </Card>

        {saved && <div style={{ color: "#5fd98a", fontSize: 13, marginBottom: 12 }}>✅ Saved {saved}</div>}

        <details>
          <summary style={{ cursor: "pointer", color: "#8b97a5", fontSize: 13, marginBottom: 8 }}>
            Advanced: raw config JSON
          </summary>
          <pre
            style={{
              fontSize: 12,
              overflowX: "auto",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              background: "#0b0f14",
              border: "1px solid #232b35",
              borderRadius: 8,
              padding: 12,
            }}
          >
            {JSON.stringify(config, null, 2)}
          </pre>
        </details>
      </div>
    </div>
  );
}
