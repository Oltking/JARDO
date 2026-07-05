import { useRef, useState } from "react";
import {
  sendChat,
  voiceSay,
  voiceTranscribe,
  type ApiError,
  type ChatReply,
} from "../api";
import { useInputMode } from "../useInputMode";

interface Msg {
  role: "user" | "assistant";
  text: string;
  meta?: { model: string; prompt_tokens: number; completion_tokens: number };
}

// Chat panel. Voice is the default input (mic → transcribe → send → spoken
// reply); the user can switch to typing and the choice persists app-wide.
// POSTs to /chat, threads via conversation_id, handles 409/429/502.
export function Chat() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [convId, setConvId] = useState<string | null>(null);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useInputMode();
  const scrollRef = useRef<HTMLDivElement>(null);

  function scrollToBottom() {
    requestAnimationFrame(() => {
      const el = scrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    });
  }

  async function send(text: string, speakReply: boolean) {
    const msg = text.trim();
    if (!msg || busy) return;
    setError(null);
    setInput("");
    setMessages((m) => [...m, { role: "user", text: msg }]);
    scrollToBottom();
    setBusy(true);
    try {
      const reply: ChatReply = await sendChat(msg, convId);
      setConvId(reply.conversation_id);
      setNeedsSetup(false);
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          text: reply.reply,
          meta: {
            model: reply.model,
            prompt_tokens: reply.prompt_tokens,
            completion_tokens: reply.completion_tokens,
          },
        },
      ]);
      if (speakReply) voiceSay(reply.reply).catch(() => undefined);
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 409) {
        setNeedsSetup(true);
      } else if (err.status === 429) {
        setError("Budget/rate limit reached (429). Try again later.");
      } else if (err.status === 502) {
        setError("The model backend is unavailable right now (502).");
      } else {
        setError(err.message || "Chat request failed.");
      }
    } finally {
      setBusy(false);
      scrollToBottom();
    }
  }

  // Voice input (default): record → transcribe → send → speak the reply.
  async function speakAndSend() {
    if (listening || busy) return;
    setError(null);
    setListening(true);
    try {
      const heard = await voiceTranscribe(6);
      if (heard.transcript.trim()) await send(heard.transcript, true);
      else setError("I didn't catch that — try again, or switch to typing.");
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 409 && (err.message || "").includes("voice")) {
        setError("Voice isn't available. Switch to typing.");
      } else {
        setError((err.message || "Couldn't hear you."));
      }
    } finally {
      setListening(false);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(input, false);
    }
  }

  return (
    <div className="chat">
      {needsSetup && (
        <div className="banner warn" role="alert">
          Jardo isn't set up yet. Run <code>jardo setup</code> in your terminal
          to configure identity, keys, and the model backend, then try again.
        </div>
      )}
      {error && (
        <div className="banner error" role="alert">
          {error}
        </div>
      )}

      <div className="messages" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="empty welcome">
            <img className="welcome-logo" src="/jardo-logo.png" alt="Jardo" />
            <p className="welcome-title">Jardo</p>
            <p className="welcome-sub">Your AI chief of staff. Ask anything.</p>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <div className="bubble">{m.text}</div>
            {m.meta && (
              <div className="usage">
                {m.meta.model} · {m.meta.prompt_tokens} in /{" "}
                {m.meta.completion_tokens} out tokens
              </div>
            )}
          </div>
        ))}
        {busy && <div className="msg assistant"><div className="bubble typing">…</div></div>}
      </div>

      {mode === "voice" ? (
        <div className="composer voice-composer">
          <button
            className={`mic-btn big ${listening ? "listening" : ""}`}
            onClick={speakAndSend}
            disabled={listening || busy}
          >
            {listening ? "● Listening…" : busy ? "…" : "🎤 Tap and speak"}
          </button>
          <button
            className="mode-toggle"
            onClick={() => setMode("text")}
            title="Type instead"
          >
            ⌨
          </button>
        </div>
      ) : (
        <div className="composer">
          <button
            className="mode-toggle"
            onClick={() => setMode("voice")}
            title="Speak instead"
          >
            🎤
          </button>
          <textarea
            value={input}
            placeholder="Message Jardo…  (Enter to send, Shift+Enter for newline)"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            rows={2}
          />
          <button onClick={() => send(input, false)} disabled={busy || !input.trim()}>
            Send
          </button>
        </div>
      )}
    </div>
  );
}
