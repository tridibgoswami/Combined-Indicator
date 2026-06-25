import { useEffect, useState } from "react";
import Nav from "@/components/Nav";
import { apiFetch } from "@/lib/api";

export default function OrdersPage() {
  const [rows, setRows] = useState<any[]>([]);
  useEffect(() => {
    apiFetch("/orders").then(setRows).catch(() => setRows([]));
  }, []);
  return (
    <div>
      <Nav />
      <div style={{ padding: 16 }}>
        <h2>Orders</h2>
        <pre>{JSON.stringify(rows, null, 2)}</pre>
      </div>
    </div>
  );
}
