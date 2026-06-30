import { useEffect, useState } from "react";
import Nav from "@/components/Nav";
import { apiFetch } from "@/lib/api";
import { Badge, Card, Empty, Row, fmtNum } from "@/components/ui";

export default function SignalsPage() {
  const [rows, setRows] = useState<any[]>([]);
  useEffect(() => {
    apiFetch("/signals").then(setRows).catch(() => setRows([]));
  }, []);
  return (
    <div>
      <Nav />
      <div style={{ padding: 16, maxWidth: 560, margin: "0 auto" }}>
        <Card emoji="📡" title={`Signals (${rows.length})`}>
          {rows.length === 0 && <Empty text="No signals yet" />}
          {[...rows].reverse().map((s, i) => (
            <div key={i} style={{ borderBottom: i === rows.length - 1 ? "none" : "1px solid #1c232c", padding: "10px 0" }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                <Badge>{s.signal}</Badge>
                <span style={{ color: "#8b97a5", fontSize: 13 }}>{s.datetime}</span>
              </div>
              <Row label="Price" value={fmtNum(s.price)} />
              <Row label="HMA" value={fmtNum(s.hma)} />
              <Row label="Source" value={s.source || "-"} />
              {s.entry_time_blocked === "True" && <Row label="Entry blocked" value={<Badge tone="orange">YES</Badge>} />}
            </div>
          ))}
        </Card>
      </div>
    </div>
  );
}
