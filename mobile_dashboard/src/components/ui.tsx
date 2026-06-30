import { ReactNode } from "react";

export function Card({ title, emoji, children }: { title?: string; emoji?: string; children: ReactNode }) {
  return (
    <div
      style={{
        background: "#121821",
        border: "1px solid #232b35",
        borderRadius: 12,
        padding: 16,
        marginBottom: 12,
        maxWidth: "100%",
        boxSizing: "border-box",
      }}
    >
      {title && (
        <h2 style={{ margin: "0 0 12px", fontSize: 16, display: "flex", alignItems: "center", gap: 8 }}>
          {emoji && <span>{emoji}</span>}
          {title}
        </h2>
      )}
      {children}
    </div>
  );
}

export function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: 12,
        padding: "6px 0",
        borderBottom: "1px solid #1c232c",
        fontSize: 14,
      }}
    >
      <span style={{ color: "#8b97a5" }}>{label}</span>
      <span style={{ textAlign: "right", wordBreak: "break-word" }}>{value}</span>
    </div>
  );
}

const TONE_COLORS: Record<string, { bg: string; fg: string }> = {
  green: { bg: "#143822", fg: "#5fd98a" },
  red: { bg: "#3a1620", fg: "#ff6b6b" },
  blue: { bg: "#13283d", fg: "#6fb3ff" },
  orange: { bg: "#3a2a12", fg: "#ffb35c" },
  gray: { bg: "#1c232c", fg: "#9fb0c0" },
};

export function badgeTone(value?: string | null): keyof typeof TONE_COLORS {
  const v = (value || "").toUpperCase();
  if (["RUNNING", "CONNECTED", "LONG", "BUY", "OK", "CLOSED", "PAPER"].includes(v)) return "green";
  if (["STOPPED", "DISCONNECTED", "SHORT", "SELL", "ERROR", "LIVE"].includes(v)) return v === "LIVE" ? "orange" : "red";
  if (v === "PAUSED") return "orange";
  if (["FLAT", "UNKNOWN"].includes(v)) return "gray";
  return "blue";
}

export function Badge({ children, tone }: { children: ReactNode; tone?: keyof typeof TONE_COLORS }) {
  const resolvedTone = tone || badgeTone(String(children));
  const colors = TONE_COLORS[resolvedTone] || TONE_COLORS.gray;
  return (
    <span
      style={{
        background: colors.bg,
        color: colors.fg,
        borderRadius: 999,
        padding: "2px 10px",
        fontSize: 12,
        fontWeight: 600,
        letterSpacing: 0.3,
      }}
    >
      {children}
    </span>
  );
}

export function Empty({ text = "No data yet" }: { text?: string }) {
  return <div style={{ color: "#5b6673", fontSize: 14, padding: "8px 0" }}>{text}</div>;
}

export function pointsColor(points?: number | string | null): string {
  const n = typeof points === "string" ? parseFloat(points) : points;
  if (n === undefined || n === null || Number.isNaN(n)) return "#8b97a5";
  return n >= 0 ? "#5fd98a" : "#ff6b6b";
}

export function fmtNum(value?: number | string | null, digits = 2): string {
  if (value === undefined || value === null || value === "") return "-";
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (Number.isNaN(n)) return String(value);
  return n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
