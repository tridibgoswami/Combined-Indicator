import { useEffect, useState } from "react";
import Nav from "@/components/Nav";
import { apiFetch } from "@/lib/api";

export default function SignalsPage() {
  const [rows, setRows] = useState<any[]>([]);
  useEffect(() => {
    apiFetch("/signals").then(setRows).catch(() => setRows([]));
  }, []);
  return (
    <div>
      <Nav />
      <div style={{ padding: 16 }}>
        <h2>Signals</h2>
        <pre>{JSON.stringify(rows, null, 2)}</pre>
      </div>
    </div>
  );
}
