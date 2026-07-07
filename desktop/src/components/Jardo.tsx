import { useEffect, useRef, useState } from "react";
import {
  sendChat,
  terminalSupervise,
  terminalTick,
  voiceSay,
  voiceStatus,
  voiceTranscribe,
  type ApiError,
  type VoiceStatus,
} from "../api";

// The one surface. You talk (or type) to Jardo; it answers and, when you ask,
// goes and supervises your coding agent in your real terminal. Voice is always
// on from the moment the app opens — no tapping. This component stays mounted
// for the whole session, so nothing you say ever disappears when you look
// elsewhere in the app.

interface Line {
  who: "you" | "jardo" | "event";
  text: string;
  ok?: boolean; // for supervision events: approved (true) / declined (false)
}

type Phase = "idle" | "listening" | "thinking" | "speaking";

interface Supervising {
  goal: string;
  agent: string;
}

// Does an utterance mean "go watch my terminal"?
function parseSupervise(text: string): Supervising | null {
  const t = text.toLowerCase();
  const wantsWatch =
    /\b(supervise|oversee|watch|monitor|keep an eye|handle|take over|answer)\b/.test(t);
  const hasTarget = /\b(terminal|claude|gemini|codex|cursor|agent|permission)\b/.test(t);
  if (wantsWatch && hasTarget) {
    const agent = /gemini/.test(t)
      ? "gemini"
      : /codex/.test(t)
        ? "codex"
        : /cursor/.test(t)
          ? "cursor"
          : "claude";
    return { goal: text, agent };
  }
  return null;
}

function wantsStop(text: string): boolean {
  return /\b(stop|pause|that's enough|stand down|stop watching|stop supervising)\b/.test(
    text.toLowerCase()
  );
}

