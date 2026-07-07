import { useEffect, useState } from "react";
import {
  getProviders,
  setProvider,
  type ApiError,
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
      <h2>Providers</h2>
      <p className="settings-lead">
        Paste an inference key and Jardo starts using it. When more than one is
        ready it prefers the cheaper self-hosted option (AMD).
      </p>

      {error && (
        <div className="banner error" role="alert">
          {error}
        </div>
      )}

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
