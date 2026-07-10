import { useEffect, useState } from "react";
import {
  getIdentity,
  getLanguages,
  infraStatus,
  type InfraStatus,
  getProviders,
  getProjectsRoot,
  getTerminalChoice,
  setIdentity,
  setProvider,
  setProjectsRoot,
  setTerminalChoice,
  type ApiError,
  type LanguageOption,
  type ProviderStatus,
} from "../api";

// Settings → Providers (spec §5). Paste a Fireworks key and/or point Jardo at an
// AMD (vLLM / MI300X) endpoint + key. Jardo uses whichever is ready, preferring
// the cheaper self-hosted one. Keys are stored in the OS Keychain, never echoed
// back — the panel only ever shows whether a key is present.
export function Settings() {
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [active, setActive] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [keyDraft, setKeyDraft] = useState<Record<string, string>>({});
  const [urlDraft, setUrlDraft] = useState<Record<string, string>>({});
  const [name, setName] = useState("");
  const [pronoun, setPronoun] = useState("sir");
  const [infra, setInfra] = useState<InfraStatus | null>(null);
  const [language, setLanguage] = useState("en");
  const [languages, setLanguages] = useState<LanguageOption[]>([
    { code: "en", name: "English", native: "English" },
  ]);
  const [root, setRoot] = useState<string | null>(null);
  const [savedName, setSavedName] = useState(false);
  const [terminal, setTerminal] = useState("terminal");

  async function pickTerminal(value: string) {
    setTerminal(value);
    try {
      await setTerminalChoice(value);
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  async function saveIdentity() {
    setError(null);
    try {
      const id = await setIdentity(name.trim() || null, pronoun, language);
      setName(id.name ?? "");
      if (id.language) setLanguage(id.language);
      // Tell the running app to switch language live (no restart needed).
      window.dispatchEvent(
        new CustomEvent("jardo-language", { detail: id.language || "en" }));
      setSavedName(true);
      setTimeout(() => setSavedName(false), 1500);
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  async function pickRoot() {
    setError(null);
    try {
      const r = await setProjectsRoot(null); // null → native folder chooser
      setRoot(r.root);
    } catch (e) {
      const err = e as ApiError;
      if (err.status !== 409) setError(err.message); // 409 = cancelled
    }
  }

  async function refresh() {
    try {
      const info = await getProviders();
      setProviders(info.providers);
      setActive(info.active);
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  useEffect(() => {
    refresh();
    getIdentity()
      .then((id) => {
        setName(id.name ?? "");
        if (id.pronoun_style) setPronoun(id.pronoun_style);
        if (id.language) setLanguage(id.language);
      })
      .catch(() => undefined);
    getLanguages()
      .then((r) => r.languages.length && setLanguages(r.languages))
      .catch(() => undefined);
    infraStatus().then((s) => s && setInfra(s)).catch(() => undefined);
    getProjectsRoot()
      .then((r) => setRoot(r.root))
      .catch(() => undefined);
    getTerminalChoice()
      .then((t) => setTerminal(t.terminal))
      .catch(() => undefined);
  }, []);

  async function save(name: string, needsUrl: boolean) {
    setSaving(name);
    setError(null);
    try {
      const info = await setProvider(
        name,
        keyDraft[name]?.trim() || null,
        needsUrl ? urlDraft[name]?.trim() ?? null : null
      );
      setProviders(info.providers);
      setActive(info.active);
      setKeyDraft((d) => ({ ...d, [name]: "" }));
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setSaving(null);
    }
  }

  return (
    <div className="settings">
      {error && (
        <div className="banner error" role="alert">
          {error}
        </div>
      )}

      {infra && (
        <>
          <h2>Compute</h2>
          <div className="compute-status">
            <span className={`serving-badge ${infra.backend}`}>
              {infra.backend === "amd"
                ? "⚡ AMD Gemma"
                : infra.backend === "fireworks"
                ? "Fireworks AI"
                : "Local model"}
            </span>
            <span className="settings-hint" style={{ margin: 0 }}>
              {infra.backend === "amd"
                ? `Running on ${infra.accelerator || "AMD Instinct GPU"} — free, doesn't touch your trial.`
                : infra.own_key
                ? "Using your own key."
                : infra.trial_remaining != null
                ? `Free trial: $${infra.trial_remaining.toFixed(2)} of $${(infra.trial_usd ?? 1).toFixed(2)} left.`
                : "On the free trial."}
            </span>
          </div>
        </>
      )}

      <h2>You</h2>
      <p className="settings-lead">What should Jardo call you?</p>
      <div className="provider-card">
        <label className="field">
          <span>Name</span>
          <input
            type="text"
            autoComplete="off"
            placeholder="e.g. Alex"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label className="field">
          <span>Honorific</span>
          <select
            value={pronoun}
            onChange={(e) => setPronoun(e.target.value)}
            className="settings-select"
          >
            <option value="sir">sir</option>
            <option value="ma">ma’am</option>
          </select>
        </label>
        <label className="field">
          <span>Voice language</span>
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            className="settings-select"
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
          <p className="settings-hint">
            I'll listen and reply in {languages.find((l) => l.code === language)?.name || "your language"}.
            My reasoning stays in English for accuracy. First switch downloads a
            multilingual voice model once.
          </p>
        )}
        <button className="primary" onClick={saveIdentity}>
          {savedName ? "Saved ✓" : "Save"}
        </button>
      </div>

      <h2>Projects folder</h2>
      <p className="settings-lead">
        The folder that holds all your projects. Jardo remembers it, lists your
        projects from it, and saves new ones inside.
      </p>
      <div className="provider-card">
        <div className="root-row">
          <code className="root-path">{root || "not set"}</code>
          <button className="primary" onClick={pickRoot}>
            {root ? "Change…" : "Choose…"}
          </button>
        </div>
      </div>

      <h2>Terminal</h2>
      <p className="settings-lead">
        Which terminal you run your coding agent in — so Jardo can read it and
        answer its prompts.
      </p>
      <div className="provider-card">
        <label className="field">
          <span>Supervise in</span>
          <select
            value={terminal}
            onChange={(e) => pickTerminal(e.target.value)}
            className="settings-select"
          >
            <option value="terminal">Terminal.app</option>
            <option value="iterm">iTerm2</option>
            <option value="warp">Warp (via hook)</option>
            <option value="vscode">VS Code (via hook)</option>
          </select>
        </label>
        {(terminal === "warp" || terminal === "vscode") && (
          <p className="settings-note">
            Warp and VS Code can't be read directly — supervise Claude via the
            hook: run <code>jardo hook install</code>. It works in any terminal.
          </p>
        )}
      </div>

      <h2>Providers</h2>
      <p className="settings-lead">
        Every new install includes a small amount of <strong>free trial compute</strong> on us —
        Fireworks AI and AMD-hosted inference, so Jardo thinks and supervises out of the box.
        When that runs out, <em>adding your own key is optional</em>: paste a Fireworks or AMD
        Developer Cloud key below to keep cloud inference on your account, or continue with
        Ollama locally at zero cost. Jardo prefers the cheaper self-hosted option (AMD) when
        both are configured.
      </p>
      <div className="provider-card trial-note">
        <p>
          <strong>Your keys, your choice.</strong> Keys live in the macOS Keychain — never in files.
          Trial compute is a gift to get you started; your own Fireworks or AMD endpoint means
          you control spend and limits. Skip cloud entirely and Jardo still listens, supervises,
          and remembers — on-device.
        </p>
      </div>

      {providers.map((p) => {
        const needsUrl = p.name === "amd";
        const isActive = active.includes(p.name);
        return (
          <div className="provider-card" key={p.name}>
            <div className="provider-head">
              <span className="provider-name">{p.label}</span>
              <span className={`pill ${p.ready ? "ok" : "off"}`}>
                {p.ready ? (isActive ? "active" : "ready") : "not configured"}
              </span>
            </div>

            <label className="field">
              <span>API key {p.has_key && <em>(set — paste to replace)</em>}</span>
              <input
                type="password"
                autoComplete="off"
                placeholder={p.has_key ? "•••••••• stored in Keychain" : "paste key"}
                value={keyDraft[p.name] ?? ""}
                onChange={(e) =>
                  setKeyDraft((d) => ({ ...d, [p.name]: e.target.value }))
                }
              />
            </label>

            {needsUrl && (
              <label className="field">
                <span>Endpoint (OpenAI-compatible vLLM URL)</span>
                <input
                  type="text"
                  autoComplete="off"
                  placeholder="http://your-mi300x:8000/v1"
                  value={urlDraft[p.name] ?? p.base_url}
                  onChange={(e) =>
                    setUrlDraft((d) => ({ ...d, [p.name]: e.target.value }))
                  }
                />
              </label>
            )}

            <button
              className="primary"
              disabled={saving === p.name}
              onClick={() => save(p.name, needsUrl)}
            >
              {saving === p.name ? "Saving…" : "Save"}
            </button>
          </div>
        );
      })}
    </div>
  );
}
