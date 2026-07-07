import { useCallback, useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { register, unregister } from "@tauri-apps/plugin-global-shortcut";
import { StatusBar } from "./components/StatusBar";
import { Chat } from "./components/Chat";
import { Approvals } from "./components/Approvals";
import { Voice } from "./components/Voice";
import { Agents } from "./components/Agents";
import { Reports } from "./components/Reports";
import { Build } from "./components/Build";
import { Splash } from "./components/Splash";
import { Briefing } from "./components/Briefing";
import { Settings } from "./components/Settings";
import { killSwitch } from "./api";

type Tab = "chat" | "voice" | "build" | "agents" | "reports" | "approvals" | "settings";

// Does the spoken goal look like a "build something" request?
function isBuildRequest(goal: string): boolean {
  return /\b(build|create|make|develop|set\s?up|scaffold)\b/i.test(goal) &&
    /\b(website|site|web\s?app|app|application|api|tool|page|bot|script|game|dashboard|landing)\b/i.test(goal);
}

// Global kill-switch hotkey (spec §7.3). Cmd+Shift+Escape on macOS.
// docs/vendor/tauri/plugin-global-shortcut.md
const KILL_SWITCH_HOTKEY = "CommandOrControl+Shift+Escape";

export default function App() {
  const [tab, setTab] = useState<Tab>("chat");
  const [killFlash, setKillFlash] = useState(false);
  const [briefingDone, setBriefingDone] = useState(false);
  const [buildSeed, setBuildSeed] = useState<string | undefined>(undefined);

  // When the launch briefing captures a build goal, roll straight into the
  // Build interview instead of dropping into an empty chat.
  const onBriefingDone = useCallback((goal?: string) => {
    setBriefingDone(true);
    if (goal && isBuildRequest(goal)) {
      setBuildSeed(goal);
      setTab("build");
    }
  }, []);

  // Visual acknowledgement whenever the kill-switch fires, from any source
  // (tray menu, global hotkey, or the header button). The Rust side emits a
  // `kill-switch` event so all surfaces stay in sync.
  useEffect(() => {
    const unlisten = listen<{ source: string }>("kill-switch", (event) => {
      // eslint-disable-next-line no-console
      console.warn("[Jardo] kill-switch fired from", event.payload?.source);
      setKillFlash(true);
      window.setTimeout(() => setKillFlash(false), 2500);
    });
    return () => {
      unlisten.then((f) => f());
    };
  }, []);

  // Register the global shortcut. The plugin's JS `register` handler runs in the
  // webview; it calls the same Rust stub so hotkey + tray share one code path.
  useEffect(() => {
    let active = true;
    register(KILL_SWITCH_HOTKEY, (event) => {
      if (event.state === "Pressed") {
        killSwitch("global-hotkey").catch(() => undefined);
      }
    }).catch((e) => {
      // eslint-disable-next-line no-console
      console.error("Failed to register kill-switch hotkey:", e);
    });
    return () => {
      active = false;
      void active;
      unregister(KILL_SWITCH_HOTKEY).catch(() => undefined);
    };
  }, []);

  const onKillClick = useCallback(() => {
    killSwitch("header-button").catch(() => undefined);
  }, []);

  return (
    <div className="app">
      <Splash />
      {!briefingDone && <Briefing onDone={onBriefingDone} />}
      <StatusBar
        onKillSwitch={onKillClick}
        hotkeyLabel="⌘⇧⎋"
        killFlash={killFlash}
      />

      {killFlash && (
        <div className="kill-banner" role="alert">
          KILL-SWITCH engaged — synthetic input halted (stub; real halting in
          Phase 7).
        </div>
      )}

      <nav className="tabs">
        <button
          className={tab === "chat" ? "tab active" : "tab"}
          onClick={() => setTab("chat")}
        >
          Chat
        </button>
        <button
          className={tab === "voice" ? "tab active" : "tab"}
          onClick={() => setTab("voice")}
        >
          Voice
        </button>
        <button
          className={tab === "build" ? "tab active" : "tab"}
          onClick={() => setTab("build")}
        >
          Build
        </button>
        <button
          className={tab === "agents" ? "tab active" : "tab"}
          onClick={() => setTab("agents")}
        >
          Agents
        </button>
        <button
          className={tab === "reports" ? "tab active" : "tab"}
          onClick={() => setTab("reports")}
        >
          Reports
        </button>
        <button
          className={tab === "approvals" ? "tab active" : "tab"}
          onClick={() => setTab("approvals")}
        >
          Approvals
        </button>
        <button
          className={tab === "settings" ? "tab active" : "tab"}
          onClick={() => setTab("settings")}
        >
          Settings
        </button>
      </nav>

      <main className="content">
        {tab === "chat" && <Chat />}
        {tab === "build" && <Build seed={buildSeed} />}
        {tab === "agents" && <Agents />}
        {tab === "reports" && <Reports />}
        {tab === "approvals" && <Approvals />}
        {tab === "settings" && <Settings />}
        {/* Always mounted so listening stays alive across tabs; auto-starts once
            the launch briefing hands off (always-on voice). */}
        <Voice autoStart={briefingDone} hidden={tab !== "voice"} />
      </main>
    </div>
  );
}
