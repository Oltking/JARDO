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
  const [error, setError] = useState<string | null>(null);
  const spokenRef = useRef(false);

  async function speakGoal() {
    if (listening || busy) return;
    setError(null);
    setListening(true);
    try {
      const heard = await voiceTranscribe(6);
      if (heard.transcript.trim()) setGoal(heard.transcript.trim());
    } catch (e) {
      setError((e as ApiError).message || "Couldn't hear you — check the mic.");
    } finally {
      setListening(false);
    }
  }

  useEffect(() => {
    getBriefing()
      .then((b) => {
        setData(b);
        if (!spokenRef.current) {
          spokenRef.current = true;
          voiceSay(b.spoken).catch(() => undefined); // speak greeting; ignore if no voice
        }
      })
      .catch((e: ApiError) => setError(e.message));
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

            <label className="briefing-prompt">{data.prompt}</label>
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
