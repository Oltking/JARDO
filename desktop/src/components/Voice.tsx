import { useEffect, useRef, useState } from "react";
import {
  sendChat,
  voiceSay,
  voiceStatus,
  voiceTranscribe,
  voiceWake,
  type ApiError,
  type VoiceStatus,
} from "../api";

// Voice panel (spec §8). A continuous conversation: once started it keeps
// listening → answering → listening until you stop it, so you can ask follow-up
// questions without tapping again. Optional hands-free mode waits for the wake
// word ("hey Jardo") before each turn. An amplitude meter surfaces mic trouble.
type Phase = "idle" | "waking" | "listening" | "thinking" | "speaking";

const LOW_SIGNAL = 0.02;
const CLIPPING = 0.98;

export function Voice() {
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [handsFree, setHandsFree] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [amplitude, setAmplitude] = useState<number | null>(null);
  const [reply, setReply] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [needsSetup, setNeedsSetup] = useState(false);

  const runningRef = useRef(false);
  const convRef = useRef<string | null>(null);

  useEffect(() => {
    voiceStatus().then(setStatus).catch((e: ApiError) => setError(e.message));
    return () => {
      runningRef.current = false; // stop the loop if the tab unmounts
    };
  }, []);

  async function loop(withWake: boolean) {
    if (runningRef.current) return;
    runningRef.current = true;
    setError(null);
    setPhase(withWake ? "waking" : "listening");
    try {
      while (runningRef.current) {
        if (withWake) {
          setPhase("waking");
          const w = await voiceWake(30);
          if (!runningRef.current) break;
          if (!w.detected) continue; // timeout → keep waiting
        }
        setPhase("listening");
        const heard = await voiceTranscribe(5);
        if (!runningRef.current) break;
        setAmplitude(heard.amplitude);
        if (!heard.transcript.trim()) continue; // silence → listen again
        setTranscript(heard.transcript);
        setReply("");
        setPhase("thinking");
        const chat = await sendChat(heard.transcript, convRef.current);
        convRef.current = chat.conversation_id;
        setReply(chat.reply);
        setNeedsSetup(false);
        if (!runningRef.current) break;
        setPhase("speaking");
        await voiceSay(chat.reply);
      }
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 409 && !(err.message || "").includes("voice")) {
        setNeedsSetup(true);
      } else {
        setError(err.message || "Voice error.");
      }
      runningRef.current = false;
    } finally {
      setPhase("idle");
    }
  }

  function stop() {
    runningRef.current = false;
    setPhase("idle");
  }

  const active = phase !== "idle";
  const buttonLabel: Record<Phase, string> = {
    idle: handsFree ? "🎙 Start hands-free" : "🎙 Tap to talk",
    waking: "Say “hey Jardo”…",
    listening: "● Listening…",
    thinking: "… Thinking",
    speaking: "🔊 Speaking",
  };

  const selectedName = status?.input_devices?.find(
    (d) => d.index === status.selected_device
  )?.name;

  if (status && !status.available) {
    return (
      <div className="voice">
        <div className="banner warn">
          Voice isn't available: {status.reason ?? "the voice extra is not installed."}
          <br />
          Install it with <code>uv sync --extra voice</code>, then restart the core.
        </div>
      </div>
    );
  }

  return (
    <div className="voice">
      {needsSetup && (
        <div className="banner warn" role="alert">
          Jardo isn't set up yet. Run <code>jardo setup</code> first, then talk.
        </div>
      )}
      {error && (
        <div className="banner error" role="alert">
          {error}
        </div>
      )}

      <div className="voice-status">
        {selectedName ? (
          <span>
            Mic: <strong>{selectedName}</strong> · Voice:{" "}
            <strong>{status?.tts_voice}</strong>
          </span>
        ) : (
          <span>Checking voice…</span>
        )}
      </div>

      <button
        className={`talk-button ${phase}`}
        onClick={() => (active ? stop() : loop(handsFree))}
      >
        {buttonLabel[phase]}
      </button>

      {active ? (
        <button className="ghost voice-stop" onClick={stop}>
          Stop
        </button>
      ) : (
        <label className="handsfree-toggle">
          <input
            type="checkbox"
            checked={handsFree}
            onChange={(e) => setHandsFree(e.target.checked)}
          />
          Hands-free — wait for “hey Jardo” each turn
        </label>
      )}

      {amplitude !== null && (
        <div className="amp-meter">
          <div
            className="amp-fill"
            style={{ width: `${Math.min(100, amplitude * 400)}%` }}
          />
          <span className="amp-label">
            signal {amplitude.toFixed(3)}
            {amplitude < LOW_SIGNAL &&
              " — very quiet; raise input volume or disconnect Bluetooth audio"}
            {amplitude >= CLIPPING && " — clipping; lower mic input volume"}
          </span>
        </div>
      )}

      {transcript && (
        <div className="voice-line you">
          <span className="who">You</span>
          <span>{transcript}</span>
        </div>
      )}
      {reply && (
        <div className="voice-line jardo">
          <span className="who">Jardo</span>
          <span>{reply}</span>
        </div>
      )}

      {!transcript && !reply && !active && (
        <div className="empty">
          Start a conversation — Jardo keeps listening after each answer, so you can
          ask follow-ups without tapping again. Turn on hands-free to wake it with
          “hey Jardo”.
        </div>
      )}
    </div>
  );
}
