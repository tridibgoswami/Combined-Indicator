import Link from "next/link";

const LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/signals", label: "Signals" },
  { href: "/orders", label: "Orders" },
  { href: "/positions", label: "Positions" },
  { href: "/backtest", label: "Backtest" },
  { href: "/risk", label: "Risk" },
  { href: "/settings", label: "Settings" },
  { href: "/login", label: "Login" },
];

export default function Nav() {
  return (
    <nav style={{ display: "flex", flexWrap: "wrap", gap: 12, padding: 12, borderBottom: "1px solid #2a2f36" }}>
      {LINKS.map((l) => (
        <Link key={l.href} href={l.href} style={{ color: "#9fd3ff", textDecoration: "none", fontSize: 14 }}>
          {l.label}
        </Link>
      ))}
    </nav>
  );
}
