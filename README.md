<div align="center">
  <img src="desktop/public/jardo-logo.png" alt="Jardo" width="120" />
  <h1>Jardo</h1>
  <p><strong>Your voice-first AI chief of staff — it conducts your coding agents while you're away.</strong></p>
</div>

---

## What Jardo is

Jardo is a lifelong personal AI that sits above your coding agents (Claude Code, Gemini CLI) and **runs them on your behalf**. You talk to it. It sets up the project, launches the agent in your real terminal, and — this is the point — **answers the agent's permission prompts for you** by checking each action against your goal and its safety, so you don't have to sit there clicking *"Yes"* all day.

It's built to be three things at once:

- **A supervisor** — it watches the agent work and approves what's safe and on-task, declines what isn't.
- **A memory** — ask *"where am I?"* and it tells you the goal, what's done, what's left, and what needs your attention.
- **A cost engine** — it routes every request to the cheapest model that clears an accuracy bar, and caches aggressively, so you get premium results without premium bills.

Voice is the default everywhere. Open the app and it's already listening.

## The problem it solves

Coding agents are powerful but needy. They stop every few minutes to ask permission. They forget where they were between sessions. They burn tokens re-reading your whole codebase. And leaving one running unattended is nerve-wracking — you don't know what it'll try.

Jardo is the layer that makes an agent something you can actually **delegate to**: it keeps it moving, keeps it on-task, keeps it safe, and keeps it cheap.

## What we're selling

> **A personal assistant that conducts coding agents for you — safely, continuously, and at a fraction of the token cost.**

The differentiators, in order:

1. **Autonomous supervision, not just automation.** Jardo decides for you after checking *safety* (a rule-based danger scan) and *purpose* (does this action serve the goal you stated?). It never blindly clicks yes. Risky actions are declined; genuinely dangerous ones are refused outright.
2. **Cost as a first-class feature.** A cost-accuracy router picks local → self-hosted AMD → Fireworks by live $/token math; exact + semantic response caching means repeated work is free; agent briefs push for small, committed steps to stay inside the session's token budget.
3. **Security-first by design.** Secrets live in the OS Keychain, never in files. A local API token gates every request. A global kill-switch halts everything. Audit logs are append-only and redact secrets.
4. **Private by default.** Speech-to-text, wake handling, and memory recall run **on your machine**. Nothing about your voice or your projects leaves the device unless a cloud model is actually needed.
5. **It remembers.** Jardo reads the agent's *own* on-disk memory to resume work — no expensive codebase re-scan just to answer "what was I doing?"

## What it does today

- 🎙️ **Always-on voice.** Opens listening — no tap, no wake word. Talk to it like a person.
- 🖥️ **Terminal supervision.** *"Supervise Claude in my terminal"* → it reads your terminal (without disturbing it) and presses the answer on each permission prompt, judged against your goal.
- 🧭 **"Where am I?"** Resume any project instantly — goal, recent progress, what's uncommitted, what needs your attention — pulled from the agent's session memory + git, not the codebase.
- 🚀 **New-project onboarding.** *"Build me a landing page with Claude"* → it scaffolds the folder, `git init`s, writes the agent's brief, opens a terminal, starts the agent, and supervises it — after a one-line confirmation.
- 💸 **Cost-accuracy router + caching.** Cheapest capable model, every time; repeats served from cache for free.
- 🔌 **Bring your own keys.** Paste a Fireworks or AMD key in Settings; Jardo uses whichever is set and prefers the cheaper one.
- 🔒 **Security controls.** Keychain-backed secrets, TOTP for high-privilege actions, kill-switch hotkey, redacted append-only audit log.
- 🧑 **Personal.** Set the name Jardo calls you and your projects folder; it remembers.

## How to use it

> **Status:** early, active development. macOS-first; Windows is on the roadmap. Requires Docker, Python 3.14, and (for the desktop app) Node/pnpm + Rust.

```bash
# 1. Infrastructure (Postgres + Redis)
docker compose -f infra/docker-compose.yml up -d

# 2. Python core
uv sync                       # add --extra voice for speech, --extra denoise for noise suppression
uv run jardo setup            # identity + optional cloud key → Keychain
uv run jardo serve            # runs the local API on 127.0.0.1

# 3. Desktop app (in another terminal)
cd desktop
pnpm install
pnpm tauri dev
```

Then just **talk to it**:

| Say… | Jardo… |
| --- | --- |
| *"Where am I?"* | Resumes your last project — goal, progress, what's left. |
| *"Supervise Claude in my terminal."* | Watches your terminal and answers the agent's prompts. |
| *"Build me a todo app with Claude."* | Scaffolds it, launches the agent, supervises it. |
| *"Who am I?" / "What can you do?"* | Answers instantly, itself — no model needed. |
| *"Stop."* | Stands down. |

Prefer typing? There's a text box for every one of these.

## Under the hood

| Layer | Tech |
| --- | --- |
| Core API | Python 3.14 · FastAPI · SQLAlchemy async · Arq workers |
| Data | Postgres + pgvector · Redis |
| Desktop | Tauri v2 · Rust · React + TypeScript + Vite |
| Voice | faster-whisper (STT) · Piper (TTS) · optional noisereduce · all on-device |
| Inference | Ollama (local) · Fireworks · AMD (self-hosted vLLM) — routed by cost |
| Security | macOS Keychain · TOTP (RFC 6238) · Sentinel danger scan · append-only audit |

The design keeps the sensitive parts local: your mic, your memory, and the safety decisions never require the cloud.

## Cost optimization (the engine)

Jardo treats your token bill as something to actively minimize without losing quality:

- **Right-sized routing** — trivial work stays local (free); hard work goes to the cheapest cloud model that passes an accuracy floor.
- **AMD vs Fireworks by live math** — self-hosted AMD (flat cost) wins for sustained work; Fireworks for bursts.
- **Exact + semantic caching** — the same (or similar) request is never billed twice.
- **Lean agent briefs** — agents are told to work in small committed steps and keep context tight, so sessions don't blow their token budget.

## Roadmap — what Jardo *will* be

- **Active token-budget awareness** — watch the agent's context and have it compact/summarize *before* it hits the wall.
- **Windows support** — the whole thing, cross-platform.
- **Multi-agent conducting** — supervise several agents and terminals at once.
- **Deeper project memory** — cross-session goals, standing preferences, and proactive "here's what needs your attention" briefings.
- **Away-mode autonomy** — trustworthy unattended runs while you're out, reporting back what it did.

## Security & privacy

Jardo is built security-first. Highlights: secrets only in the OS Keychain; a token gates the local API; passive checks only — never active scanning of third-party systems; a kill-switch that halts synthetic input instantly; audit logs that are append-only and secret-redacted.

---

<div align="center">
  <sub>Built to be the assistant you'd actually trust with your terminal.</sub>
</div>
