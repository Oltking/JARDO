import { useEffect, useState } from "react";
import { getSavings, type ApiError, type Savings as SavingsData } from "../api";

// Makes the cost-optimization value visible (spec §5): what you spent, what Jardo
// saved by routing to the cheapest model + caching, and how much ran free locally.
export function Savings() {
  const [data, setData] = useState<SavingsData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSavings()
      .then(setData)
      .catch((e: ApiError) => setError(e.message));
  }, []);

  if (error) return <div className="banner error">{error}</div>;
  if (!data) return <div className="empty">Loading…</div>;

  const usd = (n: number) => `$${n.toFixed(n < 1 ? 4 : 2)}`;

  return (
    <div className="savings">
      <h2>Savings</h2>
      <p className="settings-lead">
        Jardo routes every request to the cheapest capable model and serves repeats
        from cache — here's what that's saved you.
      </p>

      <div className="savings-grid">
        <div className="stat big ok">
          <span className="stat-num">{usd(data.saved_usd)}</span>
          <span className="stat-label">saved</span>
        </div>
        <div className="stat big">
          <span className="stat-num">{usd(data.spent_usd)}</span>
          <span className="stat-label">spent</span>
        </div>
        <div className="stat">
          <span className="stat-num">{data.local_pct}%</span>
          <span className="stat-label">ran free (local)</span>
        </div>
        <div className="stat">
          <span className="stat-num">{data.cache_hits}</span>
          <span className="stat-label">cache hits</span>
        </div>
        <div className="stat">
          <span className="stat-num">{data.tokens_saved.toLocaleString()}</span>
          <span className="stat-label">tokens saved by cache</span>
        </div>
        <div className="stat">
          <span className="stat-num">
            {data.local_requests + data.cloud_requests}
          </span>
          <span className="stat-label">requests routed</span>
        </div>
      </div>
    </div>
  );
}
