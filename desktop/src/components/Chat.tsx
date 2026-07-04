import { useRef, useState } from "react";
import { sendChat, type ApiError, type ChatReply } from "../api";

interface Msg {
  role: "user" | "assistant";
  text: string;
  meta?: { model: string; prompt_tokens: number; completion_tokens: number };
}

// Chat panel. POSTs to /chat, threads via the returned conversation_id, and
// renders the small model/token usage line under each reply. Handles the 409
// "not set up" case and 502/429 model/budget errors gracefully.
export function Chat() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [convId, setConvId] = useState<string | null>(null);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  function scrollToBottom() {
    requestAnimationFrame(() => {
      const el = scrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    });
  }

  async function submit() {
    const text = input.trim();
    if (!text || busy) return;
    setError(null);
    setInput("");
    setMessages((m) => [...m, { role: "user", text }]);
    scrollToBottom();
    setBusy(true);
    try {
      const reply: ChatReply = await sendChat(text, convId);
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

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
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
          <div className="empty">
            Ask Jardo anything. Messages POST to <code>/chat</code> and thread by
            conversation id.
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

      <div className="composer">
        <textarea
          value={input}
          placeholder="Message Jardo…  (Enter to send, Shift+Enter for newline)"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          rows={2}
        />
        <button onClick={submit} disabled={busy || !input.trim()}>
          Send
        </button>
      </div>
    </div>
  );
}
