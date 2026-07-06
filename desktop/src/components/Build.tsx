import { useEffect, useRef, useState } from "react";
import {
  buildIntake,
  buildRun,
  voiceSay,
  voiceTranscribe,
  type ApiError,
  type BuildRunResponse,
} from "../api";
import { useInputMode } from "../useInputMode";

interface Turn {
  role: "you" | "jardo";
  text: string;
}

// Conversational build front-door: say what to build, Jardo interviews you
// (voice-first), then launches the agent and shows the result.
export function Build({ seed }: { seed?: string }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [agent, setAgent] = useState("claude");
  const [brief, setBrief] = useState<string | null>(null);
  const [directory, setDirectory] = useState("~/jardo-projects/new");
  const [phase, setPhase] = useState<"idle" | "listening" | "thinking" | "speaking">("idle");
  const [runResult, setRunResult] = useState<BuildRunResponse | null>(null);
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useInputMode();
  const scrollRef = useRef<HTMLDivElement>(null);
  const seededRef = useRef(false);

  function scrollDown() {
    requestAnimationFrame(() => {
      if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    });
  }

  async function send(message: string, speak: boolean) {
    const msg = message.trim();
    if (!msg || phase !== "idle") return;
    setError(null);
    setInput("");
    setTurns((t) => [...t, { role: "you", text: msg }]);
    scrollDown();
    setPhase("thinking");
    try {
      const r = await buildIntake(msg, sessionId);
      setSessionId(r.session_id);
      setAgent(r.agent);
      setTurns((t) => [...t, { role: "jardo", text: r.reply }]);
      if (r.ready && r.brief) {
        setBrief(r.brief);
        if (directory.endsWith("/new") && r.what) {
          setDirectory(`~/jardo-projects/${r.what.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`);
        }
      }
      scrollDown();
      if (speak) {
        setPhase("speaking");
        await voiceSay(r.reply);
      }
    } catch (e) {
      setError((e as ApiError).message || "Build request failed.");
    } finally {
      setPhase("idle");
    }
  }

  async function speakAndSend() {
    if (phase !== "idle") return;
    setError(null);
    setPhase("listening");
    try {
      const heard = await voiceTranscribe(6);
      if (heard.heard && heard.transcript.trim()) await send(heard.transcript, true);
      else setPhase("idle");
    } catch (e) {
      setError((e as ApiError).message || "Couldn't hear you.");
      setPhase("idle");
    }
  }

  // Auto-start from a seed (e.g. a build goal spoken on the launch briefing).
  useEffect(() => {
    if (seed && !seededRef.current) {
      seededRef.current = true;
      send(seed, mode === "voice");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed]);

  async function launch() {
    if (!sessionId) return;
    setPhase("thinking");
    try {
      const result = await buildRun(sessionId, directory, true);
      setRunResult(result);
    } catch (e) {
      setError((e as ApiError).message || "Couldn't launch the agent.");
    } finally {
      setPhase("idle");
    }
  }

  return (
    <div className="build">
      {error && <div className="banner error" role="alert">{error}</div>}

      <div className="build-convo" ref={scrollRef}>
        {turns.length === 0 && (
          <div className="empty">
            Tell me what to build — e.g. "a bakery website with Claude". I'll ask what
            I need, suggest improvements, then run the agent for you.
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className={`build-turn ${t.role}`}>
            <span className="who">{t.role === "you" ? "You" : "Jardo"}</span>
            <span className="what">{t.text}</span>
          </div>
        ))}
        {phase === "thinking" && <div className="build-turn jardo"><span className="who">Jardo</span><span className="what typing">…</span></div>}
      </div>

      {brief && (
        <div className="build-ready">
          <div className="build-brief">
            <div className="brief-title">Brief ready · agent: {agent}</div>
            <pre>{brief}</pre>
          </div>
          <div className="build-launch">
            <input
              value={directory}
              onChange={(e) => setDirectory(e.target.value)}
              placeholder="project folder"
            />
            <button onClick={launch} disabled={phase !== "idle"}>
              {phase !== "idle" ? "Working…" : `Run ${agent}`}
            </button>
          </div>
          {runResult && (
            <div className="build-result">
              <div>{runResult.note} — {runResult.workspace.path}
                {runResult.model ? ` · model ${runResult.model}` : ""}</div>
              {runResult.warnings.map((w, i) => (
                <div key={i} className="warn-line">⚠ {w}</div>
              ))}
              {runResult.output && <pre>{runResult.output.slice(-800)}</pre>}
            </div>
          )}
        </div>
      )}

      {!brief && (
        mode === "voice" ? (
          <div className="composer voice-composer">
            <button
              className={`mic-btn big ${phase === "listening" ? "listening" : ""}`}
              onClick={speakAndSend}
              disabled={phase !== "idle"}
            >
              {phase === "listening" ? "● Listening…" : phase === "thinking" ? "… Thinking"
                : phase === "speaking" ? "🔊 Speaking" : "🎤 Tap and speak"}
            </button>
            <button className="mode-toggle" onClick={() => setMode("text")} title="Type instead">⌨</button>
          </div>
        ) : (
          <div className="composer">
            <button className="mode-toggle" onClick={() => setMode("voice")} title="Speak instead">🎤</button>
            <textarea
              value={input}
              placeholder="Tell Jardo what to build…"
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input, false); } }}
              rows={2}
            />
            <button onClick={() => send(input, false)} disabled={phase !== "idle" || !input.trim()}>
              Send
            </button>
          </div>
        )
      )}
    </div>
  );
}
