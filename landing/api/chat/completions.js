// Jardo hosted inference proxy (Vercel serverless, Node runtime).
//
// The Fireworks key lives ONLY here, in Vercel env, never in the app. The app
// calls this endpoint instead of Fireworks directly; we forward the request with
// our key and meter each device against a small free trial. This is what lets
// Jardo work out-of-the-box with no signup and no key on the user's side.
//
// Env (set in Vercel → Project → Settings → Environment Variables):
//   FIREWORKS_API_KEY   (required)  your Fireworks key
//   FIREWORKS_BASE_URL  default https://api.fireworks.ai/inference/v1
//   FREE_TRIAL_USD      default "1"     per-device trial budget (change anytime)
//   USD_PER_1M_TOKENS   default "0.30"  blended price used to meter spend
//   GLOBAL_CAP_USD      optional        overall safety ceiling across all devices
//   JARDO_APP_SECRET    optional        shared secret the app must send (soft gate)
//   UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN  optional durable metering
//
// Without Upstash configured, metering is best-effort (per warm instance), fine
// for a demo; add Upstash for real per-device persistence.

const FIREWORKS_BASE_URL =
  process.env.FIREWORKS_BASE_URL || "https://api.fireworks.ai/inference/v1";
// AMD Instinct droplet (vLLM on ROCm), OpenAI-compatible. When set, we serve from
// AMD first and fall back to Fireworks if it is unreachable, so users always work,
// and self-hosted AMD compute doesn't count against the free trial.
const AMD_BASE_URL = (process.env.AMD_BASE_URL || "").replace(/\/$/, "");
const AMD_API_KEY = process.env.AMD_API_KEY || "";
const AMD_MODEL = process.env.AMD_MODEL || ""; // vLLM --served-model-name
const FREE_TRIAL_USD = parseFloat(process.env.FREE_TRIAL_USD || "1");
const USD_PER_1M_TOKENS = parseFloat(process.env.USD_PER_1M_TOKENS || "0.30");
const GLOBAL_CAP_USD = process.env.GLOBAL_CAP_USD
  ? parseFloat(process.env.GLOBAL_CAP_USD)
  : null;

// ---- metering store: Upstash REST if configured, else in-memory ------------
// Accept either manual Upstash vars or the names Vercel's Marketplace integration
// injects (KV_REST_API_*), so both setup paths work with no code change.
const KV_URL = process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL;
const KV_TOKEN = process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN;
const memSpend = new Map(); // deviceId -> usd (per warm instance)

async function kv(path) {
  const r = await fetch(`${KV_URL}/${path}`, {
    headers: { Authorization: `Bearer ${KV_TOKEN}` },
  });
  if (!r.ok) throw new Error(`kv ${r.status}`);
  return (await r.json()).result;
}

async function getSpend(device) {
  if (KV_URL && KV_TOKEN) {
    const v = await kv(`get/jardo:spend:${encodeURIComponent(device)}`);
    return v ? parseFloat(v) : 0;
  }
  return memSpend.get(device) || 0;
}

async function addSpend(device, usd) {
  if (KV_URL && KV_TOKEN) {
    await kv(`incrbyfloat/jardo:spend:${encodeURIComponent(device)}/${usd}`);
    if (GLOBAL_CAP_USD != null) await kv(`incrbyfloat/jardo:spend:__global__/${usd}`);
    return;
  }
  memSpend.set(device, (memSpend.get(device) || 0) + usd);
}

async function globalSpend() {
  if (GLOBAL_CAP_USD == null) return 0;
  if (KV_URL && KV_TOKEN) {
    const v = await kv("get/jardo:spend:__global__");
    return v ? parseFloat(v) : 0;
  }
  let sum = 0;
  for (const v of memSpend.values()) sum += v;
  return sum;
}

module.exports = async (req, res) => {
  if (req.method !== "POST") {
    res.status(405).json({ error: "POST only" });
    return;
  }
  const key = process.env.FIREWORKS_API_KEY;
  if (!key) {
    res.status(500).json({ error: "proxy not configured (FIREWORKS_API_KEY missing)" });
    return;
  }
  // Soft gate: if a shared app secret is set, require it.
  if (process.env.JARDO_APP_SECRET) {
    if (req.headers["x-jardo-app"] !== process.env.JARDO_APP_SECRET) {
      res.status(401).json({ error: "unauthorized" });
      return;
    }
  }
  const device = String(req.headers["x-jardo-device"] || "").slice(0, 128);
  if (!device) {
    res.status(400).json({ error: "missing x-jardo-device" });
    return;
  }

  // Trial + global caps checked before spending.
  const spent = await getSpend(device);
  if (spent >= FREE_TRIAL_USD) {
    res.status(402).json({
      error: "trial_exhausted",
      message:
        "Your free Jardo trial compute is used up. Add your own Fireworks or AMD " +
        "Developer Cloud key in Settings → Providers for cloud inference, or keep " +
        "using Jardo locally with Ollama.",
      trial_usd: FREE_TRIAL_USD,
      spent_usd: Number(spent.toFixed(4)),
    });
    return;
  }
  if (GLOBAL_CAP_USD != null && (await globalSpend()) >= GLOBAL_CAP_USD) {
    res.status(503).json({ error: "capacity", message: "Free trial capacity reached, try later." });
    return;
  }

  const body = typeof req.body === "string" ? JSON.parse(req.body || "{}") : req.body || {};

  // 1) Try the AMD Instinct droplet first (self-hosted, ROCm/vLLM) when configured.
  let text = null;
  let served = "fireworks";
  if (AMD_BASE_URL) {
    try {
      const amdBody = AMD_MODEL ? { ...body, model: AMD_MODEL } : body;
      const r = await fetch(`${AMD_BASE_URL}/chat/completions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(AMD_API_KEY ? { Authorization: `Bearer ${AMD_API_KEY}` } : {}),
        },
        body: JSON.stringify(amdBody),
        signal: AbortSignal.timeout(55000), // transformers is slower than vLLM; stay under Vercel's 60s
      });
      if (r.ok) {
        text = await r.text();
        served = "amd";
      }
    } catch {
      /* droplet down/slow → fall back to Fireworks below */
    }
  }

  // 2) Fireworks (Gemma), the cloud tier and the fallback.
  if (text === null) {
    let upstream;
    try {
      upstream = await fetch(`${FIREWORKS_BASE_URL}/chat/completions`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${key}` },
        body: JSON.stringify(body),
      });
    } catch (e) {
      res.status(502).json({ error: "upstream_unreachable", message: String(e) });
      return;
    }
    text = await upstream.text();
    if (!upstream.ok) {
      res.status(upstream.status).send(text);
      return;
    }
  }

  res.setHeader("x-jardo-served-by", served);
  res.setHeader("x-jardo-trial-usd", String(FREE_TRIAL_USD));
  // Meter only Fireworks usage. AMD self-hosted compute is free, so it does not
  // burn the trial (and it's the cheaper-tier cost story).
  let remaining = FREE_TRIAL_USD - spent;
  if (served === "fireworks") {
    try {
      const tokens = JSON.parse(text)?.usage?.total_tokens || 0;
      const cost = (tokens / 1_000_000) * USD_PER_1M_TOKENS;
      await addSpend(device, cost);
      remaining = Math.max(0, FREE_TRIAL_USD - (spent + cost));
    } catch {
      /* keep the answer even if usage is unparseable */
    }
  }
  res.setHeader("x-jardo-trial-remaining", remaining.toFixed(4));
  res.setHeader("Content-Type", "application/json");
  res.status(200).send(text);
};
