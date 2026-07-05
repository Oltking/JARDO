import { useEffect, useState } from "react";
import { health, type HealthStatus } from "../api";

interface Props {
  onKillSwitch: () => void;
  hotkeyLabel: string;
  killFlash: boolean;
}

type Conn = "connecting" | "online" | "offline";

// Minimal header: brand mark + wordmark, a quiet connection indicator, and the
// kill switch (ghosted until engaged). Polls GET /healthz via the Rust proxy.
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

  const label =
    conn === "online" ? "Connected" : conn === "offline" ? "Offline" : "Connecting";

  return (
    <header className="statusbar">
      <div className="brand" title="Jardo">
        {/* Minimal "A" mark echoing the halftone logo */}
        <svg className="mark" viewBox="0 0 24 24" aria-hidden="true">
          <path
            d="M12 4 L4.5 20 M12 4 L19.5 20 M7.6 14.5 L16.4 14.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
          />
        </svg>
        <span className="title">Jardo</span>
      </div>

      <div
        className={`conn ${conn}`}
        title={detail ? `db ${detail.db} · redis ${detail.redis}` : ""}
      >
        <span className="dot" />
        <span className="conn-label">{label}</span>
      </div>

      <button
        className={killFlash ? "kill-btn active" : "kill-btn"}
        onClick={onKillSwitch}
        title={`Halt synthetic input · ${hotkeyLabel}`}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" className="kill-ico">
          <circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" strokeWidth="1.8" />
          <path d="M12 8 L12 12.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
        <span>Stop</span>
      </button>
    </header>
  );
}
