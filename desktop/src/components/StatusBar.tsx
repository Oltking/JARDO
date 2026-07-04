import { useEffect, useState } from "react";
import { health, type HealthStatus } from "../api";

interface Props {
  onKillSwitch: () => void;
  hotkeyLabel: string;
  killFlash: boolean;
}

type Conn = "connecting" | "online" | "offline";

// Header/status indicator. Polls GET /healthz (via the Rust proxy) so the
// owner can see at a glance whether the core is reachable.
export function StatusBar({ onKillSwitch, hotkeyLabel, killFlash }: Props) {
  const [conn, setConn] = useState<Conn>("connecting");
  const [detail, setDetail] = useState<HealthStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const h = await health();
        if (cancelled) return;
        setDetail(h);
        setConn("online");
      } catch {
        if (cancelled) return;
        setDetail(null);
        setConn("offline");
      }
    }
    poll();
    const id = window.setInterval(poll, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const dotClass =
    conn === "online" ? "dot online" : conn === "offline" ? "dot offline" : "dot";

  return (
    <header className="statusbar">
      <div className="brand">
        <span className="logo">◆</span>
        <span className="title">JARVIS</span>
      </div>

      <div className="conn">
        <span className={dotClass} />
        <span className="conn-label">
          {conn === "online"
            ? `core online · db:${detail?.db ?? "?"} · redis:${detail?.redis ?? "?"}`
            : conn === "offline"
            ? "core offline — is `uv run jarvis serve` running?"
            : "connecting…"}
        </span>
      </div>

      <button
        className={killFlash ? "kill-btn active" : "kill-btn"}
        onClick={onKillSwitch}
        title={`Halt synthetic input (global hotkey ${hotkeyLabel})`}
      >
        ⛔ Kill switch <span className="hotkey">{hotkeyLabel}</span>
      </button>
    </header>
  );
}
