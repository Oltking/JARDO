<div align="center">
  <img src="desktop/public/jardo-logo.png" alt="Jardo" width="120" />
  <h1>Jardo</h1>
  <p><strong>Your personal supervisor for coding agents. It runs them for you, in your language.</strong></p>
</div>

---

## What Jardo is

Jardo is a voice-first AI assistant that sits above your coding agents (Claude Code, Gemini CLI) and **supervises them toward your goals**. You talk to it, in your own language. It sets up the project, launches the agent in your real terminal, and then stands watch: it reads the terminal, answers the agent's permission prompts against your goal, and steers the agent back on course when it drifts, so you do not have to sit there clicking *"Yes"* all day.

It is three things at once:

- **A supervisor and conductor.** It watches the agent work, approves the normal build/install/edit work, declines only what is genuinely destructive, and types precise guidance back into the terminal when the agent stalls or wanders off task.
- **A memory.** Ask *"where am I?"* and it tells you the goal, what is done, what is left, and what needs your attention, pulled from the agent's own session memory and git, not an expensive codebase re-scan.
- **A cost engine.** It routes every request to the cheapest capable model and caches aggressively, so you get premium results without premium bills.

Voice is the default everywhere, in nine languages. Open the app and it is already listening.

## The problem it solves

Coding agents are powerful but needy. They stop every few minutes to ask permission. They drift off task once you step away. They forget where they were between sessions. And leaving one running unattended is nerve-wracking.

Jardo is the layer that makes an agent something you can actually **delegate to**: it keeps it moving, keeps it on task, keeps it safe, and keeps it cheap.

## What makes it different

1. **Judgment, not a denylist.** Jardo does not blindly click yes, and it does not dumbly decline either. It reads the terminal like a senior engineer glancing over a teammate's shoulder, understands the command and the agent's own reasoning, and judges each action against your goal. It approves the real work an agent needs (installs, builds, tests, scaffolding, file edits, in-project git). It declines only genuinely destructive or off-task actions. Truly catastrophic or illegal actions (wiping a disk, deleting your home directory, active scanning of third parties) are refused outright, no matter what.
2. **It steers.** When the agent gets stuck, loops, or drifts, Jardo does not just wait. It composes a concrete, project-aware instruction and types it into the terminal to get the agent back on track. A conductor, not just a gate.
3. **In your language.** Speak and hear Jardo in English, French, Spanish, German, Portuguese, Italian, Arabic, Hindi, or Chinese. Your words and its replies are localized, while the reasoning core stays in English for accuracy, and Gemma does the translation.
4. **Cost as a first-class feature.** Inference runs on Gemma on AMD Instinct GPUs via ROCm, which is free and tried first for chat, supervision, and translation, with Fireworks AI as the instant fallback. Every request is routed to the cheapest capable model, and exact plus semantic caching means repeated work is never billed twice.
5. **Security-first and private.** Secrets live only in the macOS Keychain. Speech-to-text, text-to-speech, and memory recall run on your machine. A global kill-switch halts everything by hotkey. The audit log is append-only and redacts secrets. You can delete your entire profile at any time.

## Install

Jardo is a self-contained macOS app. No Docker, no database, no API key, nothing to configure.

**One command (recommended):**

```bash
curl -fsSL https://jardo.vercel.app/install.sh | bash
```

This downloads with `curl` (which does not trigger macOS quarantine), installs Jardo to your Applications folder, and launches it. No Gatekeeper warning, no right-click dance.

**Or the .dmg:** download it from the [website](https://jardo.vercel.app) or the [GitHub releases](https://github.com/Oltking/JARDO/releases). The build is self-signed but not Apple-notarized, so if you download it in a browser and macOS says it is "damaged," that is just the browser quarantine flag. Right-click the app and choose **Open**, or clear it once:

```bash
xattr -dr com.apple.quarantine ~/Downloads/Jardo_*.dmg
```

## First run

1. **Onboarding.** Set your name, how Jardo should address you, and your **language**. It also tells you which macOS permissions to expect (Microphone right away, Accessibility and Terminal control the first time you supervise).
2. **The first dollar is on us.** Every Mac gets a hosted AI trial with no key and no signup. Because it runs on Gemma on AMD first (free), most of what you do never spends the trial. Adding your own Fireworks or AMD Developer Cloud key in Settings is optional.
3. **Grant Accessibility when prompted.** Jardo presses the agent's answers with real keystrokes, so it needs Accessibility and Terminal (Automation) access. The app prompts you; click Allow.

Then just **talk to it** (in your language):

| Say... | Jardo... |
| --- | --- |
| *"Where am I?"* | Resumes your last project: goal, progress, what is left. |
| *"Supervise Claude in my terminal."* | Watches your terminal, answers prompts, and steers the agent. |
| *"Build me a todo app with Claude."* | Scaffolds it, launches the agent, and supervises it. |
| *"Who am I?" / "What can you do?"* | Answers instantly, itself, no model needed. |
| *"Stop."* | Stands down. |

Prefer typing? There is a text box for every one of these, and it translates typed input the same way.

## Under the hood

| Layer | Tech |
| --- | --- |
| Desktop | Tauri v2 · Rust · React + TypeScript + Vite |
| Core API | Python · FastAPI · SQLAlchemy async |
| Data | Embedded SQLite + in-process queue (packaged app); Postgres + pgvector + Redis (dev/server) |
| Voice | faster-whisper STT (multilingual) · Piper and macOS TTS · always-on, on-device |
| Inference | Gemma on AMD Instinct (ROCm) tried first and free · Fireworks AI fallback · Ollama local · routed by cost |
| Security | macOS Keychain secrets · local token · TOTP · Sentinel danger scan · append-only redacted audit log |

The packaged app ships everything inside it. The sensitive parts (your mic, your memory, the safety decisions) stay local.

## Cost optimization (the engine)

Jardo treats your token bill as something to actively minimize without losing quality:

- **Gemma on AMD, free.** Chat, supervision, and translation run on your AMD Instinct droplet first, so most usage costs nothing and never spends the trial.
- **Right-sized routing.** Trivial work stays local; harder work goes to the cheapest cloud model that clears an accuracy floor; Fireworks is the metered fallback.
- **Exact and semantic caching.** The same or a similar request is never billed twice.

## Multilingual voice

Jardo speaks nine languages out of the box: English, French, Spanish, German, Portuguese, Italian, Arabic, Hindi, and Chinese. The design translates at the edges: your speech is transcribed and translated to English for the core, and Jardo's replies are translated back and spoken with your language's native voice. The AI core stays in English so intent parsing, supervision, and command judgment never misfire. Change your language any time in Settings.

## Roadmap

- **Active token-budget awareness.** Watch the agent's context and have it compact before it hits the wall.
- **Windows support.** The whole thing, cross-platform.
- **Multi-agent conducting.** Supervise several agents and terminals at once.
- **Away-mode autonomy.** Trustworthy unattended runs with summaries, approvals, and verified handoff reports.

## Security and privacy

Jardo is built security-first. Secrets live only in the OS Keychain, never in files. A local token gates the core API. It never actively scans third-party systems. A **kill-switch** (tray, `⌘⇧⎋` hotkey, or the header) immediately halts the always-on listening and terminal supervision. Only truly catastrophic or illegal actions are ever hard-blocked; everything else is judged in context. Audit logs are append-only and secret-redacted, and you can wipe your entire profile from the app whenever you want.

---

<div align="center">
  <sub>Built to be the assistant you would actually trust with your terminal.</sub>
</div>
