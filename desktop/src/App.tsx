import { useCallback, useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { register, unregister } from "@tauri-apps/plugin-global-shortcut";
import { Jardo } from "./components/Jardo";
import { Approvals } from "./components/Approvals";
import { Agents } from "./components/Agents";
import { Reports } from "./components/Reports";
import { Savings } from "./components/Savings";
import { Settings } from "./components/Settings";
import { Splash } from "./components/Splash";
import { Briefing } from "./components/Briefing";
import { Onboarding } from "./components/Onboarding";
import { getIdentity, health, killSwitch } from "./api";

// Secondary surfaces live behind a single "More" drawer so the main screen stays
// what Jardo is for: talking and supervising. Nothing here is needed day-to-day.
type Panel = "providers" | "savings" | "approvals" | "reports" | "activity";

const PANELS: { id: Panel; label: string }[] = [
  { id: "providers", label: "Providers" },
  { id: "savings", label: "Savings" },
  { id: "approvals", label: "Approvals" },
  { id: "activity", label: "Agent activity" },
  { id: "reports", label: "Reports" },
];

const KILL_SWITCH_HOTKEY = "CommandOrControl+Shift+Escape";

export default function App() {
  const [killFlash, setKillFlash] = useState(false);
  const [briefingDone, setBriefingDone] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [panel, setPanel] = useState<Panel>("providers");
  // null = still checking; false = brand-new user (no owner); true = onboarded.
  const [onboarded, setOnboarded] = useState<boolean | null>(null);
  // The bundled core takes ~10-13s to boot on a cold start. Don't mount anything
  // that talks to it until /healthz answers, or requests error out (the Splash is
  // only a visual cover). Once ready, decide onboarding.
  const [coreReady, setCoreReady] = useState(false);

  const onBriefingDone = useCallback(() => setBriefingDone(true), []);

  useEffect(() => {
    let alive = true;
    (async () => {
      const started = Date.now();
      while (alive) {
        try {
          const h = await health();
          if (h && (h as { status?: string }).status === "ok") break;
        } catch {
          /* core still booting */
        }
        if (Date.now() - started > 120_000) break; // give up after 2 min
        await new Promise((r) => setTimeout(r, 500));
      }
      if (!alive) return;
      setCoreReady(true);
      try {
        const id = await getIdentity();
        setOnboarded(Boolean(id.name));
      } catch {
        setOnboarded(false); // core up but couldn't read identity → run onboarding
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    const unlisten = listen<{ source: string }>("kill-switch", () => {
      setKillFlash(true);
      window.setTimeout(() => setKillFlash(false), 2500);
    });
    return () => {
      unlisten.then((f) => f());
    };
  }, []);

  useEffect(() => {
    register(KILL_SWITCH_HOTKEY, (event) => {
      if (event.state === "Pressed") killSwitch("global-hotkey").catch(() => undefined);
    }).catch(() => undefined);
    return () => {
      unregister(KILL_SWITCH_HOTKEY).catch(() => undefined);
    };
  }, []);

  const onKillClick = useCallback(() => {
    killSwitch("header-button").catch(() => undefined);
  }, []);

  return (
    <div className="app">
      <Splash />
      {coreReady && (
        <>
      {onboarded === false && <Onboarding onDone={() => setOnboarded(true)} />}
      {onboarded === true && !briefingDone && <Briefing onDone={onBriefingDone} />}

      <header className="topbar">
        <div className="brand">
          <img src="/jardo-logo.png" alt="" className="brand-mark" />
          <span className="brand-name">Jardo</span>
        </div>
        <div className="topbar-actions">
          <button className="more-btn" onClick={() => setDrawer(true)}>
            ⋯
          </button>
          <button
            className={`kill-btn ${killFlash ? "flash" : ""}`}
            onClick={onKillClick}
            title="Kill-switch  ⌘⇧⎋"
          >
            ⏻ Stop
          </button>
        </div>
      </header>

      {killFlash && (
        <div className="kill-banner" role="alert">
          KILL-SWITCH engaged — listening and terminal supervision halted.
        </div>
      )}

      <main className="content">
        <Jardo autoStart={briefingDone} />
      </main>

      {drawer && (
        <div className="drawer-scrim" onClick={() => setDrawer(false)}>
          <aside className="drawer" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-head">
              <span>More</span>
              <button className="link-btn" onClick={() => setDrawer(false)}>
                close
              </button>
            </div>
            <nav className="drawer-nav">
              {PANELS.map((p) => (
                <button
                  key={p.id}
                  className={panel === p.id ? "active" : ""}
                  onClick={() => setPanel(p.id)}
                >
                  {p.label}
                </button>
              ))}
            </nav>
            <div className="drawer-body">
              {panel === "providers" && <Settings />}
              {panel === "savings" && <Savings />}
              {panel === "approvals" && <Approvals />}
              {panel === "activity" && <Agents />}
              {panel === "reports" && <Reports />}
            </div>
          </aside>
        </div>
      )}
        </>
      )}
    </div>
  );
}
