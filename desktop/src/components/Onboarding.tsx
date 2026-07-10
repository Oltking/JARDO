import { useEffect, useState } from "react";
import {
  getLanguages,
  setIdentity,
  setProvider,
  type ApiError,
  type LanguageOption,
} from "../api";
import { HalftoneAvatar } from "./HalftoneAvatar";

// First-run onboarding (new user, new computer). A shipped user has no terminal,
// so everything setup used to need (`jardo setup`) happens here: create the owner
// identity, then optionally add a model key. Voice model + mic permission warm up
// on their own after this. Shows only when there's no owner yet.
type Step = "name" | "permissions" | "key" | "done";

export function Onboarding({ onDone }: { onDone: () => void }) {
  const [step, setStep] = useState<Step>("name");
  const [name, setName] = useState("");
  const [pronoun, setPronoun] = useState<"sir" | "ma" | "neutral">("sir");
  const [language, setLanguage] = useState("en");
  const [languages, setLanguages] = useState<LanguageOption[]>([
    { code: "en", name: "English", native: "English" },
  ]);

  useEffect(() => {
    getLanguages()
      .then((r) => r.languages.length && setLanguages(r.languages))
      .catch(() => undefined);
  }, []);
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
      await setIdentity(n, pronoun, language);
      setStep("permissions");
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
                {(["sir", "ma", "neutral"] as const).map((p) => (
                  <button
                    key={p}
                    className={pronoun === p ? "active" : ""}
                    onClick={() => setPronoun(p)}
                  >
                    {p === "sir" ? "Sir" : p === "ma" ? "Ma" : "Just my name"}
                  </button>
                ))}
              </div>
            </div>
            <label className="onboard-field">
              <span>Talk to me in</span>
              <select
                className="onboard-select"
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
              >
                {languages.map((l) => (
                  <option key={l.code} value={l.code}>
                    {l.native}
                    {l.native !== l.name ? ` (${l.name})` : ""}
                  </option>
                ))}
              </select>
            </label>
            {language !== "en" && (
              <p className="onboard-hint">
                🌍 I'll listen and reply in your language — my thinking stays in
                English under the hood for accuracy.
              </p>
            )}
            {error && <p className="onboard-error">{error}</p>}
            <button className="onboard-primary" disabled={busy} onClick={saveName}>
              {busy ? "Saving…" : "Continue"}
            </button>
          </>
        )}

        {step === "permissions" && (
          <>
            <h1 className="onboard-title">A couple of macOS permissions.</h1>
            <p className="onboard-sub">
              So nothing surprises you later, here's what I'll ask for — and when.
              You grant each with one click when it comes up.
            </p>
            <ul className="onboard-perms">
              <li>
                <span className="onboard-perm-icon">🎙️</span>
                <span>
                  <strong>Microphone</strong> — the first time I listen, so we can
                  talk. Asked right after this.
                </span>
              </li>
              <li>
                <span className="onboard-perm-icon">⌨️</span>
                <span>
                  <strong>Accessibility &amp; Terminal control</strong> — only when
                  you first ask me to <em>supervise</em> a coding agent, so I can
                  read the terminal and press the answers.
                </span>
              </li>
            </ul>
            <p className="onboard-hint">
              I never act without you seeing it, and there's always a kill-switch
              (⌘⇧⎋).
            </p>
            <div className="onboard-actions">
              <button className="onboard-ghost" onClick={() => setStep("name")}>
                Back
              </button>
              <button className="onboard-primary" onClick={() => setStep("key")}>
                Got it
              </button>
            </div>
          </>
        )}

        {step === "key" && (
          <>
            <h1 className="onboard-title">You're set — the first $1 is on me.</h1>
            <p className="onboard-sub">
              Skip this and start right away on your free trial; I'll think, talk, and
              supervise with no key needed. When it runs out, adding your own key is
              optional: paste Fireworks here or add Fireworks/AMD Developer Cloud later
              in Settings for cloud inference, or keep using local Ollama. Keys live in
              the macOS Keychain, never in a file.
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
                onClick={() => setStep("permissions")}
              >
                Back
              </button>
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
