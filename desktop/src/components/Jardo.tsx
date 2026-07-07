import { useEffect, useRef, useState } from "react";
import {
  chooseProject,
  sendChat,
  terminalSupervise,
  terminalTick,
  voiceSay,
  voiceStatus,
  voiceTranscribe,
  whereAmI,
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

// Speech-to-text routinely mangles "Claude" → "cloud/clod/claud" and "supervise"
// → "superwise/supavise". We match loosely on purpose: it's far better to start
// watching when the owner meant it than to drop the request into the chat model.
const CLAUDE = /\b(claude|cloud|claud|clod|glaude|clawed)\b/;
const AGENT_WORDS = /\b(terminal|gemini|codex|cursor|agent|prompt|prompts|permission|permissions)\b/;
// "supervise" is a word STT loves to mangle — match every spelling we've seen it
// return, including the two-word ones ("super vice", "super wise", "superverse").
const STRONG_VERB =
  /\b(supervise|supervised|supervising|supervisor|superwise|supavise|superverse|supervice)\b|\bsuper\s?(vice|vise|wise|verse|advise|advice)\b/;
// Softer "just do the clicking" phrasings the owner actually uses out loud.
const SOFT_VERB = /\b(watch|keep an eye|handle|take over|answer|click|clicking|press|pressing|approve|approving|accept|accepting|confirm|allow|say yes|go through)\b/;
const YES_WORDS = /\b(yes|yeah|proceed|approve|accept|allow|permission)\b/;

// Does an utterance mean "go watch my terminal and press the buttons for me"?
function parseSupervise(text: string): Supervising | null {
  const t = text.toLowerCase();
  const hasTarget = AGENT_WORDS.test(t) || CLAUDE.test(t);
  // A strong verb ("supervise it") is enough on its own. A soft verb ("keep
  // clicking yes", "help me click through the terminal") needs a target or a
  // yes-word to disambiguate from ordinary chat.
  const trigger = STRONG_VERB.test(t) || (SOFT_VERB.test(t) && (hasTarget || YES_WORDS.test(t)));
  if (!trigger) return null;
  const agent = /gemini/.test(t)
    ? "gemini"
    : /codex/.test(t)
      ? "codex"
      : /cursor/.test(t)
        ? "cursor"
        : "claude"; // default incl. the "cloud" mishearing
  return { goal: text, agent };
}

// "Where am I / catch me up / what am I working on / what's left" → resume.
function wantsWhereAmI(text: string): boolean {
  const t = text.toLowerCase();
  return (
    /\bwhere\s+(am\s+i|was\s+i|are\s+we)\b/.test(t) ||
    /\b(catch me up|resume|pick up where|remind me)\b/.test(t) ||
    /\bwhat('?s| is| am i)\b.*\b(working on|doing|left|remaining|next|the goal|status)\b/.test(t) ||
    /\bwhat('?s| is)\b.*\b(remaining|left)\b/.test(t)
  );
}

function wantsStop(text: string): boolean {
  return /\b(stop|pause|that'?s enough|stand down|never ?mind|cancel|hold on)\b/.test(
    text.toLowerCase()
  );
}

// Short affirmations / cheerleading while supervising — must NOT be fed to the
// chat model (it would answer with nonsense). Jardo just keeps watching.
function isFiller(text: string): boolean {
  const t = text.trim().toLowerCase().replace(/[.!?,]+$/g, "");
  if (t.length <= 3) return true;
  return /^(yes|yeah|yep|ok|okay|good|nice|cool|great|perfect|beautiful|thanks|thank you|keep going|keep clicking|keep at it|go on|continue|come on|do it|please|right|exactly|correct)\b/.test(
    t
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
  const [needsAccess, setNeedsAccess] = useState(false);

  const runningRef = useRef(false);
  const convRef = useRef<string | null>(null);
  const superRef = useRef<Supervising | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const speakingRef = useRef(false);
  const suppressUntilRef = useRef(0);

  function say(who: Line["who"], text: string, ok?: boolean) {
    setLines((l) => [...l, { who, text, ok }]);
    requestAnimationFrame(() => {
      const el = scrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    });
  }

  // Speak, but muffle the mic while we do it (and for a moment after) so Jardo
  // never hears its own voice and answers itself.
  async function speak(text: string) {
    speakingRef.current = true;
    try {
      await voiceSay(text);
    } catch {
      /* no voice — fine */
    } finally {
      speakingRef.current = false;
      suppressUntilRef.current = Date.now() + 900; // ignore the tail echo
    }
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
      if (spoken) await speak(line);
      return;
    }

    if (wantsWhereAmI(msg)) {
      await doWhereAmI(spoken);
      return;
    }

    const intent = parseSupervise(msg);
    if (intent) {
      if (superRef.current) {
        // Already watching — the owner is just reaffirming. Reassure, don't
        // restart, and never send this to the chat model.
        const line = `Still on it — I'm watching your terminal and handling ${superRef.current.agent}'s prompts.`;
        say("jardo", line);
        if (spoken) await speak(line);
        return;
      }
      await startSupervising(intent, spoken);
      return;
    }

    // While supervising, ignore filler/cheerleading so the weak chat model never
    // gets a chance to answer with nonsense over the top of the real work.
    if (superRef.current && isFiller(msg)) return;

    setPhase("thinking");
    try {
      const reply = await sendChat(msg, convRef.current);
      convRef.current = reply.conversation_id;
      setNeedsSetup(false);
      say("jardo", reply.reply);
      if (spoken) {
        setPhase("speaking");
        await speak(reply.reply);
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
        // Drop anything captured while (or just after) Jardo was speaking — that's
        // Jardo hearing itself, not the owner.
        if (speakingRef.current || Date.now() < suppressUntilRef.current) continue;
        await handle(heard.transcript, true);
      }
    } catch (e) {
      setError((e as ApiError).message || "Voice error.");
    } finally {
      setPhase("idle");
      runningRef.current = false;
    }
  }

  // ---- "where am I?" resume-work --------------------------------------------
  async function doWhereAmI(spoken: boolean) {
    setPhase("thinking");
    try {
      let res = await whereAmI(null);
      if (res.needs_folder) {
        const ask = "Which project? Pick the folder you're working on.";
        say("jardo", ask);
        if (spoken) await speak(ask);
        const chosen = await chooseProject(); // native folder picker
        res = await whereAmI(chosen.path);
      }
      const line = res.spoken || "I couldn't read that project.";
      say("jardo", line);
      if (res.from_agent_memory === false && res.found) {
        say("event", "read from git (no agent memory found for this folder)", true);
      }
      if (spoken) {
        setPhase("speaking");
        await speak(line);
      }
    } catch (e) {
      const err = e as ApiError;
      // 409 from choose = the owner cancelled the picker; stay quiet.
      if (err.status !== 409) setError(err.message || "Couldn't check the project.");
    } finally {
      setPhase("idle");
    }
  }

  // ---- terminal supervision -------------------------------------------------
  async function startSupervising(intent: Supervising, spoken: boolean) {
    setPhase("thinking");
    try {
      const res = await terminalSupervise(intent.goal, intent.agent);
      // The server keeps your real objective (from the briefing) over the raw
      // trigger phrase — show that on the bar.
      const active: Supervising = { agent: intent.agent, goal: res.goal || intent.goal };
      superRef.current = active;
      setSupervising(active);
      const line = `On it. I'm watching your terminal and I'll answer ${intent.agent}'s permission prompts — approving what's safe and on-task, declining anything risky.`;
      say("jardo", line);
      if (spoken) {
        setPhase("speaking");
        await speak(line);
      }
    } catch (e) {
      const err = e as ApiError;
      const line =
        err.status === 409
          ? "I couldn't find a terminal to watch. Open Terminal with your agent running, then ask me again."
          : err.message || "I couldn't start supervising.";
      say("jardo", line);
      if (spoken) await speak(line);
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
        if (r.needs_accessibility) {
          setNeedsAccess(true);
          return;
        }
        if (r.answered && r.action) {
          setNeedsAccess(false);
          const verb = r.approved ? "Approved" : "Declined";
          const action = r.action.length > 90 ? r.action.slice(0, 90) + "…" : r.action;
          say("event", `${verb} · ${action}`, r.approved);
          await speak(`${verb}. ${action}`);
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
          Supervising <strong>{supervising.agent}</strong>
          {supervising.goal ? ` — ${supervising.goal}` : " in your terminal"}
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
      {needsAccess && (
        <div className="banner warn" role="alert">
          I can read your terminal but I'm blocked from pressing the answer. Grant
          Jardo <strong>Accessibility</strong> in System Settings → Privacy &
          Security → Accessibility, then I'll take it from there.
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
              I'm listening. Say “where am I?” to pick up where you left off, or
              “supervise Claude in my terminal” and I'll handle the permission
              prompts for you.
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
