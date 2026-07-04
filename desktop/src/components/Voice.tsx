import { useEffect, useState } from "react";
import {
  sendChat,
  voiceSay,
  voiceStatus,
  voiceTranscribe,
  type ApiError,
  type VoiceStatus,
} from "../api";

// Voice panel (spec §8). Tap-to-talk: record → local STT → /chat → speak reply.
// Shows a capture-amplitude meter because a quiet signal (e.g. a Bluetooth
// headset ducking the built-in mic) is the usual reason transcription fails.
type Phase = "idle" | "listening" | "thinking" | "speaking";

const LOW_SIGNAL = 0.02; // below this, capture is effectively silence
const CLIPPING = 0.98; // at/above this the mic is clipping — lower input volume

export function Voice() {
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [transcript, setTranscript] = useState("");
  const [amplitude, setAmplitude] = useState<number | null>(null);
  const [reply, setReply] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [convId, setConvId] = useState<string | null>(null);

  useEffect(() => {
    voiceStatus()
      .then(setStatus)
      .catch((e: ApiError) => setError(e.message));
  }, []);

  async function talk() {
    if (phase !== "idle") return;
    setError(null);
    setTranscript("");
    setReply("");
    setAmplitude(null);
    setPhase("listening");
    try {
      const heard = await voiceTranscribe(5);
      setTranscript(heard.transcript);
      setAmplitude(heard.amplitude);
      if (!heard.transcript.trim()) {
        setPhase("idle");
        return;
      }
      setPhase("thinking");
      const chat = await sendChat(heard.transcript, convId);
      setConvId(chat.conversation_id);
      setReply(chat.reply);
      setNeedsSetup(false);
      setPhase("speaking");
      await voiceSay(chat.reply);
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 409) {
        // Could be voice-not-installed or chat-not-set-up; both surface here.
        if ((err.message || "").includes("voice")) setError(err.message);
        else setNeedsSetup(true);
      } else {
        setError(err.message || "Voice request failed.");
      }
    } finally {
      setPhase("idle");
    }
  }

  const selectedName =
    status?.input_devices?.find((d) => d.index === status.selected_device)?.name;

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
          JARVIS isn't set up yet. Run <code>jarvis setup</code> first, then talk.
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
          <span>Checking voice status…</span>
        )}
      </div>

      <button
        className={`talk-button ${phase}`}
        onClick={talk}
        disabled={phase !== "idle"}
      >
        {phase === "idle" && "🎙 Tap to talk"}
        {phase === "listening" && "● Listening…"}
        {phase === "thinking" && "… Thinking"}
        {phase === "speaking" && "🔊 Speaking"}
      </button>

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
            {amplitude >= CLIPPING &&
              " — clipping; lower mic input volume in System Settings"}
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
        <div className="voice-line jarvis">
          <span className="who">JARVIS</span>
          <span>{reply}</span>
        </div>
      )}

      {!transcript && !reply && phase === "idle" && (
        <div className="empty">
          Tap the button and speak. Your voice is transcribed locally
          (faster-whisper), answered by the routed model, and spoken back.
        </div>
      )}
    </div>
  );
}
