import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useState } from "react";
import { clearToken } from "@/lib/api";

const LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/signals", label: "Signals" },
  { href: "/orders", label: "Orders" },
  { href: "/positions", label: "Positions" },
  { href: "/backtest", label: "Backtest" },
  { href: "/risk", label: "Risk" },
  { href: "/settings", label: "Settings" },
];

export default function Nav() {
  const router = useRouter();
  const [loggedIn, setLoggedIn] = useState(false);

  useEffect(() => {
    setLoggedIn(!!window.localStorage.getItem("access_token"));
  }, [router.pathname]);

  function logout() {
    clearToken();
    setLoggedIn(false);
    router.push("/login");
  }

  return (
    <nav style={{ display: "flex", flexWrap: "wrap", gap: 12, padding: 12, borderBottom: "1px solid #2a2f36" }}>
      {LINKS.map((l) => (
        <Link key={l.href} href={l.href} style={{ color: "#9fd3ff", textDecoration: "none", fontSize: 14 }}>
          {l.label}
        </Link>
      ))}
      {loggedIn ? (
        <button
          onClick={logout}
          style={{ color: "#ff8787", background: "none", border: "none", fontSize: 14, cursor: "pointer", padding: 0 }}
        >
          Logout
        </button>
      ) : (
        <Link href="/login" style={{ color: "#9fd3ff", textDecoration: "none", fontSize: 14 }}>
          Login
        </Link>
      )}
    </nav>
  );
}
