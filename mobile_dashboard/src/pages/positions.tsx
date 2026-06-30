import { useEffect, useState } from "react";
import Nav from "@/components/Nav";
import { apiFetch } from "@/lib/api";
import { Badge, Card, Empty, Row, fmtNum, pointsColor } from "@/components/ui";

export default function PositionsPage() {
  const [position, setPosition] = useState<any>(null);
  const [trades, setTrades] = useState<any[]>([]);
  useEffect(() => {
    apiFetch("/positions").then(setPosition).catch(() => setPosition(null));
    apiFetch("/trades").then(setTrades).catch(() => setTrades([]));
  }, []);

  const isFlat = !position || position.current_position === "FLAT" || !position.current_position;

  return (
    <div>
      <Nav />
      <div style={{ padding: 16, maxWidth: 560, margin: "0 auto" }}>
        <Card emoji="📌" title="Current Position">
          {!isFlat ? (
            <>
              <Row label="Open position" value={<Badge>{position.current_position}</Badge>} />
              <Row label="Entry price" value={fmtNum(position.entry_price)} />
              <Row label="Entry time" value={position.entry_time || "-"} />
              <Row
                label="Open points"
                value={<span style={{ color: pointsColor(position.open_points) }}>{fmtNum(position.open_points)}</span>}
              />
            </>
          ) : (
            <Empty text="No open position (FLAT)" />
          )}
        </Card>

        <Card emoji="📒" title={`Closed Trades (${trades.length})`}>
          {trades.length === 0 && <Empty text="No closed trades yet" />}
          {[...trades].reverse().map((t, i) => (
            <div key={i} style={{ borderBottom: i === trades.length - 1 ? "none" : "1px solid #1c232c", padding: "10px 0" }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                <Badge>{t.position}</Badge>
                <span style={{ color: pointsColor(t.points), fontWeight: 700 }}>
                  {fmtNum(t.points)} pts ({t.pnl_value ? `₹${fmtNum(t.pnl_value, 0)}` : "-"})
                </span>
              </div>
              <Row label="Entry" value={`${t.entry_signal} @ ${fmtNum(t.entry_price)}`} />
              <Row label="Entry time" value={t.entry_time || "-"} />
              <Row label="Exit" value={`${t.exit_signal} @ ${fmtNum(t.exit_price)}`} />
              <Row label="Exit time" value={t.exit_time || "-"} />
              <Row label="Exit reason" value={t.exit_reason || "-"} />
            </div>
          ))}
        </Card>
      </div>
    </div>
  );
}
