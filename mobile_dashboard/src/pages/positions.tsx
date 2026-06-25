import { useEffect, useState } from "react";
import Nav from "@/components/Nav";
import { apiFetch } from "@/lib/api";

export default function PositionsPage() {
  const [position, setPosition] = useState<any>(null);
  const [trades, setTrades] = useState<any[]>([]);
  useEffect(() => {
    apiFetch("/positions").then(setPosition).catch(() => setPosition(null));
    apiFetch("/trades").then(setTrades).catch(() => setTrades([]));
  }, []);
  return (
    <div>
      <Nav />
      <div style={{ padding: 16 }}>
        <h2>Current Position</h2>
        <pre>{JSON.stringify(position, null, 2)}</pre>
        <h2>Closed Trades</h2>
        <pre>{JSON.stringify(trades, null, 2)}</pre>
      </div>
    </div>
  );
}
