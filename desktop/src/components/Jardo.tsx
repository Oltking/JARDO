import { useEffect, useRef, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { HalftoneAvatar } from "./HalftoneAvatar";
import {
  chooseProject,
  getIdentity,
  getProviders,
  openPrivacySettings,
  requestAccessibility,
  routeIntent,
  sendChat,
  type RoutedIntent,
  setProjectsRoot,
  startProject,
  supervisionReport,
  terminalObserve,
  terminalSupervise,
  terminalTick,
  voiceSay,
  voiceStatus,
  voiceTranscribe,
  whereAmI,
  type ApiError,
  type Observation,
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

// New-project intake: collected in a small form before we scaffold anything, so
// the owner names it and describes it properly (and can attach a spec file)
// instead of the agent building from a one-line guess.
interface Intake {
  name: string;
  goal: string;
  details: string;
  agent: string;
  specText: string | null;
  specFilename: string | null;
  spoken: boolean;
}

// A short, human folder name from a spoken goal ("build a landing page for my
// bakery" → "landing page bakery"). The backend still slugifies; this is only a
// friendly default the owner can edit.
function suggestName(goal: string): string {
  const skip = new Set([
    "build", "create", "make", "start", "a", "an", "the", "me", "my", "new",
    "project", "please", "for", "with", "using", "of", "to", "app", "some",
    "that", "this", "spin", "up", "scaffold", "set",
  ]);
  const words = goal
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .split(/\s+/)
    .filter((w) => w && !skip.has(w))
    .slice(0, 4);
  const name = words.join(" ").trim();
  return name ? name.replace(/\b\w/g, (c) => c.toUpperCase()) : "New Project";
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
  const [obs, setObs] = useState<Observation | null>(null); // live agent read (P1)
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [needsAccess, setNeedsAccess] = useState(false);
  const [micPaused, setMicPaused] = useState(false); // pause the always-on mic
  const [noKey, setNoKey] = useState(false); // first-run: no model key configured
  const [intake, setIntake] = useState<Intake | null>(null); // new-project form

  const runningRef = useRef(false);
  const convRef = useRef<string | null>(null);
  const superRef = useRef<Supervising | null>(null);
  const pendingRef = useRef<Supervising | null>(null); // onboarding awaiting a yes
  const lastStateRef = useRef<string>(""); // last observed agent state (dedupe)
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const speakingRef = useRef(false);
  const suppressUntilRef = useRef(0);
  // True while an utterance (typed or spoken) is being handled. The always-on mic
  // loop checks this before dispatching, so typing in the chat doesn't get a
  // second answer from a voice capture that overlapped it (no two responders).
  const busyRef = useRef(false);
  const nameRef = useRef<string | null>(null);

  function say(who: Line["who"], text: string, ok?: boolean) {
    setLines((l) => [...l, { who, text, ok }]);
  }

  // Keep the transcript pinned to the latest line — separate from the welcome
  // screen so new bubbles never overlap earlier ones when the view fills up.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || lines.length === 0) return;
    bottomRef.current?.scrollIntoView({ block: "end" });
    el.scrollTop = el.scrollHeight;
  }, [lines]);

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
    // First run downloads the voice model once (~180 MB). Poll until it's ready
    // so the banner clears itself; chat/supervision work throughout.
    const poll = window.setInterval(async () => {
      try {
        const s = await voiceStatus();
        setStatus(s);
        if (s.model_ready || s.available === false) window.clearInterval(poll);
      } catch {
        /* ignore transient errors */
      }
    }, 3000);
    getIdentity()
      .then((id) => {
        nameRef.current = id.name;
      })
      .catch(() => undefined);
    getProviders()
      .then((info) => setNoKey(info.active.length === 0))
      .catch(() => undefined);
    return () => {
      runningRef.current = false;
      window.clearInterval(poll);
    };
  }, []);

  // Always-on: start listening as soon as the app is up (unless paused).
  useEffect(() => {
    if (autoStart && !micPaused && status?.available && !runningRef.current) listenLoop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart, status?.available]);

  function toggleMic() {
    if (micPaused) {
      setMicPaused(false);
      if (status?.available) listenLoop();
    } else {
      setMicPaused(true);
      runningRef.current = false; // stop after the current frame
      setPhase("idle");
    }
  }

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
  // Wrapper: mark "busy" for the entire turn so the mic loop won't fire a second
  // response over a typed one. The real logic lives in handleUtterance.
  async function handle(text: string, spoken: boolean) {
    if (!text.trim()) return;
    busyRef.current = true;
    try {
      await handleUtterance(text, spoken);
    } finally {
      busyRef.current = false;
    }
  }

  async function handleUtterance(text: string, spoken: boolean) {
    const raw = text.trim();
    if (!raw) return;
    say("you", raw); // immediate echo — stays responsive

    // --- Instant, offline handling first: the most common turns (confirmations,
    // stop, identity) need no model round-trip, so they answer immediately. Only
    // substantive requests pay for the understanding call further down.

    // A side-effectful action (create project + launch agent) awaits a yes/no.
    if (pendingRef.current) {
      const p = pendingRef.current;
      pendingRef.current = null;
      if (isAffirmative(raw)) {
        setIntake({
          name: suggestName(p.goal), goal: p.goal, details: "", agent: p.agent,
          specText: null, specFilename: null, spoken,
        });
        return;
      }
      if (isNegative(raw)) {
        const line = "Okay, cancelled.";
        say("jardo", line);
        if (spoken) await speak(line);
        return;
      }
      // Neither yes nor no — fall through and treat as new input.
    }

    if (superRef.current && wantsStop(raw)) {
      stopSupervising();
      const line = "Okay — I've stopped watching your terminal.";
      say("jardo", line);
      if (spoken) await speak(line);
      return;
    }

    // Jardo answers its own identity/capability questions — never the model.
    if (!superRef.current) {
      const quick = quickAnswer(raw, nameRef.current);
      if (quick) {
        say("jardo", quick);
        if (spoken) await speak(quick);
        return;
      }
    }

    // --- Substantive request: NOW understand it — clean up STT noise + classify
    // intent in one cached call. `msg` becomes the clarified text used for chat.
    // Falls back to offline heuristics when there's no capable model (no-key path).
    let action: RoutedIntent["intent"] = "chat";
    let agent = "claude";
    let msg = raw;
    let goal = raw;
    try {
      const routed = await routeIntent(raw);
      if (routed.fallback) throw new Error("fallback");
      if (routed.clarified) msg = routed.clarified;
      action = routed.intent;
      if (routed.agent) agent = routed.agent;
      goal = routed.goal || msg;
    } catch {
      if (wantsWhereAmI(raw)) action = "resume";
      else if (!superRef.current && parseNewProject(raw)) {
        const p = parseNewProject(raw)!;
        action = "new_project";
        agent = p.agent;
        goal = p.goal;
      } else if (parseSupervise(raw)) {
        action = "supervise";
        agent = parseSupervise(raw)!.agent;
      }
    }

    if (action === "resume") {
      await doWhereAmI(spoken);
      return;
    }
    if (action === "report") {
      setPhase("thinking");
      try {
        const r = await supervisionReport();
        const line = r.spoken || "Nothing to report yet.";
        say("jardo", line);
        if (spoken) {
          setPhase("speaking");
          await speak(line);
        }
      } catch {
        setError("Couldn't pull the report.");
      } finally {
        setPhase("idle");
      }
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
      // Don't scaffold + spawn an agent off one utterance. Open an intake form so
      // the owner names it and describes what to build (and can attach a spec).
      setIntake({
        name: suggestName(goal),
        goal,
        details: "",
        agent,
        specText: null,
        specFilename: null,
        spoken,
      });
      const line = `Let's set that up properly. I've opened a quick form — give it a name and tell me more about what you want built. You can attach a spec file too.`;
      say("jardo", line);
      if (spoken) await speak(line);
      return;
    }
    if (action === "stop" && superRef.current) {
      // Router caught a "stop" the offline check missed (e.g. accented phrasing).
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
    let silentStreak = 0; // consecutive cycles where the mic captured nothing
    try {
      while (runningRef.current) {
        setPhase("listening");
        const heard = await voiceTranscribe(6);
        if (!runningRef.current) break;

        // The speech model is still downloading (first run). The banner already
        // explains it; slow the loop so we don't spin, and keep waiting.
        if (heard.model_pending) {
          await new Promise((r) => setTimeout(r, 2000));
          continue;
        }
        // Recording/transcription failed — surface it instead of silently looping.
        // A denied microphone is the common case; say so plainly.
        if (heard.error) {
          setError(
            /permission|denied|access|coreaudio|portaudio|-50|input/i.test(heard.error)
              ? "I can't access the microphone. Grant Jardo access in System Settings → Privacy & Security → Microphone, then I'll hear you."
              : `Voice error: ${heard.error}`
          );
          await new Promise((r) => setTimeout(r, 2500));
          continue;
        }
        setError(null);

        if (!heard.heard || !heard.transcript.trim()) {
          // Nothing heard. If the mic is truly silent (amplitude ~0) many times
          // in a row, the mic probably isn't reaching us — tell the owner once.
          if (heard.amplitude < 0.002) {
            silentStreak += 1;
            if (silentStreak === 6) {
              setError(
                "I'm listening but not picking up any sound. Check that the right microphone is selected and that Jardo has Microphone permission."
              );
            }
          }
          continue; // silence → keep listening
        }
        silentStreak = 0;
        setError(null);
        // Drop anything captured while (or just after) Jardo was speaking — that's
        // Jardo hearing itself, not the owner. Also skip if a turn is already being
        // handled (e.g. the owner just typed) so we never get two responders.
        if (speakingRef.current || busyRef.current || Date.now() < suppressUntilRef.current)
          continue;
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
  // ---- new-project intake form ----------------------------------------------
  async function attachSpecFile(file: File) {
    // Read the spec as text in the browser (no Tauri fs permission needed). Text
    // formats only — we can't parse binary docs like .pdf/.docx.
    try {
      const text = await file.text();
      setIntake((cur) =>
        cur ? { ...cur, specText: text, specFilename: file.name } : cur
      );
    } catch {
      setError("Couldn't read that file. Use a text spec (.md, .txt, …).");
    }
  }

  async function submitIntake() {
    if (!intake) return;
    const it = intake;
    if (!it.name.trim() || !(it.details.trim() || it.goal.trim())) return;
    setIntake(null);
    await startNewProject(it);
  }

  async function startNewProject(intent: Intake) {
    const spoken = intent.spoken;
    const extra = {
      name: intent.name.trim() || null,
      details: intent.details.trim() || null,
      specText: intent.specText,
      specFilename: intent.specFilename,
    };
    setPhase("thinking");
    try {
      let res = await startProject(intent.goal, intent.agent, extra);
      if (res.needs_root) {
        const ask = "First, where should I keep your projects? Pick the folder that holds them.";
        say("jardo", ask);
        if (spoken) await speak(ask);
        await setProjectsRoot(null); // native folder chooser
        res = await startProject(intent.goal, intent.agent, extra);
      }
      if (res.ok) {
        const reason = res.launch_error
          ? ` (${res.launch_error.replace(/^osascript failed:\s*/i, "")})`
          : "";
        const where = res.launched
          ? `I created ${res.name} and started ${intent.agent} on it in your terminal. I'm watching it now — I'll answer its prompts.`
          : `I created ${res.name} and set it up, but couldn't open the terminal${reason}. Open Terminal, run ${intent.agent} in that folder, and I'll supervise. If macOS blocked me, grant Jardo control of Terminal in System Settings → Privacy & Security → Automation.`;
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
    // Pressing answers into the agent's terminal needs Accessibility. Trigger the
    // macOS prompt now (adds Jardo to the allowlist) so the grant is in place
    // before the first prompt appears, instead of failing mid-supervision.
    void requestAccessibility();
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
    setObs(null);
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
          const agent = superRef.current?.agent || "the agent";
          stopSupervising();
          if (r.ended) {
            const line = r.ended_reason
              ? `Looks like ${r.ended_reason}, so I've stopped watching.`
              : `${agent} stopped, so I've stopped watching.`;
            say("jardo", line);
            void speak(line);
          }
          return;
        }
        if (r.needs_accessibility) {
          setNeedsAccess(true);
          return;
        }
        if (r.answered && r.action) {
          setNeedsAccess(false);
          const verb = r.approved ? "Approved" : "Declined";
          const action = r.action.length > 80 ? r.action.slice(0, 80) + "…" : r.action;
          // On a decline, note that Jardo also told the agent to adapt & continue.
          const tail = !r.approved && r.guided ? " → told it to adapt & keep going" : "";
          say("event", `${verb} · ${action}${tail}`, r.approved);
          await speak(r.approved ? `Approved. ${action}` : `Declined ${action}. Told it to keep going.`);
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

  // Comprehension beat (Jardo's eyes): on a slow timer, judge whether the agent
  // is progressing, stuck, off-task, or done — and speak up only when it's
  // notable and the state has changed, so it's a heads-up, not a running monologue.
  useEffect(() => {
    if (!supervising) return;
    lastStateRef.current = "";
    let alive = true;
    let busy = false;
    const timer = setInterval(async () => {
      if (!alive || !superRef.current || busy) return;
      busy = true;
      try {
        const o = await terminalObserve();
        if (!alive || !superRef.current) return;
        if (o.state && o.state !== "unknown") setObs(o); // live mission-control read
        const state = o.state || "";
        if (o.notable && state && state !== lastStateRef.current) {
          lastStateRef.current = state;
          const label =
            state === "stuck" ? "⚠ Looks stuck" :
            state === "off_task" ? "⚠ Drifting off-task" :
            state === "error" ? "✗ Hit an error" :
            state === "done" ? "✓ Looks done" : state;
          // Prefer the concrete detail — the actual error, or a progress signal.
          const detail = o.issue || o.note || o.progress || o.activity || "";
          say("event", detail ? `${label} — ${detail}` : label, state === "done");
          await speak(o.note || o.issue || label);
        } else if (state && state !== "unknown") {
          lastStateRef.current = state;
        }
      } catch {
        /* transient — try again next beat */
      } finally {
        busy = false;
      }
    }, 25000);
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

  // P4 — the avatar reacts to what Jardo sees: while supervising it glows with the
  // agent's state (calm progressing, amber stuck, red error, green done), else the
  // voice phase. This is only possible because the observer reads the agent's state.
  const avatarState =
    supervising && obs?.state && obs.state !== "unknown" ? obs.state : phase;

  const STATE_LABEL: Record<string, string> = {
    progressing: "Working", stuck: "Stuck", off_task: "Off-task", done: "Done",
    error: "Error", waiting: "Waiting", idle: "Idle",
  };

  return (
    <div className="jardo">
      {supervising && (
        // P1 — mission control: the flagship gets a real panel, not a status line.
        <div className={`mission ${obs?.state || "waiting"}`}>
          <div className="mission-head">
            <span className="pulse" />
            <span>
              Supervising <strong>{supervising.agent}</strong>
            </span>
            {supervising.goal && <span className="mission-goal">{supervising.goal}</span>}
            <button className="link-btn" onClick={stopSupervising}>
              stop
            </button>
          </div>
          {obs && (
            <div className="mission-body">
              <span className={`state-chip ${obs.state}`}>
                {STATE_LABEL[obs.state || "idle"] || obs.state}
              </span>
              {obs.activity && <span className="mission-activity">{obs.activity}</span>}
              {obs.last_command && <code className="mission-cmd">{obs.last_command}</code>}
              {obs.progress && <span className="mission-progress">✓ {obs.progress}</span>}
              {obs.issue && <span className="mission-issue">⚠ {obs.issue}</span>}
            </div>
          )}
        </div>
      )}

      {intake && (
        <div className="intake-backdrop" onClick={() => setIntake(null)}>
          <div
            className="intake"
            role="dialog"
            aria-label="New project"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="intake-title">New project</h2>
            <p className="intake-sub">
              Name it and tell me what to build. The more detail you give, the
              better {intake.agent === "gemini" ? "Gemini" : "Claude"} starts.
            </p>

            <label className="intake-field">
              <span>Name</span>
              <input
                type="text"
                value={intake.name}
                autoFocus
                placeholder="my-project"
                onChange={(e) => setIntake({ ...intake, name: e.target.value })}
              />
            </label>

            <label className="intake-field">
              <span>What do you want built?</span>
              <textarea
                value={intake.details}
                rows={5}
                placeholder={intake.goal || "Describe the app, its purpose, key features, stack, and anything that matters…"}
                onChange={(e) => setIntake({ ...intake, details: e.target.value })}
              />
            </label>

            <div className="intake-attach">
              {intake.specFilename ? (
                <span className="intake-file">
                  📎 {intake.specFilename}
                  <button
                    className="link-btn"
                    onClick={() => setIntake({ ...intake, specText: null, specFilename: null })}
                  >
                    remove
                  </button>
                </span>
              ) : (
                <label className="intake-filebtn">
                  📎 Attach a spec file
                  <input
                    type="file"
                    accept=".md,.markdown,.txt,.text,.rst,.json,.yaml,.yml"
                    hidden
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) void attachSpecFile(f);
                    }}
                  />
                </label>
              )}
              <span className="intake-agent">
                Agent:
                <select
                  value={intake.agent}
                  onChange={(e) => setIntake({ ...intake, agent: e.target.value })}
                >
                  <option value="claude">Claude</option>
                  <option value="gemini">Gemini</option>
                </select>
              </span>
            </div>

            <div className="intake-actions">
              <button className="btn-ghost" onClick={() => setIntake(null)}>
                Cancel
              </button>
              <button
                className="btn-primary"
                disabled={!intake.name.trim() || !(intake.details.trim() || intake.goal.trim())}
                onClick={submitIntake}
              >
                Create &amp; launch
              </button>
            </div>
          </div>
        </div>
      )}

      {status && status.available === false && (
        <div className="banner warn" role="alert">
          Voice is off: {status.reason || "the voice components aren't available."}{" "}
          You can still type to me.
        </div>
      )}
      {status?.available && status.model_ready === false && (
        <div className="banner hint">
          <span className="dl-spinner" aria-hidden="true" />
          <span>
            Setting up voice — downloading the speech model once (~180&nbsp;MB).
            You can chat and supervise now; talking will work as soon as it's done.
          </span>
        </div>
      )}

      {needsSetup && (
        <div className="banner warn" role="alert">
          Jardo isn't set up yet. Reopen the app to finish the quick setup, or set
          your name in Settings.
        </div>
      )}
      {noKey && !needsSetup && (
        <div className="banner hint">
          <span>
            👋 You're on our free trial compute (Fireworks + AMD). To use your own account later,
            open <strong>⋯ → Providers</strong> — optional. Until then I'm on hosted inference
            or a small local model.
          </span>
          <button className="link-btn" onClick={() => setNoKey(false)}>
            got it
          </button>
        </div>
      )}
      {needsAccess && (
        <div className="banner warn" role="alert">
          <span>
            I can read your terminal but I'm blocked from pressing the answer. Grant
            Jardo <strong>Accessibility</strong>, then I'll take it from there.
          </span>
          <button
            className="link-btn"
            onClick={async () => {
              const ok = await requestAccessibility();
              if (ok) setNeedsAccess(false);
              else await openPrivacySettings("Accessibility");
            }}
          >
            grant access
          </button>
        </div>
      )}
      {error && (
        <div className="banner error" role="alert">
          {error}
        </div>
      )}

      <div className={`stream ${lines.length > 0 ? "has-messages" : "is-empty"}`} ref={scrollRef}>
        {lines.length === 0 ? (
          <div className="welcome-screen">
            <div className="welcome">
              <span className={`welcome-avatar ${avatarState}`}>
                <HalftoneAvatar state={avatarState} size={132} />
              </span>
              <p className="welcome-title">Jardo</p>
              <p className="welcome-sub">
                I'm listening. Say “where am I?” to pick up where you left off, or
                “supervise Claude in your terminal” and I'll handle the permission
                prompts for you.
              </p>
            </div>
          </div>
        ) : (
          <div className="messages">
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
            <div ref={bottomRef} className="stream-anchor" aria-hidden="true" />
          </div>
        )}
      </div>

      <div className="dock">
        <span className={`dock-avatar-slot ${avatarState}`}>
          <HalftoneAvatar state={avatarState} size={44} className={`dock-avatar ${avatarState}`} />
        </span>
        <span className="live-label">
          {micPaused ? "mic paused" : phaseLabel[phase]}
        </span>
        {status?.available && (
          <button
            className={`mic-toggle ${micPaused ? "paused" : ""}`}
            onClick={toggleMic}
            title={micPaused ? "Resume listening" : "Pause listening"}
          >
            {micPaused ? "🔇" : "🎙"}
          </button>
        )}
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
