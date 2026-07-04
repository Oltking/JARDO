import { useEffect, useState } from "react";
import {
  codingDecisions,
  codingTools,
  type AgentDecision,
  type ApiError,
  type CodingInventory,
} from "../api";

// Agents panel (owner scope): the coding environments Jardo can operate, and a
// live feed of the yes/no permission decisions it makes for coding agents/tools
// (spec §4.3, §7.2). Decisions come from the audit log; refreshes every 4s.
export function Agents() {
  const [tools, setTools] = useState<CodingInventory | null>(null);
  const [decisions, setDecisions] = useState<AgentDecision[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    codingTools().then(setTools).catch((e: ApiError) => setError(e.message));
    const load = () =>
      codingDecisions().then(setDecisions).catch(() => undefined);
    load();
    const id = window.setInterval(load, 4000);
    return () => window.clearInterval(id);
  }, []);

  function answered(d: AgentDecision): string | null {
    if (d.event !== "prompt.answered") return null;
    return String(d.detail.answered ?? "");
  }
  function verdict(d: AgentDecision): string {
    return String(d.detail.verdict ?? "");
  }
  function subject(d: AgentDecision): string {
    return String(
      d.detail.action || d.detail.target || d.detail.prompt || "(action)"
    );
  }
  const isYes = (t: string | null) => t === "y" || t === "yes" || t === "1";

  return (
    <div className="agents">
      {error && (
        <div className="banner error" role="alert">
          {error}
        </div>
      )}

      {tools && (
        <div className="tools-grid">
          <ToolRow label="Editors" items={Object.keys(tools.editors)} />
          <ToolRow label="Terminals" items={tools.terminals} />
          <ToolRow label="Shells" items={Object.keys(tools.shells)} />
          <ToolRow label="Coding agents" items={Object.values(tools.agents)} />
        </div>
      )}

      <h3 className="section">Recent decisions</h3>
      {decisions.length === 0 && (
        <div className="empty">
          No agent decisions yet. When a coding agent asks "run this? (y/n)",
          Jardo answers per policy and it appears here.
        </div>
      )}
      <div className="decisions">
        {decisions.map((d, i) => {
          const a = answered(d);
          return (
            <div key={i} className="decision">
              {a !== null ? (
                <span className={`badge ${isYes(a) ? "yes" : "no"}`}>
                  {isYes(a) ? "allowed" : "declined"}
                </span>
              ) : (
                <span className="badge review">reviewed</span>
              )}
              <span className="decision-subject">{subject(d)}</span>
              <span className="decision-meta">
                {verdict(d)} · {new Date(d.ts).toLocaleTimeString()}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ToolRow({ label, items }: { label: string; items: string[] }) {
  return (
    <div className="tool-row">
      <span className="tool-label">{label}</span>
      <span className="tool-items">
        {items.length ? items.join(", ") : <span className="dim">none</span>}
      </span>
    </div>
  );
}
