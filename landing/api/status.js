// Live infrastructure status, so the app/landing can show what's actually serving.
// Reports whether the AMD Instinct droplet (ROCm/vLLM) is reachable, else Fireworks.
const AMD_BASE_URL = (process.env.AMD_BASE_URL || "").replace(/\/$/, "");
const AMD_API_KEY = process.env.AMD_API_KEY || "";

module.exports = async (req, res) => {
  let amdUp = false;
  if (AMD_BASE_URL) {
    try {
      const r = await fetch(`${AMD_BASE_URL}/models`, {
        headers: AMD_API_KEY ? { Authorization: `Bearer ${AMD_API_KEY}` } : {},
        signal: AbortSignal.timeout(4000),
      });
      // Must be an actual OpenAI-style models list — not a Jupyter/HTML page from a
      // misconfigured URL. A 200 that returns HTML (login/notebook) is NOT "online".
      const ct = r.headers.get("content-type") || "";
      if (r.ok && ct.includes("application/json")) {
        const j = await r.json().catch(() => null);
        amdUp = Boolean(j && (Array.isArray(j.data) || j.object === "list"));
      }
    } catch {
      amdUp = false;
    }
  }
  res.setHeader("Cache-Control", "no-store");
  res.status(200).json({
    backend: amdUp ? "amd" : "fireworks",
    amd_configured: Boolean(AMD_BASE_URL),
    amd_online: amdUp,
    accelerator: amdUp ? "AMD Instinct GPU · ROCm · vLLM" : "Fireworks AI (Gemma)",
    model: "Gemma",
  });
};
