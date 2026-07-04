import { useCallback, useEffect, useState } from "react";
import { decideApproval, getApprovals, type Approval } from "../api";

// Permission / Approval UI (spec §6.5) — the desktop realization of the
// Permission Broker and the Phase 5 demo centerpiece. Polls GET /approvals and
// lets the owner Approve / Deny each pending escalation.
export function Approvals() {
  const [items, setItems] = useState<Approval[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await getApprovals();
      setItems(list);
      setError(null);
    } catch {
      setError("Could not reach the core to load pending approvals.");
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, 4000);
    return () => window.clearInterval(id);
  }, [refresh]);

  async function decide(id: string, approve: boolean) {
    setPendingId(id);
    try {
      await decideApproval(id, approve);
      await refresh();
    } catch {
      setError("Failed to submit the decision. Check the core connection.");
    } finally {
      setPendingId(null);
    }
  }

  function sevClass(sev: string) {
    const s = sev.toLowerCase();
    if (s === "critical") return "sev critical";
    if (s === "high") return "sev high";
    if (s === "medium") return "sev medium";
    return "sev low";
  }

  return (
    <div className="approvals">
      <div className="approvals-head">
        <h2>Pending approvals</h2>
        <button className="ghost" onClick={refresh}>
          Refresh
        </button>
      </div>

      {error && (
        <div className="banner error" role="alert">
          {error}
        </div>
      )}

      {items.length === 0 && !error && (
        <div className="empty">
          No pending escalations. When a sub-agent requests a gated action, it
          appears here for your decision.
        </div>
      )}

      <ul className="approval-list">
        {items.map((a) => (
          <li key={a.id} className="approval-card">
            <div className="approval-top">
              <span className={sevClass(a.severity)}>{a.severity}</span>
              <span className="action-type">{a.action_type}</span>
              <span className="created">
                {new Date(a.created_at).toLocaleString()}
              </span>
            </div>
            <div className="approval-body">
              <div>
                <strong>Actor:</strong> {a.actor}
              </div>
              <div>
                <strong>Target:</strong> <code>{a.target}</code>
              </div>
              <div>
                <strong>Goal:</strong> {a.stated_goal}
              </div>
            </div>
            <div className="approval-actions">
              <button
                className="approve"
                disabled={pendingId === a.id}
                onClick={() => decide(a.id, true)}
              >
                Approve
              </button>
              <button
                className="deny"
                disabled={pendingId === a.id}
                onClick={() => decide(a.id, false)}
              >
                Deny
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
