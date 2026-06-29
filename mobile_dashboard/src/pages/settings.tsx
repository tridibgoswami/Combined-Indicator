import { useEffect, useState } from "react";
import Nav from "@/components/Nav";
import { apiFetch } from "@/lib/api";

export default function SettingsPage() {
  const [config, setConfig] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch("/config").then(setConfig).catch((e) => setError(e.message));
  }, []);

  async function patch(path: string, value: any) {
    setError(null);
    try {
      const updated = await apiFetch("/config", { method: "PATCH", body: JSON.stringify({ path, value }) });
      setConfig(updated);
    } catch (err: any) {
      setError(err.message);
    }
  }

  return (
    <div>
      <Nav />
      <div style={{ padding: 16, display: "grid", gap: 12, maxWidth: 480 }}>
        <h2>Settings</h2>
        {error && <span style={{ color: "#ff6b6b" }}>{error}</span>}
        <div>
          <label>Execution mode: </label>
          <select
            value={config?.execution?.instrument_mode || "FUTURES"}
            onChange={(e) => patch("execution.instrument_mode", e.target.value)}
          >
            <option value="FUTURES">FUTURES</option>
            <option value="OPTION_BUYING">OPTION_BUYING</option>
            <option value="OPTION_SELLING">OPTION_SELLING</option>
          </select>
        </div>
        <div>
          <label>Paper/live mode: </label>
          <select
            value={config?.execution?.mode || "PAPER"}
            onChange={(e) => patch("execution.mode", e.target.value)}
          >
            <option value="PAPER">PAPER</option>
            <option value="LIVE">LIVE</option>
          </select>
        </div>
        <div>
          <label>MAE points: </label>
          <input
            type="number"
            defaultValue={config?.risk_management?.mae_points}
            onBlur={(e) => patch("risk_management.mae_points", Number(e.target.value))}
          />
        </div>
        <div>
          <label>Option buying target delta: </label>
          <input
            type="number"
            step="0.05"
            defaultValue={config?.option_execution?.strike_selection?.target_delta}
            onBlur={(e) => patch("option_execution.strike_selection.target_delta", Number(e.target.value))}
          />
        </div>
        <div>
          <label>Option selling hedge distance (points): </label>
          <input
            type="number"
            defaultValue={config?.option_execution?.option_selling?.hedge_distance_points}
            onBlur={(e) => patch("option_execution.option_selling.hedge_distance_points", Number(e.target.value))}
          />
        </div>
        <pre>{JSON.stringify(config, null, 2)}</pre>
      </div>
    </div>
  );
}
