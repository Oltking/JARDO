import { useEffect, useState } from "react";
import { health } from "../api";

// Launch splash + core-ready gate. The self-contained build spawns the Python
// core as a sidecar, which takes a few seconds to boot. We hold the splash
// until /healthz answers (polling), so the app never flashes "can't reach the
// core" on a cold start. A minimum hold keeps it graceful when the core is
// already warm (dev). If the core never comes up, we surface a clear message.
type Phase = "in" | "out" | "done";

const MIN_HOLD_MS = 1200; // don't blink past it when the core is already warm
const GIVE_UP_MS = 90_000; // frozen first boot + model warm can be slow

export function Splash() {
  const [phase, setPhase] = useState<Phase>("in");
  const [slow, setSlow] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    const started = Date.now();
    const slowTimer = window.setTimeout(() => alive && setSlow(true), 6000);

    async function waitForCore() {
      while (alive) {
        try {
          const h = await health();
          if (h && (h as { status?: string }).status === "ok") break;
        } catch {
          /* core not up yet */
        }
        if (Date.now() - started > GIVE_UP_MS) {
          if (alive) setFailed(true);
          return;
        }
        await new Promise((r) => setTimeout(r, 400));
      }
      // healthy — respect the minimum hold, then fade out and unmount
      const remaining = Math.max(0, MIN_HOLD_MS - (Date.now() - started));
      window.setTimeout(() => {
        if (!alive) return;
        setPhase("out");
        window.setTimeout(() => alive && setPhase("done"), 600);
      }, remaining);
    }

    void waitForCore();
    return () => {
      alive = false;
      window.clearTimeout(slowTimer);
    };
  }, []);

  if (phase === "done") return null;

  return (
    <div className={`splash ${phase}`}>
      <div className="splash-inner">
        <img className="splash-logo" src="/jardo-logo.png" alt="Jardo" />
        <div className="splash-word">Jardo</div>
        <div className="splash-bar">
          <span />
        </div>
        {failed ? (
          <div className="splash-note error">
            The core didn't start. Quit and reopen Jardo; if it persists, check
            Console for &ldquo;jardo-core&rdquo;.
          </div>
        ) : (
          slow && <div className="splash-note">Starting the engine…</div>
        )}
      </div>
    </div>
  );
}
