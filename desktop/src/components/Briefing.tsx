import { useEffect, useRef, useState } from "react";
import {
  getBriefing,
  setObjective,
  voiceSay,
  voiceTranscribe,
  type ApiError,
  type Briefing as BriefingData,
} from "../api";

// Launch briefing (spec §4.5): on open, Jardo greets the owner, speaks any
// updates, and asks for the day's objective — which becomes the supervision goal.
export function Briefing({ onDone }: { onDone: () => void }) {
  const [data, setData] = useState<BriefingData | null>(null);
  const [goal, setGoal] = useState("");
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [confirmed, setConfirmed] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const spokenRef = useRef(false);

  // Auto-listen for the day's goal (10s silence timeout). On hearing an answer,
  // Jardo confirms it out loud before proceeding; on silence/misheard, it says so
  // and leaves the manual input available (never a silent jump).
  async function autoListenForGoal() {
    if (listening || busy) return;
    setListening(true);
    try {
      const heard = await voiceTranscribe(6);
      const g = (heard.transcript || "").trim();
      if (heard.heard && g.length >= 3) {
        setGoal(g);
        setConfirmed(g);
        await setObjective(g);
        try {
          await voiceSay(`Got it. I'll help you with ${g}. Let's get started.`);
        } catch {
          /* no voice — the visual confirmation still shows */
        }
        onDone();
      } else {
        try {
          await voiceSay("I didn't catch that. You can say it again, or type it below.");
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
    getBriefing()
      .then(async (b) => {
        setData(b);
        if (spokenRef.current) return;
        spokenRef.current = true;
        try {
          await voiceSay(b.spoken); // speak greeting + updates + the question
        } catch {
          /* no voice — fall through to manual */
        }
        autoListenForGoal(); // then listen for the answer automatically
      })
      .catch((e: ApiError) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function submit() {
    const g = goal.trim();
    if (!g) {
      onDone();
      return;
    }
    setBusy(true);
    try {
      await setObjective(g);
      onDone();
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
            <h1 className="briefing-greeting">{data.greeting}</h1>

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

            <button className="briefing-skip" onClick={onDone}>
              Skip for now
            </button>
          </>
        )}
      </div>
    </div>
  );
}
