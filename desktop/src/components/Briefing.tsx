import { useCallback, useEffect, useRef, useState } from "react";
import {
  getBriefing,
  getIdentity,
  localize,
  setObjective,
  voiceSay,
  voiceTranscribe,
  type ApiError,
  type Briefing as BriefingData,
} from "../api";

// Launch briefing (spec §4.5): on open, Jardo greets the owner, speaks any
// updates, and asks for the day's objective — which becomes the supervision goal.
export function Briefing({ onDone }: { onDone: (goal?: string) => void }) {
  const [data, setData] = useState<BriefingData | null>(null);
  const [goal, setGoal] = useState("");
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [confirmed, setConfirmed] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const spokenRef = useRef(false);
  const langRef = useRef("en");
  const [greeting, setGreeting] = useState<string | null>(null); // localized for display
  // Once we've handed off (skip or a set goal), any in-flight voice capture must
  // not also fire — otherwise the briefing keeps listening after Skip and you get
  // two responders talking over each other in the chat.
  const doneRef = useRef(false);

  // Speak in the user's language: the briefing text is English, so translate it
  // before voicing (the backend also picks the language's native voice). This is
  // the FIRST thing a non-English user hears — it must be in their language.
  async function speakL(text: string) {
    const out = langRef.current !== "en" ? await localize(text) : text;
    await voiceSay(out);
  }

  const finish = useCallback(
    (g?: string) => {
      if (doneRef.current) return;
      doneRef.current = true;
      onDone(g);
    },
    [onDone]
  );

  // Auto-listen for the day's goal (10s silence timeout). On hearing an answer,
  // Jardo confirms it out loud before proceeding; on silence/misheard, it says so
  // and leaves the manual input available (never a silent jump).
  async function autoListenForGoal() {
    if (listening || busy || doneRef.current) return;
    setListening(true);
    try {
      const heard = await voiceTranscribe(6);
      if (doneRef.current) return; // skipped/submitted while we were recording
      // First run: the speech model is still downloading — say so plainly instead
      // of "I didn't catch that" (which wrongly implies it heard nothing).
      if (heard.model_pending) {
        setError("My voice is still setting up (one-time download). Type your goal below, and I'll speak once it's ready.");
        return;
      }
      const g = (heard.transcript || "").trim();
      if (heard.heard && g.length >= 3) {
        setGoal(g);
        setConfirmed(g);
        await setObjective(g);
        try {
          // Don't parrot the raw sentence back ("I'll help you with I want to
          // achieve a project"); a short, natural acknowledgement reads better.
          await speakL("Got it. Let's get started.");
        } catch {
          /* no voice — the visual confirmation still shows */
        }
        finish(g);
      } else {
        try {
          await speakL("I didn't catch that. You can say it again, or type it below.");
        } catch {
          /* ignore */
        }
      }
    } catch {
      /* ignore — manual input remains */
    } finally {
      setListening(false);
    }
  }

  const speakGoal = autoListenForGoal;

  useEffect(() => {
    getIdentity()
      .then((id) => (langRef.current = id.language || "en"))
      .catch(() => undefined)
      .finally(() => {
        getBriefing()
          .then(async (b) => {
            setData(b);
            if (langRef.current !== "en") {
              localize(b.greeting).then(setGreeting).catch(() => undefined);
            }
            if (spokenRef.current) return;
            spokenRef.current = true;
            try {
              await speakL(b.spoken); // greeting + updates + question, in-language
            } catch {
              /* no voice — fall through to manual */
            }
            autoListenForGoal(); // then listen for the answer automatically
          })
          .catch((e: ApiError) => setError(e.message));
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function submit() {
    const g = goal.trim();
    if (!g) {
      finish();
      return;
    }
    setBusy(true);
    try {
      await setObjective(g);
      finish(g);
    } catch (e) {
      setError((e as ApiError).message);
      setBusy(false);
    }
  }

  return (
    <div className="briefing">
      <div className="briefing-card">
        <img className="briefing-logo" src="/jardo-logo.png" alt="Jardo" />

        {error && (
          <div className="banner error" role="alert">
            {error}
          </div>
        )}

        {!data && !error && <div className="empty">Preparing your briefing…</div>}

        {data && (
          <>
            <h1 className="briefing-greeting">{greeting || data.greeting}</h1>

            <ul className="briefing-updates">
              {data.updates.map((u, i) => (
                <li key={i}>{u}</li>
              ))}
            </ul>

            {data.active_objective && (
              <div className="briefing-active">
                Still working toward: <strong>{data.active_objective}</strong>
              </div>
            )}

            {confirmed ? (
              <div className="briefing-confirmed">✓ On it: <strong>{confirmed}</strong></div>
            ) : (
              <label className="briefing-prompt">
                {listening ? "Listening — tell me your goal…" : data.prompt}
              </label>
            )}
            <div className="briefing-input">
              <button
                className={`mic-btn ${listening ? "listening" : ""}`}
                onClick={speakGoal}
                disabled={listening || busy}
                title="Answer by voice"
              >
                {listening ? "● Listening…" : "🎤 Speak"}
              </button>
              <input
                autoFocus
                value={goal}
                placeholder="…or type your goal for today"
                onChange={(e) => setGoal(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submit()}
              />
              <button onClick={submit} disabled={busy || listening}>
                {goal.trim() ? "Set goal" : "Skip"}
              </button>
            </div>

            <button className="briefing-skip" onClick={() => finish()}>
              Skip for now
            </button>
          </>
        )}
      </div>
    </div>
  );
}
