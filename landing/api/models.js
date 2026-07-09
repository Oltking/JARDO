// Discover which models this Fireworks account can reach. GET ?q=gemma to filter.
// Used to find the exact Gemma model id to wire into Jardo.
module.exports = async (req, res) => {
  const key = process.env.FIREWORKS_API_KEY;
  const base = process.env.FIREWORKS_BASE_URL || "https://api.fireworks.ai/inference/v1";
  if (!key) { res.status(500).json({ error: "FIREWORKS_API_KEY missing" }); return; }
  try {
    const r = await fetch(`${base}/models`, { headers: { Authorization: `Bearer ${key}` } });
    const data = await r.json();
    let models = Array.isArray(data && data.data) ? data.data.map((m) => m.id) : data;
    const q = String((req.query && req.query.q) || "").toLowerCase();
    if (q && Array.isArray(models)) models = models.filter((id) => String(id).toLowerCase().includes(q));
    res.status(200).json({ count: Array.isArray(models) ? models.length : null, models });
  } catch (e) {
    res.status(502).json({ error: String(e) });
  }
};
