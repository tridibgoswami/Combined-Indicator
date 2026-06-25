import { useRouter } from "next/router";
import { useState } from "react";
import { login } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await login(email, password);
      router.push("/");
    } catch (err: any) {
      setError(err.message);
    }
  }

  return (
    <div style={{ display: "flex", justifyContent: "center", paddingTop: 80 }}>
      <form onSubmit={onSubmit} style={{ display: "flex", flexDirection: "column", gap: 12, width: 280 }}>
        <h2>Trading Platform Login</h2>
        <input placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input placeholder="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <span style={{ color: "#ff6b6b" }}>{error}</span>}
        <button type="submit">Log in</button>
      </form>
    </div>
  );
}
