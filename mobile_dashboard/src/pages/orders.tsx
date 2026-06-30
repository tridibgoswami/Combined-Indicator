import { useEffect, useState } from "react";
import Nav from "@/components/Nav";
import { apiFetch } from "@/lib/api";
import { Badge, Card, Empty, Row } from "@/components/ui";

export default function OrdersPage() {
  const [rows, setRows] = useState<any[]>([]);
  useEffect(() => {
    apiFetch("/orders").then(setRows).catch(() => setRows([]));
  }, []);
  return (
    <div>
      <Nav />
      <div style={{ padding: 16, maxWidth: 560, margin: "0 auto" }}>
        <Card emoji="🧾" title={`Orders (${rows.length})`}>
          {rows.length === 0 && <Empty text="No orders yet" />}
          {[...rows].reverse().map((o, i) => (
            <div key={i} style={{ borderBottom: i === rows.length - 1 ? "none" : "1px solid #1c232c", padding: "10px 0" }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                <Badge>{o.side}</Badge>
                <span style={{ color: "#8b97a5", fontSize: 13 }}>{o.datetime}</span>
              </div>
              <Row label="Symbol" value={o.tradingsymbol || "-"} />
              <Row label="Action" value={o.action || "-"} />
              <Row label="Quantity" value={o.quantity || "-"} />
              <Row label="Mode" value={<Badge>{o.mode}</Badge>} />
              <Row label="Instrument mode" value={o.instrument_mode || "-"} />
              <Row label="Reason" value={o.reason || "-"} />
            </div>
          ))}
        </Card>
      </div>
    </div>
  );
}
