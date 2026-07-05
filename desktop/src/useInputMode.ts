import { useEffect, useState } from "react";

// App-wide input preference: voice is the default everywhere; the user can
// switch to text and the choice persists (and applies across surfaces).
export type InputMode = "voice" | "text";

const KEY = "jardo.inputMode";

export function useInputMode() {
  const [mode, setMode] = useState<InputMode>(
    () => (localStorage.getItem(KEY) as InputMode) || "voice"
  );
  useEffect(() => {
    localStorage.setItem(KEY, mode);
    // notify other mounted surfaces so a switch applies app-wide
    window.dispatchEvent(new CustomEvent("jardo-inputmode", { detail: mode }));
  }, [mode]);
  useEffect(() => {
    const onChange = (e: Event) => {
      const next = (e as CustomEvent).detail as InputMode;
      setMode((cur) => (cur === next ? cur : next));
    };
    window.addEventListener("jardo-inputmode", onChange);
    return () => window.removeEventListener("jardo-inputmode", onChange);
  }, []);
  return [mode, setMode] as const;
}
