import { useCallback, useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { register, unregister } from "@tauri-apps/plugin-global-shortcut";
import { StatusBar } from "./components/StatusBar";
import { Chat } from "./components/Chat";
import { Approvals } from "./components/Approvals";
import { Voice } from "./components/Voice";
import { Agents } from "./components/Agents";
import { Splash } from "./components/Splash";
import { Briefing } from "./components/Briefing";
import { killSwitch } from "./api";

type Tab = "chat" | "voice" | "agents" | "approvals";

// Global kill-switch hotkey (spec §7.3). Cmd+Shift+Escape on macOS.
// docs/vendor/tauri/plugin-global-shortcut.md
const KILL_SWITCH_HOTKEY = "CommandOrControl+Shift+Escape";

export default function App() {
  const [tab, setTab] = useState<Tab>("chat");
  const [killFlash, setKillFlash] = useState(false);
  const [briefingDone, setBriefingDone] = useState(false);

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
      {!briefingDone && <Briefing onDone={() => setBriefingDone(true)} />}
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
          className={tab === "agents" ? "tab active" : "tab"}
          onClick={() => setTab("agents")}
        >
          Agents
        </button>
        <button
          className={tab === "approvals" ? "tab active" : "tab"}
          onClick={() => setTab("approvals")}
        >
          Approvals
        </button>
      </nav>

      <main className="content">
        {tab === "chat" && <Chat />}
        {tab === "voice" && <Voice />}
        {tab === "agents" && <Agents />}
        {tab === "approvals" && <Approvals />}
      </main>
    </div>
  );
}
