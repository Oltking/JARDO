// Report a device's remaining Jardo free trial. GET ?device=<id>.
const FREE_TRIAL_USD = parseFloat(process.env.FREE_TRIAL_USD || "1");
const KV_URL = process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL;
const KV_TOKEN = process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN;

module.exports = async (req, res) => {
  const device = String((req.query && req.query.device) || "").slice(0, 128);
  let spent = 0;
  if (device && KV_URL && KV_TOKEN) {
    try {
      const r = await fetch(`${KV_URL}/get/jardo:spend:${encodeURIComponent(device)}`, {
        headers: { Authorization: `Bearer ${KV_TOKEN}` },
      });
      const v = (await r.json()).result;
      spent = v ? parseFloat(v) : 0;
    } catch {
      /* best-effort */
    }
  }
  res.status(200).json({
    trial_usd: FREE_TRIAL_USD,
    spent_usd: Number(spent.toFixed(4)),
    remaining_usd: Number(Math.max(0, FREE_TRIAL_USD - spent).toFixed(4)),
  });
};
