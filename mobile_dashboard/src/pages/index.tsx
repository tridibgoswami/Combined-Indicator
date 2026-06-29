import { useEffect, useState } from "react";
import Nav from "@/components/Nav";
import { apiFetch } from "@/lib/api";

export default function Dashboard() {
  const [engineStatus, setEngineStatus] = useState<any>(null);
  const [brokerStatus, setBrokerStatus] = useState<any>(null);
  const [positions, setPositions] = useState<any>(null);
  const [pnl, setPnl] = useState<any>(null);
  const [signals, setSignals] = useState<any[]>([]);

  useEffect(() => {
    const load = async () => {
      try {
        setEngineStatus(await apiFetch("/engine/status"));
        setBrokerStatus(await apiFetch("/broker/status"));
        setPositions(await apiFetch("/positions"));
        setPnl(await apiFetch("/pnl"));
        const sig = await apiFetch("/signals");
        setSignals(sig.slice(-1));
      } catch {
        // Surfaced via empty state below; dashboard stays usable while offline.
      }
    };
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, []);

  return (
    <div>
      <Nav />
      <div style={{ padding: 16, display: "grid", gap: 12 }}>
        <h2>Engine Status</h2>
        <pre>{JSON.stringify(engineStatus, null, 2)}</pre>
        <h2>Broker Status</h2>
        <pre>{JSON.stringify(brokerStatus, null, 2)}</pre>
        <h2>Current Position</h2>
        <pre>{JSON.stringify(positions, null, 2)}</pre>
        <h2>Open PnL</h2>
        <pre>{JSON.stringify(pnl, null, 2)}</pre>
        <h2>Last Signal</h2>
        <pre>{JSON.stringify(signals[0] || {}, null, 2)}</pre>
      </div>
    </div>
  );
}
