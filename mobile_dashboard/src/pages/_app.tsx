import type { AppProps } from "next/app";

export default function App({ Component, pageProps }: AppProps) {
  return (
    <div style={{ background: "#0b0f14", color: "#e6edf3", minHeight: "100vh", fontFamily: "system-ui, sans-serif" }}>
      <Component {...pageProps} />
    </div>
  );
}
