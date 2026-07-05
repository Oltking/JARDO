import { useEffect, useState } from "react";
import {
  generateReport,
  listReports,
  type ApiError,
  type Report,
} from "../api";

// Reports inbox (spec §4.4): read the hourly/daily/weekly rollups Jardo
// generates, and produce a fresh one on demand.
const PERIODS = ["hourly", "daily", "weekly"] as const;

export function Reports() {
  const [reports, setReports] = useState<Report[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      setReports(await listReports());
      setError(null);
    } catch (e) {
      setError((e as ApiError).message || "Couldn't load reports.");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function generate(period: string) {
    setBusy(period);
    try {
      await generateReport(period);
      await refresh();
    } catch (e) {
      setError((e as ApiError).message || "Couldn't generate the report.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="reports">
      <div className="reports-head">
        <h2>Reports</h2>
        <div className="report-actions">
          {PERIODS.map((p) => (
            <button
              key={p}
              className="ghost"
              disabled={busy !== null}
              onClick={() => generate(p)}
            >
              {busy === p ? "…" : `New ${p}`}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="banner error" role="alert">
          {error}
        </div>
      )}

      {reports.length === 0 && !error && (
        <div className="empty">
          No reports yet. Generate one above, or Jardo will write them on schedule
          (hourly, daily at 7am, weekly on Mondays).
        </div>
      )}

      <div className="report-list">
        {reports.map((r) => (
          <article key={r.id} className="report-card">
            <header className="report-card-head">
              <span className={`report-period ${r.period}`}>{r.period}</span>
              <span className="report-date">
                {new Date(r.created_at).toLocaleString()}
              </span>
            </header>
            <pre className="report-body">{r.body}</pre>
          </article>
        ))}
      </div>
    </div>
  );
}
