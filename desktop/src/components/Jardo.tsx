import { useCallback, useEffect, useRef, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import {
  chooseProject,
  getIdentity,
  routeIntent,
  sendChat,
  type RoutedIntent,
  setProjectsRoot,
  startProject,
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

// "Where am I / catch me up / what am I working on / what's left / check my
// project / where did I stop" → resume-work. Kept broad: these are commands, and
// letting them slip through to the chat model is what makes Jardo feel dumb.
function wantsWhereAmI(text: string): boolean {
  const t = text.toLowerCase();
  return (
    /\bwhere\s+(am|was|are|were)\b/.test(t) ||
    /\bwhere\s+(did|do)\s+i\b/.test(t) ||
    /\b(catch me up|resume|pick up where|pick up from|remind me where|bring me up to speed)\b/.test(t) ||
    /\bwhere i (stopped|finished|left off|left it|was|ended)\b/.test(t) ||
    /\bwhat\b.*\bproject\b.*\b(working on|on now|am i on|is this|currently)\b/.test(t) ||
    /\bwhat('?s| is| am i)\b.*\b(working on|doing now|left|remaining|next|the goal|status|progress)\b/.test(t) ||
    /\b(check|show|tell me)\b.*\b(where i|my project|the project|my progress|what i (did|finished)|last|finished)\b/.test(t) ||
    /\bwhat did i (do|finish|work on)\b/.test(t)
  );
}

// Things Jardo should answer itself, instantly and correctly — never via the
// model (which invents nonsense like "you're the one being addressed").
function quickAnswer(text: string, name: string | null): string | null {
  const t = text.trim().toLowerCase().replace(/[?.!,]+$/g, "");
  if (/^(who are you|what('?s| is) your name|your name|what are you)\b/.test(t))
    return "I'm Jardo, your AI chief of staff. I resume your work and supervise coding agents in your terminal.";
  if (/^who am i\b/.test(t) || /^what('?s| is) my name\b/.test(t))
    return name
      ? `You're ${name}.`
      : "I don't have your name yet — set it in Settings and I'll use it.";
  if (/^(what can you do|what do you do|how can you help|help me|capabilities|what are you for)\b/.test(t))
    return "Say “where am I?” and I'll pick up where you left off, or “supervise Claude in my terminal” and I'll answer the agent's permission prompts for you. You can also just ask me things.";
  if (/^(hi|hey|hello|yo|hiya|hey jardo|good morning|good evening)\b/.test(t) && t.length < 20)
    return name ? `Hi ${name} — what are we working on?` : "Hi — what are we working on?";
  return null;
}

// "Build me an X / create a new project / spin up a website with gemini" →
// onboard a fresh project and hand it to a coding agent.
function parseNewProject(text: string): Supervising | null {
  const t = text.toLowerCase();
  const build = /\b(build|create|make|start|scaffold|set ?up|spin ?up)\b/.test(t);
  const thing =
    /\b(project|website|web ?app|app|application|api|tool|bot|game|dashboard|landing ?page|site|script|cli|library)\b/.test(t);
  // "start supervising" etc. is NOT a new project — that's handled elsewhere.
  const isSupervise = /\b(supervise|superwise|watch|oversee)\b/.test(t);
  if (build && thing && !isSupervise) {
    const agent = /gemini/.test(t) ? "gemini" : "claude";
    return { goal: text, agent };
  }
  return null;
}

function isAffirmative(text: string): boolean {
  return /^(yes|yeah|yep|yup|sure|ok|okay|go|go ahead|do it|confirm|please do|start|create it|make it|let'?s do it|proceed|correct)\b/.test(
    text.trim().toLowerCase()
  );
}

function isNegative(text: string): boolean {
  return /^(no|nope|cancel|stop|don'?t|nah|never ?mind|forget it|not now|wait)\b/.test(
    text.trim().toLowerCase()
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
  const pendingRef = useRef<Supervising | null>(null); // onboarding awaiting a yes
  const scrollRef = useRef<HTMLDivElement>(null);
  const speakingRef = useRef(false);
  const suppressUntilRef = useRef(0);
  const nameRef = useRef<string | null>(null);

  // Ref callback that guarantees the avatar autoplays and loops. WebKit blocks
  // autoplay unless the `muted` *property* is set (React's `muted` attribute is
  // unreliable), and a paused video shows a play-button overlay — so we mute and
  // play imperatively and never pause it. The glow (via className) shows state.
  const playMuted = useCallback((el: HTMLVideoElement | null) => {
    if (!el) return;
    el.muted = true;
    el.loop = true;
    void el.play().catch(() => undefined);
  }, []);

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
    getIdentity()
      .then((id) => {
        nameRef.current = id.name;
      })
      .catch(() => undefined);
    return () => {
      runningRef.current = false;
    };
  }, []);

  // Always-on: start listening as soon as the app is up.
  useEffect(() => {
    if (autoStart && status?.available && !runningRef.current) listenLoop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart, status?.available]);

  // Kill-switch — a real halt (audit #2). Stops the always-on voice loop and the
  // supervision tick, so Jardo immediately stops listening and stops pressing
  // keys in your terminal. Fired from the tray, hotkey, or header Stop button.
  useEffect(() => {
    const un = listen("kill-switch", () => {
      runningRef.current = false; // stop the voice loop after its current frame
      pendingRef.current = null; // drop any unconfirmed action
      stopSupervising(); // clears the tick interval → no more key presses
      setPhase("idle");
      say("event", "Kill-switch — halted all autonomous actions.", false);
    });
    return () => {
      un.then((f) => f());
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- one place every utterance flows through, voice or typed --------------
  async function handle(text: string, spoken: boolean) {
    const msg = text.trim();
    if (!msg) return;
    say("you", msg);

    // A side-effectful action (creating a project + launching an agent) is
    // waiting on a yes/no — resolve that before anything else (audit #1).
    if (pendingRef.current) {
      const p = pendingRef.current;
      pendingRef.current = null;
      if (isAffirmative(msg)) {
        await startNewProject(p, spoken);
        return;
      }
      if (isNegative(msg)) {
        const line = "Okay, cancelled.";
        say("jardo", line);
        if (spoken) await speak(line);
        return;
      }
      // Neither yes nor no — drop the pending action and handle this as new input.
    }

    if (superRef.current && wantsStop(msg)) {
      stopSupervising();
      const line = "Okay — I've stopped watching your terminal.";
      say("jardo", line);
      if (spoken) await speak(line);
      return;
    }

    // Jardo answers its own identity/capability questions — never the model.
    if (!superRef.current) {
      const quick = quickAnswer(msg, nameRef.current);
      if (quick) {
        say("jardo", quick);
        if (spoken) await speak(quick);
        return;
      }
    }

    // Understand intent with the model (the tool-use layer). If there's no
    // capable model, or the router is unreachable, fall back to offline
    // heuristics — which is also the no-key path, so behaviour never regresses.
    let action: RoutedIntent["intent"] = "chat";
    let agent = "claude";
    let goal = msg;
    try {
      const routed = await routeIntent(msg);
      if (routed.fallback) throw new Error("fallback");
      action = routed.intent;
      if (routed.agent) agent = routed.agent;
      if (routed.goal) goal = routed.goal;
    } catch {
      if (wantsWhereAmI(msg)) action = "resume";
      else if (!superRef.current && parseNewProject(msg)) {
        const p = parseNewProject(msg)!;
        action = "new_project";
        agent = p.agent;
        goal = p.goal;
      } else if (parseSupervise(msg)) {
        action = "supervise";
        agent = parseSupervise(msg)!.agent;
      }
    }

    if (action === "resume") {
      await doWhereAmI(spoken);
      return;
    }
    if (action === "supervise") {
      if (superRef.current) {
        // Already watching — the owner is just reaffirming. Reassure, don't restart.
        const line = `Still on it — I'm watching your terminal and handling ${superRef.current.agent}'s prompts.`;
        say("jardo", line);
        if (spoken) await speak(line);
        return;
      }
      await startSupervising({ goal: msg, agent }, spoken);
      return;
    }
    if (action === "new_project" && !superRef.current) {
      // Don't scaffold + spawn an agent off one utterance — confirm first.
      pendingRef.current = { goal, agent };
      const line = `Start a new ${agent === "gemini" ? "Gemini" : "Claude"} project for that and set it up in your terminal? Say yes to go ahead.`;
      say("jardo", line);
      if (spoken) await speak(line);
      return;
    }
    if (action === "stop" && superRef.current) {
      stopSupervising();
      const line = "Okay — I've stopped watching your terminal.";
      say("jardo", line);
      if (spoken) await speak(line);
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

  // ---- new-project onboarding conductor -------------------------------------
  async function startNewProject(intent: Supervising, spoken: boolean) {
    setPhase("thinking");
    try {
      let res = await startProject(intent.goal, intent.agent);
      if (res.needs_root) {
        const ask = "First, where should I keep your projects? Pick the folder that holds them.";
        say("jardo", ask);
        if (spoken) await speak(ask);
        await setProjectsRoot(null); // native folder chooser
        res = await startProject(intent.goal, intent.agent);
      }
      if (res.ok) {
        const where = res.launched
          ? `I created ${res.name} and started ${intent.agent} on it in your terminal. I'm watching it now — I'll answer its prompts.`
          : `I created ${res.name} and set it up, but couldn't open the terminal. Open it and run ${intent.agent} in that folder, then I'll supervise.`;
        say("jardo", where);
        if (spoken) {
          setPhase("speaking");
          await speak(where);
        }
        if (res.launched) {
          const active: Supervising = { agent: intent.agent, goal: res.goal || intent.goal };
          superRef.current = active;
          setSupervising(active);
        }
      }
    } catch (e) {
      const err = e as ApiError;
      if (err.status !== 409 || !(err.message || "").includes("chosen")) {
        const line = err.message || "I couldn't start that project.";
        say("jardo", line);
        if (spoken) await speak(line);
      }
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
    let busy = false; // never let a slow tick overlap the next — double-press guard
    const timer = setInterval(async () => {
      if (!alive || !superRef.current || busy) return;
      busy = true;
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
      } finally {
        busy = false;
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
            <video
              ref={playMuted}
              className={`welcome-avatar ${phase}`}
              src="/jardo-avatar.mp4"
              autoPlay
              loop
              muted
              playsInline
            />
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
        <video
          ref={playMuted}
          className={`dock-avatar ${phase}`}
          src="/jardo-avatar.mp4"
          autoPlay
          loop
          muted
          playsInline
        />
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
