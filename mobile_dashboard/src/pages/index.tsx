import { useEffect, useState } from "react";
import Nav from "@/components/Nav";
import { apiFetch } from "@/lib/api";
import { Badge, Card, Empty, Row, fmtNum, pointsColor } from "@/components/ui";

export default function Dashboard() {
  const [engineStatus, setEngineStatus] = useState<any>(null);
  const [brokerStatus, setBrokerStatus] = useState<any>(null);
  const [position, setPosition] = useState<any>(null);
  const [pnl, setPnl] = useState<any>(null);
  const [signals, setSignals] = useState<any[]>([]);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    const load = async () => {
      try {
        const [engine, broker, pos, pnlData, sig] = await Promise.allSettled([
          apiFetch("/engine/status"),
          apiFetch("/broker/status"),
          apiFetch("/positions"),
          apiFetch("/pnl"),
          apiFetch("/signals"),
        ]);
        setEngineStatus(engine.status === "fulfilled" ? engine.value : null);
        setBrokerStatus(broker.status === "fulfilled" ? broker.value : null);
        setPosition(pos.status === "fulfilled" ? pos.value : null);
        setPnl(pnlData.status === "fulfilled" ? pnlData.value : null);
        setSignals(sig.status === "fulfilled" ? sig.value.slice(-1) : []);
        setOffline(false);
      } catch {
        setOffline(true);
      }
    };
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, []);

  const lastSignal = signals[0];
  const isFlat = !position || position.current_position === "FLAT" || !position.current_position;

  return (
    <div>
      <Nav />
      <div style={{ padding: 16, maxWidth: 560, margin: "0 auto" }}>
        {offline && <Card emoji="⚠️" title="Connection issue">Couldn&apos;t reach the API. Pull to refresh.</Card>}

        <Card emoji="⚙️" title="Engine Status">
          {engineStatus ? (
            <>
              <Row label="State" value={<Badge>{engineStatus.state}</Badge>} />
              <Row label="Mode" value={<Badge>{engineStatus.mode}</Badge>} />
              {engineStatus.instrument_mode && <Row label="Instrument mode" value={engineStatus.instrument_mode} />}
              {engineStatus.detail && <Row label="Detail" value={engineStatus.detail} />}
            </>
          ) : (
            <Empty text="Engine status unavailable" />
          )}
        </Card>

        <Card emoji="📶" title="Broker Status">
          {brokerStatus ? (
            <>
              <Row label="Status" value={<Badge>{brokerStatus.status}</Badge>} />
              {brokerStatus.detail && <Row label="Detail" value={brokerStatus.detail} />}
            </>
          ) : (
            <Empty text="Broker status unavailable" />
          )}
        </Card>

        <Card emoji={isFlat ? "⚪" : position.current_position === "LONG" ? "🟢" : "🔴"} title="Current Position">
          {!isFlat ? (
            <>
              <Row label="Open position" value={<Badge>{position.current_position}</Badge>} />
              <Row label="Entry price" value={fmtNum(position.entry_price)} />
              <Row label="Entry time" value={position.entry_time || "-"} />
              <Row
                label="Open points"
                value={<span style={{ color: pointsColor(position.open_points) }}>{fmtNum(position.open_points)}</span>}
              />
              {pnl && !isFlat && (
                <Row
                  label="Open PnL (₹)"
                  value={<span style={{ color: pointsColor(pnl.open_pnl) }}>₹{fmtNum(pnl.open_pnl)}</span>}
                />
              )}
            </>
          ) : (
            <Empty text="No open position (FLAT)" />
          )}
        </Card>

        <Card emoji="💰" title="Session PnL (Realized)">
          {pnl ? (
            <Row
              label="Net points"
              value={<span style={{ color: pointsColor(pnl.net_points) }}>{fmtNum(pnl.net_points)}</span>}
            />
          ) : (
            <Empty />
          )}
        </Card>

        <Card emoji="📡" title="Last Signal">
          {lastSignal ? (
            <>
              <Row label="Signal" value={<Badge>{lastSignal.signal}</Badge>} />
              <Row label="Price" value={fmtNum(lastSignal.price)} />
              <Row label="Time" value={lastSignal.datetime || "-"} />
              {lastSignal.is_chop !== undefined && <Row label="Chop filtered" value={String(lastSignal.is_chop)} />}
            </>
          ) : (
            <Empty text="No signals yet" />
          )}
        </Card>
      </div>
    </div>
  );
}