export function Jardo({ autoStart = false }: { autoStart?: boolean }) {
  const [lines, setLines] = useState<Line[]>([]);
  const [input, setInput] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [supervising, setSupervising] = useState<Supervising | null>(null);
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [needsSetup, setNeedsSetup] = useState(false);

  const runningRef = useRef(false);
  const convRef = useRef<string | null>(null);
  const superRef = useRef<Supervising | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  function say(who: Line["who"], text: string, ok?: boolean) {
    setLines((l) => [...l, { who, text, ok }]);
    requestAnimationFrame(() => {
      const el = scrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    });
  }

  useEffect(() => {
    voiceStatus().then(setStatus).catch((e: ApiError) => setError(e.message));
    return () => {
      runningRef.current = false;
    };
  }, []);

  // Always-on: start listening as soon as the app is up.
  useEffect(() => {
    if (autoStart && status?.available && !runningRef.current) listenLoop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart, status?.available]);

  // ---- one place every utterance flows through, voice or typed --------------
  async function handle(text: string, spoken: boolean) {
    const msg = text.trim();
    if (!msg) return;
    say("you", msg);

    if (superRef.current && wantsStop(msg)) {
      stopSupervising();
      const line = "Okay — I've stopped watching your terminal.";
      say("jardo", line);
      if (spoken) voiceSay(line).catch(() => undefined);
      return;
    }

    const intent = parseSupervise(msg);
    if (intent) {
      await startSupervising(intent, spoken);
      return;
    }

    setPhase("thinking");
    try {
      const reply = await sendChat(msg, convRef.current);
      convRef.current = reply.conversation_id;
      setNeedsSetup(false);
      say("jardo", reply.reply);
      if (spoken) {
        setPhase("speaking");
        await voiceSay(reply.reply).catch(() => undefined);
      }
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 409 && !(err.message || "").includes("voice")) {
        setNeedsSetup(true);
      } else {
        setError(err.message || "Something went wrong.");
      }
    } finally {
      setPhase("idle");
    }
  }

  // ---- always-on voice loop -------------------------------------------------
  async function listenLoop() {
    if (runningRef.current) return;
    runningRef.current = true;
    setError(null);
    try {
      while (runningRef.current) {
        setPhase("listening");
        const heard = await voiceTranscribe(6);
        if (!runningRef.current) break;
        if (!heard.heard || !heard.transcript.trim()) continue; // silence → keep listening
        await handle(heard.transcript, true);
      }
    } catch (e) {
      setError((e as ApiError).message || "Voice error.");
    } finally {
      setPhase("idle");
      runningRef.current = false;
    }
  }

  // ---- terminal supervision -------------------------------------------------
  async function startSupervising(intent: Supervising, spoken: boolean) {
    setPhase("thinking");
    try {
      await terminalSupervise(intent.goal, intent.agent);
      superRef.current = intent;
      setSupervising(intent);
      const line = `On it. I'm watching your terminal and I'll answer ${intent.agent}'s permission prompts — approving what's safe and on-task, declining anything risky.`;
      say("jardo", line);
      if (spoken) {
        setPhase("speaking");
        await voiceSay(line).catch(() => undefined);
      }
    } catch (e) {
      const err = e as ApiError;
      const line =
        err.status === 409
          ? "I couldn't find a terminal to watch. Open Terminal with your agent running, then ask me again."
          : err.message || "I couldn't start supervising.";
      say("jardo", line);
      if (spoken) voiceSay(line).catch(() => undefined);
    } finally {
      setPhase("idle");
    }
  }

  function stopSupervising() {
    superRef.current = null;
    setSupervising(null);
  }

  // The supervision beat: while watching, poll the terminal and report answers.
  useEffect(() => {
    if (!supervising) return;
    let alive = true;
    const timer = setInterval(async () => {
      if (!alive || !superRef.current) return;
      try {
        const r = await terminalTick();
        if (!r.watching) {
          stopSupervising();
          return;
        }
        if (r.answered && r.action) {
          const verb = r.approved ? "Approved" : "Declined";
          say("event", `${verb}: ${r.action}${r.reason ? ` — ${r.reason}` : ""}`, r.approved);
          voiceSay(`${verb}. ${r.action}`.slice(0, 120)).catch(() => undefined);
        }
      } catch {
        /* transient — keep watching */
      }
    }, 2000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [supervising]);

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      const t = input;
      setInput("");
      handle(t, false);
    }
  }

  const phaseLabel: Record<Phase, string> = {
    idle: supervising ? "watching your terminal" : "listening",
    listening: "listening…",
    thinking: "thinking…",
    speaking: "speaking…",
  };

  return (
    <div className="jardo">
      {supervising && (
        <div className="supervising-bar">
          <span className="pulse" />
          Supervising <strong>{supervising.agent}</strong> — {supervising.goal}
          <button className="link-btn" onClick={stopSupervising}>
            stop
          </button>
        </div>
      )}

      {needsSetup && (
        <div className="banner warn" role="alert">
          Jardo isn't set up yet. Run <code>jardo setup</code>, then talk to me.
        </div>
      )}
      {error && (
        <div className="banner error" role="alert">
          {error}
        </div>
      )}

      <div className="stream" ref={scrollRef}>
        {lines.length === 0 && (
          <div className="empty welcome">
            <img className="welcome-logo" src="/jardo-logo.png" alt="Jardo" />
            <p className="welcome-title">Jardo</p>
            <p className="welcome-sub">
              I'm listening. Ask me anything — or say “supervise Claude in my
              terminal” and I'll handle the permission prompts for you.
            </p>
          </div>
        )}
        {lines.map((l, i) => (
          <div key={i} className={`line ${l.who}`}>
            {l.who === "event" ? (
              <span className={`event-chip ${l.ok ? "ok" : "no"}`}>
                {l.ok ? "✓" : "✗"} {l.text}
              </span>
            ) : (
              <div className="bubble">{l.text}</div>
            )}
          </div>
        ))}
      </div>

      <div className="dock">
        <span className={`live-dot ${phase}`} />
        <span className="live-label">{phaseLabel[phase]}</span>
        <textarea
          value={input}
          placeholder="…or type to Jardo"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
        />
        <button
          onClick={() => {
            const t = input;
            setInput("");
            handle(t, false);
          }}
          disabled={!input.trim()}
        >
          Send
        </button>
      </div>
    </div>
  );
}
