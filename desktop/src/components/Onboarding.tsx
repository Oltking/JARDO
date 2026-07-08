import { useState } from "react";
import { setIdentity, setProvider, type ApiError } from "../api";
import { HalftoneAvatar } from "./HalftoneAvatar";

// First-run onboarding (new user, new computer). A shipped user has no terminal,
// so everything setup used to need (`jardo setup`) happens here: create the owner
// identity, then optionally add a model key. Voice model + mic permission warm up
// on their own after this. Shows only when there's no owner yet.
type Step = "name" | "key" | "done";

export function Onboarding({ onDone }: { onDone: () => void }) {
  const [step, setStep] = useState<Step>("name");
  const [name, setName] = useState("");
  const [pronoun, setPronoun] = useState<"sir" | "ma">("sir");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function saveName() {
    const n = name.trim();
    if (!n) {
      setError("Tell me what to call you.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await setIdentity(n, pronoun);
      setStep("key");
    } catch (e) {
      setError((e as ApiError).message || "Couldn't save that.");
    } finally {
      setBusy(false);
    }
  }

  async function saveKeyAndFinish() {
    const k = apiKey.trim();
    setBusy(true);
    setError(null);
    try {
      if (k) await setProvider("fireworks", k, null);
      onDone();
    } catch (e) {
      setError((e as ApiError).message || "Couldn't save the key.");
      setBusy(false);
    }
  }

  return (
    <div className="onboard">
      <div className="onboard-card">
        <HalftoneAvatar state="speaking" size={96} />

        {step === "name" && (
          <>
            <h1 className="onboard-title">Hi — I'm Jardo.</h1>
            <p className="onboard-sub">
              Your voice-first chief of staff. I supervise your coding agents,
              remember where you left off, and keep costs down. First, what should
              I call you?
            </p>
            <label className="onboard-field">
              <span>Your name</span>
              <input
                type="text"
                value={name}
                autoFocus
                placeholder="e.g. Ada"
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && saveName()}
              />
            </label>
            <div className="onboard-pronoun">
              <span>Address you as</span>
              <div className="onboard-toggle">
                {(["sir", "ma"] as const).map((p) => (
                  <button
                    key={p}
                    className={pronoun === p ? "active" : ""}
                    onClick={() => setPronoun(p)}
                  >
                    {p === "sir" ? "Sir" : "Ma"}
                  </button>
                ))}
              </div>
            </div>
            {error && <p className="onboard-error">{error}</p>}
            <button className="onboard-primary" disabled={busy} onClick={saveName}>
              {busy ? "Saving…" : "Continue"}
            </button>
          </>
        )}

        {step === "key" && (
          <>
            <h1 className="onboard-title">You're set — the first $1 is on me.</h1>
            <p className="onboard-sub">
              Skip this and start right away on your free trial; I'll think, talk, and
              supervise with no key needed. When it runs out, paste your own Fireworks
              key here (or later in Settings) to keep going at cost. Keys live in the
              macOS Keychain, never in a file.
            </p>
            <label className="onboard-field">
              <span>Fireworks API key (optional)</span>
              <input
                type="password"
                value={apiKey}
                placeholder="fw-…"
                onChange={(e) => setApiKey(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && saveKeyAndFinish()}
              />
            </label>
            <p className="onboard-hint">
              🎙️ I listen by voice — macOS will ask for microphone access the first
              time I do. Say yes and we're set.
            </p>
            {error && <p className="onboard-error">{error}</p>}
            <div className="onboard-actions">
              <button
                className="onboard-ghost"
                disabled={busy}
                onClick={() => {
                  setApiKey("");
                  void saveKeyAndFinish();
                }}
              >
                Skip
              </button>
              <button className="onboard-primary" disabled={busy} onClick={saveKeyAndFinish}>
                {busy ? "Saving…" : apiKey.trim() ? "Save & start" : "Start"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
