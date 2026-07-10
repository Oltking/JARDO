"""FastAPI application (Phase 1).

Loopback-only in Phase 1 (core.config). The chat path is:
persist user msg → persona prompt (identity + facts) → Fireworks → persist reply
→ enqueue fact-extraction job on the Arq queue → respond.
"""

import re
import uuid
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core import secrets
from core.config import settings
from core.db import engine, get_session, init_db, is_sqlite
from core.inference import providers
from core.inference.fireworks import FireworksClient, FireworksError
from core.inference.ollama import OllamaClient, OllamaUnavailable
from core.memory import MemoryStore
from core.persona import build_system_prompt
from core.router.classifier import HeuristicClassifier, ModelClassifier
from core.router.router import BudgetExceeded, CostRouter, RouteDecision, RouterConfig
from core.router.spend import log_decision, spent_today_usd


def _embedded_queue():
    """In-process queue + report scheduler for the self-contained (SQLite) build,
    mirroring core.worker.WorkerSettings without Redis/Arq."""
    from core.inproc_queue import InProcessQueue
    from core.worker import (
        daily_report,
        extract_facts,
        hourly_report,
        weekly_report,
    )

    queue = InProcessQueue({"extract_facts": extract_facts})
    queue.start_scheduler([
        (hourly_report, lambda n: n.minute == 0),
        (daily_report, lambda n: n.hour == 7 and n.minute == 5),
        (weekly_report, lambda n: n.weekday() == 0 and n.hour == 7 and n.minute == 10),
    ])
    return queue


@asynccontextmanager
async def lifespan(app: FastAPI):
    # A Finder-launched .app has a minimal PATH; restore the user's real PATH so
    # coding-agent CLIs (claude, gemini), npm, and git are found (fixes the
    # bundled-app "claude cli not in path").
    from core.env_path import ensure_full_path
    ensure_full_path()
    if is_sqlite():
        # Embedded build: create tables from the models (no Alembic) and run jobs
        # in-process instead of requiring Postgres + Redis.
        await init_db()
        app.state.arq = _embedded_queue()
    else:
        app.state.arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    app.state.ollama = OllamaClient()
    config = RouterConfig.load()
    app.state.router = CostRouter(config)
    if config.classifier == "model":
        app.state.classifier = ModelClassifier(
            app.state.ollama, config.tiers.get("ollama_local", "llama3.2:3b"),
            HeuristicClassifier(),
        )
    else:
        app.state.classifier = HeuristicClassifier()
    yield
    await app.state.arq.aclose()
    await engine.dispose()


app = FastAPI(title="Jardo core", lifespan=lifespan)

# Loopback-only in Phase 1; the Tauri desktop webview (tauri://, localhost dev
# server) calls this API directly. Remote origins get nothing (mTLS arrives §5).
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(tauri://localhost|https?://localhost(:\d+)?|https?://127\.0\.0\.1(:\d+)?)$",
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared bearer token gates every request except health + CORS preflight, so a
# stray local process can't drive Jardo (finding #2). Legit clients read the
# same token file (core/api_auth).
from fastapi.responses import JSONResponse  # noqa: E402

from core.api_auth import get_or_create_token  # noqa: E402

_API_TOKEN = get_or_create_token()
_AUTH_EXEMPT = {"/healthz"}

# Input bounds (audit MEDIUM): keep a huge paste / adversarial input from blowing
# the context window and cost. Chat gets room for real content; routing needs little.
_MAX_CHAT_CHARS = 8000
_MAX_ROUTE_CHARS = 2000


import hmac  # noqa: E402

_EXPECTED_AUTH = f"Bearer {_API_TOKEN}"


@app.middleware("http")
async def _require_token(request, call_next):
    if request.method == "OPTIONS" or request.url.path in _AUTH_EXEMPT:
        return await call_next(request)
    # Constant-time compare so the token can't be recovered by timing (audit #3).
    if not hmac.compare_digest(request.headers.get("authorization", ""), _EXPECTED_AUTH):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


def _premium_frontdoor(decision: RouteDecision, cloud_ready: bool,
                       input_tokens: int = 0) -> RouteDecision:
    """Jardo's own replies are its face. When a cloud key exists, don't let the
    tiny local model answer the owner — upgrade the conversation to a solid cloud
    tier (the owner chose "premium when a key is set"). Bulk/agent work keeps
    routing by cost elsewhere; this only rescues the weak local path.

    The upgrade is priced (audit #5) so it counts against the daily budget instead
    of being logged as free — otherwise the cost ceiling would never trip on chat."""
    if not cloud_ready or decision.backend != "ollama":
        return decision
    config = RouterConfig.load()
    model = config.tiers.get("fireworks_mid") or config.tiers.get(
        "fireworks_cheap", "fireworks/gpt-oss-20b")
    est = 0.0
    try:
        from core.router.pricing import estimate_cost_usd, load_pricing
        pricing = load_pricing()
        if model in pricing:
            est = estimate_cost_usd(pricing[model], input_tokens, config.est_output_tokens)
    except Exception:  # noqa: BLE001 — pricing missing → fall back to 0, still routes
        pass
    return RouteDecision(
        "fireworks", model, decision.task_label, est_cost_usd=est,
        alternative_cost_usd=est, saved_usd=0.0, floor="premium",  # ≤16 chars (routing_log)
        reason="front-door upgraded to premium (cloud key set)")


async def _dispatch(decision: RouteDecision, messages: list[dict]):
    """Route a chat to the decided backend. Cloud providers (Fireworks, AMD) both
    speak the OpenAI-compatible protocol, so one client serves both; core.inference
    .providers picks whichever key the owner configured and falls back gracefully
    so a missing key degrades instead of 500ing (spec §5)."""
    if decision.backend == "ollama":
        return await app.state.ollama.chat(decision.model, messages)

    # A vLLM route means AMD; anything else means Fireworks. If the intended
    # provider isn't ready, fall back to any other configured provider so the
    # owner never hits a dead end just because one key is missing.
    intended = "amd" if decision.backend == "vllm" else "fireworks"
    order = [intended] + [p for p in providers.configured() if p != intended]
    chosen = next((p for p in order if providers.is_ready(p)), None)
    if chosen is None:
        raise HTTPException(
            status_code=409,
            detail="No cloud provider is configured. Add a Fireworks or AMD key in "
                   "Settings → Providers. Local tip: install Ollama for key-free chat.",
        )
    client = providers.make_client(chosen, timeout=settings.request_timeout_seconds)
    # Cap the reply length to keep paid output tokens down (spec §5). The persona
    # already asks for brevity; this is the hard ceiling.
    return await client.chat(providers.resolve_model(chosen, decision.model), messages,
                             max_tokens=settings.chat_max_tokens)


class ChatRequest(BaseModel):
    message: str
    conversation_id: uuid.UUID | None = None


class ChatResponse(BaseModel):
    reply: str
    conversation_id: uuid.UUID
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None


@app.get("/stats/savings")
async def savings_stats(session: AsyncSession = Depends(get_session)) -> dict:
    """The value-prop, made visible: spend, savings, local %, cache hits (§5)."""
    from core.router.spend import savings_summary
    return await savings_summary(session)


@app.get("/cache/stats")
async def cache_statistics(session: AsyncSession = Depends(get_session)) -> dict:
    """Cost-optimization cache stats: entries, hits, and tokens saved (§5)."""
    from core.cache import cache_stats
    return await cache_stats(session)


@app.get("/healthz")
async def healthz(session: AsyncSession = Depends(get_session)) -> dict:
    await session.execute(text("SELECT 1"))
    redis_ok = await app.state.arq.ping()
    return {"status": "ok", "db": "ok", "redis": "ok" if redis_ok else "down"}


@app.get("/approvals")
async def list_approvals(session: AsyncSession = Depends(get_session)) -> list[dict]:
    """Pending escalations for the desktop Permission UI (spec §6.5)."""
    from sqlalchemy import select
    from core.schema import Approval

    rows = (await session.execute(
        select(Approval).where(Approval.status == "pending").order_by(Approval.created_at)
    )).scalars().all()
    return [
        {"id": str(r.id), "actor": r.actor, "action_type": r.action_type,
         "target": r.target, "stated_goal": r.stated_goal, "severity": r.severity,
         "created_at": r.created_at.isoformat()}
        for r in rows
    ]


class ApprovalDecision(BaseModel):
    approve: bool


@app.post("/approvals/{approval_id}/decide")
async def decide_approval(approval_id: uuid.UUID, decision: ApprovalDecision,
                          session: AsyncSession = Depends(get_session)) -> dict:
    from core.sentinel.broker import decide_pending

    result = await decide_pending(session, approval_id, decision.approve)
    if result is None:
        raise HTTPException(status_code=404, detail="Not found or already decided")
    await session.commit()
    return {"id": str(result.id), "status": result.status}


# ---- Provider settings (spec §5) — paste a Fireworks or AMD key; Jardo uses
# whichever is configured. Keys go straight to the Keychain, never echoed back.

class ProviderKeyRequest(BaseModel):
    api_key: str | None = None
    base_url: str | None = None  # AMD endpoint (URL, not a secret)


@app.get("/settings/providers")
async def get_providers() -> dict:
    return {"providers": providers.status(), "active": providers.configured()}


@app.post("/settings/providers/{name}")
async def set_provider(name: str, body: ProviderKeyRequest) -> dict:
    if name not in providers.PROVIDERS:
        raise HTTPException(status_code=404, detail=f"unknown provider {name!r}")
    if body.api_key and body.api_key.strip():
        try:
            secrets.write_secret(providers.PROVIDERS[name].secret_service,
                                 body.api_key.strip())
        except secrets.SecretsUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    if body.base_url is not None:
        providers.set_base_url(name, body.base_url)
    return {"providers": providers.status(), "active": providers.configured()}


# ---- Identity settings — the name Jardo calls the owner (spec §1). Per-user,
# set at setup but editable here so it's a real product setting, not hardcoded.

class IdentityRequest(BaseModel):
    name: str | None = None
    pronoun_style: str | None = None  # "sir" | "ma"
    email: str | None = None          # optional; a local placeholder is used if absent
    language: str | None = None       # voice language code (i18n.LANGUAGES); "en" default


@app.get("/settings/identity")
async def get_identity(session: AsyncSession = Depends(get_session)) -> dict:
    from core import i18n
    owner = await MemoryStore(session).get_owner()
    if owner is None:
        return {"name": None, "pronoun_style": None, "language": i18n.current()}
    return {"name": owner.name, "pronoun_style": owner.pronoun_style,
            "language": i18n.current()}


@app.post("/settings/identity")
async def set_identity(body: IdentityRequest,
                       session: AsyncSession = Depends(get_session)) -> dict:
    from core import i18n
    store = MemoryStore(session)
    owner = await store.get_owner()
    # Voice language is a device preference (kv store), independent of the owner row.
    if body.language is not None:
        i18n.set_language(body.language)
    if owner is None:
        # First-run onboarding, in-app (no CLI). A shipped user has no terminal,
        # so entering a name here creates the owner record + device keypair.
        if not (body.name and body.name.strip()):
            raise HTTPException(status_code=400,
                                detail="Tell me your name to get started.")
        import re

        from core.identity import create_owner
        name = body.name.strip()[:120]
        pronoun = body.pronoun_style if body.pronoun_style in ("sir", "ma") else "sir"
        slug = re.sub(r"[^a-z0-9]+", "", name.lower()) or "owner"
        email = (body.email or "").strip() or f"{slug}@jardo.local"
        owner = await create_owner(session, name, pronoun, email)
        await store.audit("app", "owner.created", {"owner_id": str(owner.id)})
        await session.commit()
        return {"name": owner.name, "pronoun_style": owner.pronoun_style,
                "language": i18n.current()}
    if body.name and body.name.strip():
        owner.name = body.name.strip()[:120]
    if body.pronoun_style in ("sir", "ma"):
        owner.pronoun_style = body.pronoun_style
    await session.commit()
    return {"name": owner.name, "pronoun_style": owner.pronoun_style,
            "language": i18n.current()}


async def _model_chat(prompt: str, max_tokens: int = 700) -> str:
    """A single chat-model call for utility tasks (translation). Prefers the hosted
    provider (Gemma on AMD / Fireworks), falling back to a local Ollama model."""
    from core.inference import providers
    from core.router.router import RouterConfig

    msgs = [{"role": "user", "content": prompt}]
    if providers.configured():
        chosen = providers.configured()[0]
        model = RouterConfig.load().tiers.get("fireworks_cheap", "fireworks/gpt-oss-20b")
        client = providers.make_client(chosen, timeout=30)
        r = await client.chat(providers.resolve_model(chosen, model), msgs,
                              max_tokens=max_tokens, temperature=0.0)
        return r.content
    r = await app.state.ollama.chat(
        RouterConfig.load().tiers.get("ollama_local", "qwen2.5:0.5b"), msgs)
    return r.content


@app.get("/i18n/languages")
async def i18n_languages() -> dict:
    from core import i18n
    return {"languages": i18n.catalog(), "current": i18n.current()}


class TranslateRequest(BaseModel):
    text: str
    to: str | None = None  # target language code; defaults to the current language


@app.post("/i18n/translate")
async def i18n_translate(body: TranslateRequest) -> dict:
    """Translate text into the target (default: the user's chosen language). Used to
    localize Jardo's English replies for display + speech."""
    from core import i18n
    target = i18n.normalize(body.to or i18n.current())
    out = await i18n.translate(body.text, target, _model_chat)
    return {"text": out, "language": target}


@app.post("/settings/reset")
async def reset_account() -> dict:
    """Wipe this device's profile and memory (owner, conversations, memories,
    projects, approvals, audit). For the in-app "delete my data" control: a user
    on their own Mac can start over as if newly installed. Drops and recreates
    every table, clears Keychain secrets, and forgets the anonymous device id."""
    from pathlib import Path

    from core import db, secrets

    import core.schema  # noqa: F401 — register models on Base
    async with db.engine.begin() as conn:
        await conn.run_sync(db.Base.metadata.drop_all)
        await conn.run_sync(db.Base.metadata.create_all)

    # Secrets live only in the Keychain, never in files — clear them too.
    for svc in (secrets.FIREWORKS_API_KEY, secrets.AMD_API_KEY,
                secrets.DEVICE_PRIVATE_KEY, secrets.TOTP_SECRET):
        try:
            secrets.delete_secret(svc)
        except Exception:  # noqa: BLE001 — a missing secret is fine
            pass

    # Clear non-secret device preferences (language, projects root, terminal
    # choice, learned allow-list) so the wipe truly returns to a new-user state.
    try:
        (Path.home() / ".jardo" / "settings.json").unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass

    # Forget the anonymous trial device id so a fresh one is minted next call.
    try:
        (Path.home() / ".jardo" / "device_id").unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True}


# ---- Projects (spec §4.5) — "where am I?" resume-work. The owner picks a folder
# (or Jardo lists their projects root); Jardo answers from the agent's own memory
# + git, never by re-reading the codebase.

class WhereAmIRequest(BaseModel):
    path: str | None = None  # None → most-recently-opened project


class TerminalChoiceRequest(BaseModel):
    terminal: str


@app.get("/settings/terminal")
async def get_terminal_choice() -> dict:
    from core import appsettings
    from core.agents.terminals import SUPPORTED
    current = appsettings.get("supervise_terminal") or settings.supervise_terminal
    return {"terminal": current, "supported": list(SUPPORTED),
            "hook_only": ["warp", "vscode"]}


@app.post("/settings/terminal")
async def set_terminal_choice(body: TerminalChoiceRequest) -> dict:
    from core import appsettings
    appsettings.set("supervise_terminal", body.terminal.strip().lower())
    from core.agents import terminal_watch
    return {"terminal": body.terminal.strip().lower(),
            "scriptable": terminal_watch.supervised_terminal_ok()}


@app.get("/settings/projects-root")
async def get_projects_root() -> dict:
    from core import appsettings
    return {"root": appsettings.get("projects_root")}


@app.post("/settings/projects-root")
async def set_projects_root(body: WhereAmIRequest) -> dict:
    from core import appsettings
    from core.projects import choose_folder
    root = (body.path or "").strip() or choose_folder("Pick the folder that holds "
                                                      "all your projects")
    if not root:
        raise HTTPException(status_code=409, detail="No folder chosen.")
    appsettings.set("projects_root", root)
    return {"root": root}


@app.get("/projects")
async def list_projects(session: AsyncSession = Depends(get_session)) -> dict:
    from core import appsettings
    from core.projects import ProjectStore, list_folders

    owner = await MemoryStore(session).get_owner()
    tracked = await ProjectStore(session).list(owner.id) if owner else []
    root = appsettings.get("projects_root")
    return {
        "root": root,
        "folders": list_folders(root) if root else [],
        "tracked": [{"name": p.name, "path": p.path, "goal": p.goal,
                     "last_opened_at": p.last_opened_at.isoformat()} for p in tracked],
    }


@app.post("/projects/choose")
async def projects_choose() -> dict:
    from core.projects import choose_folder
    path = choose_folder()
    if not path:
        raise HTTPException(status_code=409, detail="No folder chosen.")
    return {"path": path}


@app.post("/projects/whereami")
async def projects_whereami(body: WhereAmIRequest,
                            session: AsyncSession = Depends(get_session)) -> dict:
    from core.projects import ProjectStore, inspect_project, where_am_i

    owner = await MemoryStore(session).get_owner()
    if owner is None:
        raise HTTPException(status_code=409, detail="Not set up. Run: jardo setup")
    store = ProjectStore(session)

    path = (body.path or "").strip()
    if not path:
        active = await store.get_active(owner.id)
        if active is None:
            # Nothing to resume — the UI should offer a folder pick.
            return {"needs_folder": True}
        path = active.path

    project = await store.upsert(owner.id, path)  # register + mark most-recent
    answer = where_am_i(inspect_project(project.path, goal=project.goal))
    await session.commit()
    return answer


class StartProjectRequest(BaseModel):
    goal: str
    agent: str = "claude"
    name: str | None = None
    location: str | None = None      # parent dir; defaults to the projects root
    existing_path: str | None = None  # resume/onboard an existing folder instead
    details: str | None = None        # owner's fuller description of what to build
    spec_text: str | None = None      # contents of an attached spec file (optional)
    spec_filename: str | None = None  # original filename of the attached spec


@app.post("/projects/start")
async def projects_start(body: StartProjectRequest,
                         session: AsyncSession = Depends(get_session)) -> dict:
    """Onboard a project and hand it to a coding agent: scaffold (or reuse) the
    folder, brief the agent, record it, and launch the agent in a real terminal
    that Jardo then supervises."""
    from core.agents import onboard, terminal_watch
    from core.agents.adapters import get_adapter
    from core import appsettings
    from core.projects import ProjectStore
    from core.supervision import start_session

    owner = await MemoryStore(session).get_owner()
    if owner is None:
        raise HTTPException(status_code=409, detail="Not set up. Run: jardo setup")
    if not body.goal.strip():
        raise HTTPException(status_code=400, detail="Tell me what to build.")

    adapter = get_adapter(body.agent)
    if adapter is None or not adapter.installed():
        raise HTTPException(
            status_code=409,
            detail=f"{body.agent} isn't installed (its CLI isn't on PATH).")

    # No ungated execution (spec §0.3): the launch goes through the Sentinel
    # decider like every other action Jardo takes (audit #8).
    from core.autonomy.decider import autonomous_decision
    gate = await autonomous_decision(
        session, f"{adapter.cli} (start build: {body.goal.strip()})", body.goal.strip())
    if not gate.approve:
        raise HTTPException(status_code=409, detail=f"Refused: {gate.reason}")

    if body.existing_path:
        path = os.path.abspath(os.path.expanduser(body.existing_path))
        if not os.path.isdir(path):
            raise HTTPException(status_code=409, detail=f"No folder at {path}.")
        name, created = os.path.basename(path), False
    else:
        parent = body.location or appsettings.get("projects_root")
        if not parent:
            return {"needs_root": True}  # UI prompts the owner to pick a root
        proj = onboard.scaffold_project(
            parent, body.name or onboard.derive_name(body.goal),
            body.goal, body.agent,
            details=body.details, spec_text=body.spec_text,
            spec_filename=body.spec_filename)
        path, name, created = proj.path, proj.name, proj.created

    await ProjectStore(session).upsert(owner.id, path, name=name, goal=body.goal.strip())
    await start_session(session, owner.id, body.goal.strip(), agent=body.agent)
    await MemoryStore(session).audit("jardo", "project.started",
                                     {"path": path, "agent": body.agent,
                                      "goal": body.goal.strip()[:300], "created": created})
    app.state.answered_prompts = set()
    await session.commit()

    launched = True
    launch_error = None
    try:
        # Pin supervision to the new window so we watch exactly this terminal.
        app.state.supervise_window_id = terminal_watch.open_interactive(
            onboard.launch_shell(adapter.cli, path, body.agent))
    except Exception as exc:  # noqa: BLE001 — folder is ready even if launch fails
        launched = False
        launch_error = str(exc)[:200]
        import logging
        logging.getLogger("jardo.terminal").warning("terminal launch failed: %s", exc)

    return {"ok": True, "path": path, "name": name, "goal": body.goal.strip(),
            "agent": body.agent, "created": created, "launched": launched,
            "launch_error": launch_error}


@app.get("/memory")
async def list_memory(session: AsyncSession = Depends(get_session)) -> list[dict]:
    store = MemoryStore(session)
    owner = await store.get_owner()
    if owner is None:
        raise HTTPException(status_code=409, detail="Not set up. Run: jardo setup")
    facts = await store.list_facts(owner.id)
    return [
        {"id": str(f.id), "kind": f.kind, "content": f.content, "source": f.source}
        for f in facts
    ]


# ---- Voice endpoints (spec §8) — drive the local mic/STT/TTS from the desktop UI.
# Audio work is blocking + CPU-bound, so it runs in a threadpool off the event loop.
# Voice deps are an optional extra; endpoints degrade gracefully if absent.

class TranscribeRequest(BaseModel):
    seconds: float = 5.0          # legacy fixed-window seconds (used if auto_stop=false)
    auto_stop: bool = True        # end recording when the speaker stops (silence)
    max_seconds: float = 15.0     # hard cap for auto-stop
    listen_timeout: float = 10.0  # wait this long for speech to start before giving up


class SayRequest(BaseModel):
    text: str


def _voice_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        import sounddevice  # noqa: F401
        return True
    except ImportError:
        return False


@app.get("/voice/status")
async def voice_status() -> dict:
    if not _voice_available():
        return {"available": False, "reason": "voice extra not installed "
                "(uv sync --extra voice)"}
    from core.voice import mic
    from starlette.concurrency import run_in_threadpool
    devices = await run_in_threadpool(mic.list_input_devices)
    selected = await run_in_threadpool(mic.pick_builtin_mic)
    # Warm the STT model in the background so the first spoken turn isn't slow
    # (the model-load cost is paid now, while the app is just opening). On a fresh
    # install this also DOWNLOADS the model once — we flag that so the UI can show a
    # one-time "setting up voice" state without blocking chat. This is LANGUAGE-aware:
    # a non-English user needs the multilingual model warmed, not the English one, or
    # transcribe would sit at model_pending forever without ever fetching it.
    from core import i18n
    lang = i18n.current()
    stt = _get_stt(lang)
    warmed = getattr(app.state, "warmed_langs", None)
    if warmed is None:
        warmed = app.state.warmed_langs = set()
    if lang not in warmed:
        import threading
        warmed.add(lang)
        app.state.voice_downloading = not stt.is_ready()

        def _warm(s=stt):
            try:
                s.warmup()
            finally:
                app.state.voice_downloading = False

        threading.Thread(target=_warm, daemon=True).start()
    voice_label = (
        "Piper (neural)" if settings.voice_tts_backend == "piper"
        else settings.voice_tts_voice
    )
    return {
        "available": True,
        "model_ready": stt.is_ready(),
        "model_downloading": bool(getattr(app.state, "voice_downloading", False)),
        "tts_backend": settings.voice_tts_backend,
        "tts_voice": voice_label,
        "input_devices": [{"index": i, "name": n} for i, n in devices],
        "selected_device": selected,
    }


@app.post("/voice/transcribe")
async def voice_transcribe(request: TranscribeRequest) -> dict:
    if not _voice_available():
        raise HTTPException(status_code=409, detail="voice extra not installed")
    import numpy as np
    from starlette.concurrency import run_in_threadpool
    from core import i18n
    from core.voice import mic

    lang = i18n.current()
    stt = _get_stt(lang)

    # First run: the speech model may still be downloading (~180 MB). Don't record
    # or block on the download here — answer instantly so the client can show the
    # "setting up voice" state instead of the request timing out.
    if not stt.is_ready():
        return {"transcript": "", "amplitude": 0.0, "heard": False,
                "model_pending": True}

    # Recording (PortAudio) and transcription must never 500 or crash the core —
    # a denied mic or a transient audio error just means "nothing heard".
    try:
        if request.auto_stop:
            audio = await run_in_threadpool(
                mic.record_until_silence, request.max_seconds,
                settings.voice_silence_ms, request.listen_timeout)
        else:
            audio = await run_in_threadpool(mic.record_seconds, request.seconds)
        heard = bool(audio.size)
        amplitude = (float(np.abs(audio.astype(np.float32) / 32768.0).max())
                     if heard else 0.0)
        native = await run_in_threadpool(stt.transcribe, audio) if heard else ""
    except Exception as exc:  # noqa: BLE001 — voice is best-effort, never fatal
        import logging
        logging.getLogger("jardo.voice").warning("transcribe failed: %s", exc)
        return {"transcript": "", "amplitude": 0.0, "heard": False,
                "error": str(exc)[:200]}

    # Non-English: transcribe in the user's language (shown as what they said), then
    # translate to English so the English-tuned core logic works unchanged.
    english = native
    if native and lang != "en":
        english = await i18n.to_english(native, lang, _model_chat)

    # heard=false means no speech within listen_timeout (silence) — callers use
    # this to end an auto-listen session. `transcript` is English (for the core);
    # `native` is what the user actually said (for the chat bubble).
    return {"transcript": english, "native": native,
            "amplitude": round(amplitude, 4), "heard": heard}


def _get_stt(language: str):
    """A cached SpeechToText per language. English uses the fast English-only model;
    other languages use the multilingual model pinned to that language."""
    from core import i18n
    from core.voice.stt import SpeechToText

    lang = i18n.normalize(language)
    cache = getattr(app.state, "stt_by_lang", None)
    if cache is None:
        cache = app.state.stt_by_lang = {}
    if lang not in cache:
        if lang == "en":
            cache[lang] = SpeechToText(settings.voice_stt_model)
        else:
            # Multilingual model (drop the ".en" suffix) pinned to the user's tongue.
            base = settings.voice_stt_model.replace(".en", "") or "small"
            cache[lang] = SpeechToText(base, language=i18n.whisper_lang(lang))
    return cache[lang]


class WakeRequest(BaseModel):
    timeout: float = 30.0


@app.post("/voice/wake")
async def voice_wake(request: WakeRequest) -> dict:
    """Block until the wake word ('hey Jardo') is heard or timeout (spec §8).
    Used by the desktop hands-free mode. Reuses the STT-based detector."""
    if not _voice_available():
        raise HTTPException(status_code=409, detail="voice extra not installed")
    from starlette.concurrency import run_in_threadpool
    from core.voice.stt import SpeechToText
    from core.voice.wakeword import WhisperWakeDetector

    if not hasattr(app.state, "stt"):
        app.state.stt = SpeechToText(settings.voice_stt_model)
    detector = WhisperWakeDetector(app.state.stt)
    detected = await run_in_threadpool(detector.listen, request.timeout)
    return {"detected": detected}


@app.post("/voice/say")
async def voice_say(request: SayRequest) -> dict:
    if not _voice_available():
        raise HTTPException(status_code=409, detail="voice extra not installed")
    from starlette.concurrency import run_in_threadpool
    from core import i18n
    from core.voice.tts import get_tts

    lang = i18n.current()
    if lang == "en":
        tts = get_tts(settings.voice_tts_backend, voice=settings.voice_tts_voice,
                      model_path=settings.voice_piper_model)
    else:
        # The bundled Piper voice is English-only; for other languages use macOS
        # `say` with that language's native system voice.
        tts = get_tts("say", voice=i18n.macos_voice(lang))
    await run_in_threadpool(tts.speak, request.text)
    return {"spoken": True}


# ---- Conversational build front-door: Jardo interviews, then conducts the agent.

class IntakeRequest(BaseModel):
    message: str
    session_id: str | None = None


async def _intake_chat_fn(session: AsyncSession):
    """Cost-optimized model call for the intake conversation (local + cache)."""
    from core.cache import cached_call
    from core.router.router import RouterConfig

    model = RouterConfig.load().tiers.get("ollama_local", "qwen2.5:0.5b")

    async def chat_fn(messages: list[dict]) -> str:
        async def miss() -> tuple[str, int]:
            r = await app.state.ollama.chat(model, messages)
            return r.content, (r.prompt_tokens or 0) + (r.completion_tokens or 0)
        res = await cached_call(session, model, messages, miss)
        return res.content

    return chat_fn


@app.post("/build/intake")
async def build_intake(request: IntakeRequest,
                       session: AsyncSession = Depends(get_session)) -> dict:
    """One turn of the build interview. Returns Jardo's question/recommendation,
    and when ready, the compiled brief + the agent to run."""
    import uuid as _uuid

    from core.agents.intake import intake_turn, parse_build_request

    store = getattr(app.state, "build_intakes", None)
    if store is None:
        store = app.state.build_intakes = {}

    if request.session_id and request.session_id in store:
        sid = request.session_id
        st = store[sid]
    else:
        what, agent = parse_build_request(request.message)
        sid = _uuid.uuid4().hex[:12]
        st = store[sid] = {"agent": agent, "what": what, "history": []}

    chat_fn = await _intake_chat_fn(session)
    turn = await intake_turn(st["agent"], st["history"], request.message, chat_fn)
    st["history"].append({"role": "user", "content": request.message})
    st["history"].append({"role": "assistant",
                          "content": turn.brief or turn.reply})
    if turn.ready:
        st["brief"] = turn.brief
    await session.commit()
    return {"session_id": sid, "reply": turn.reply, "ready": turn.ready,
            "brief": turn.brief, "agent": st["agent"], "what": st["what"]}


class BuildRunRequest(BaseModel):
    session_id: str
    directory: str
    run: bool = False


@app.post("/build/run")
async def build_run(request: BuildRunRequest,
                    session: AsyncSession = Depends(get_session)) -> dict:
    """Write the compiled brief into the project folder and conduct the agent."""
    from pathlib import Path

    from core.agents.runner import conduct

    store = getattr(app.state, "build_intakes", {})
    st = store.get(request.session_id)
    if st is None or not st.get("brief"):
        raise HTTPException(status_code=409, detail="No completed brief for this session")
    folder = Path(request.directory).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SPEC.md").write_text(st["brief"], encoding="utf-8")

    result = await conduct(session, st["what"], st["agent"], str(folder),
                           execute=request.run)
    await session.commit()
    return {"agent": result.agent, "model": result.model, "executed": result.executed,
            "visible": result.visible, "workspace": result.workspace,
            "note": result.note, "warnings": result.warnings,
            "output": result.output[-1500:] if result.output else ""}


# ---- Reports inbox (spec §4.4): hourly/daily/weekly rollups.

def _report_row(r) -> dict:
    return {"id": str(r.id), "period": r.period, "body": r.body,
            "stats": r.stats, "created_at": r.created_at.isoformat()}


@app.get("/reports")
async def list_reports(session: AsyncSession = Depends(get_session),
                       limit: int = 30) -> list[dict]:
    from sqlalchemy import select
    from core.schema import Report

    rows = (await session.execute(
        select(Report).order_by(Report.created_at.desc()).limit(limit)
    )).scalars().all()
    return [_report_row(r) for r in rows]


class GenerateReportRequest(BaseModel):
    period: str = "daily"


@app.post("/reports/generate")
async def generate_report_now(request: GenerateReportRequest,
                              session: AsyncSession = Depends(get_session)) -> dict:
    from core.memory import MemoryStore
    from core.reporter import generate_report

    if request.period not in ("hourly", "daily", "weekly"):
        raise HTTPException(status_code=400, detail="period must be hourly, daily, or weekly")
    owner = await MemoryStore(session).get_owner()
    honorific = owner.pronoun_style if owner else "sir"
    report = await generate_report(session, request.period, honorific=honorific)
    await session.commit()
    return _report_row(report)


# ---- Launch briefing + daily objective (spec §4.5).

@app.get("/briefing")
async def briefing(session: AsyncSession = Depends(get_session)) -> dict:
    """Greeting + updates + the day's-objective prompt, shown on app launch."""
    from core.briefing import assemble_briefing
    return await assemble_briefing(session)


class ObjectiveRequest(BaseModel):
    objective: str


@app.get("/supervision")
async def supervision_status(session: AsyncSession = Depends(get_session)) -> dict:
    from core.supervision import get_active
    active = await get_active(session)
    return {"objective": active.objective if active else None}


@app.post("/supervision")
async def supervision_start(request: ObjectiveRequest,
                            session: AsyncSession = Depends(get_session)) -> dict:
    """Set the day's objective; Jardo supervises agents against it (spec §4.3)."""
    from core.memory import MemoryStore
    from core.supervision import start_session

    owner = await MemoryStore(session).get_owner()
    if owner is None:
        raise HTTPException(status_code=409, detail="Not set up. Run: jardo setup")
    if not request.objective.strip():
        raise HTTPException(status_code=400, detail="Objective is empty")
    await start_session(session, owner.id, request.objective.strip())
    await session.commit()
    return {"objective": request.objective.strip()}


# ---- Terminal supervision (spec §4.3) — watch the terminal the owner is
# already working in and answer the coding agent's permission prompts.

class WatchStartRequest(BaseModel):
    goal: str
    agent: str = "claude"


@app.post("/terminal/supervise")
async def terminal_supervise(request: WatchStartRequest,
                             session: AsyncSession = Depends(get_session)) -> dict:
    """Start watching the front terminal against a goal. Jardo reads it and
    answers the agent's yes/no permission prompts on the owner's behalf."""
    from core.agents import terminal_watch
    from core.memory import MemoryStore
    from core.supervision import start_session

    from core.supervision import get_active

    owner = await MemoryStore(session).get_owner()
    if owner is None:
        raise HTTPException(status_code=409, detail="Not set up. Run: jardo setup")
    if not terminal_watch.supervised_terminal_ok():
        raise HTTPException(
            status_code=409,
            detail=f"Your terminal ({settings.supervise_terminal}) can't be read by "
                   "AppleScript (Warp / VS Code). Supervise Claude via the hook "
                   "instead — run: jardo hook install — it works in any terminal.")
    try:
        terminal_watch.read_front_terminal()  # probe: is a terminal readable here?
    except Exception as exc:  # noqa: BLE001 — no terminal / not scriptable
        raise HTTPException(
            status_code=409,
            detail=f"Can't read your terminal ({exc}). Open {settings.supervise_terminal} "
                   "with your agent running, then ask me again.",
        ) from exc

    # The command that triggers this ("supervise it", "keep clicking yes") is
    # rarely the actual goal — that was set at the briefing. Keep the existing
    # objective; only set a new one if the owner gave something substantive and
    # none is active yet.
    active = await get_active(session, owner.id)
    goal = request.goal.strip()
    substantive = len(goal.split()) >= 5
    if active is None:
        await start_session(session, owner.id, goal if substantive else "",
                            agent=request.agent)
        objective = goal if substantive else ""
    else:
        objective = active.objective
    await session.commit()
    app.state.answered_prompts = set()  # fresh dedupe per session
    # Pin to the terminal that's frontmost right now, so we read/press exactly
    # this window even if the owner brings another one forward (audit #2).
    app.state.supervise_window_id = terminal_watch.front_window_id()
    return {"watching": True, "goal": objective, "agent": request.agent}


@app.post("/terminal/observe")
async def terminal_observe(session: AsyncSession = Depends(get_session)) -> dict:
    """Comprehension beat: read the agent's recent output and judge whether it's
    progressing, stuck, off-task, or done. The desktop calls this on a slow timer
    while supervising, so Jardo notices trouble — not just permission prompts.
    Needs a capable model; returns state 'unknown' otherwise."""
    from core.agents import terminal_watch
    from core.observer import build_messages, parse_observation
    from core.supervision import get_active

    active = await get_active(session)
    if active is None:
        return {"watching": False}
    if not providers.configured():
        return {"state": "unknown", "note": "add a cloud key so I can read what "
                "the agent is doing"}

    window_id = getattr(app.state, "supervise_window_id", None)
    try:
        screen = terminal_watch.read_terminal(window_id)
    except Exception as exc:  # noqa: BLE001
        return {"state": "unknown", "readable": False, "detail": str(exc)}

    # A pending prompt is the tick's job; report waiting so we don't double up.
    if terminal_watch.detect_permission_prompt(screen) is not None:
        return {"state": "waiting", "note": "waiting on a permission decision"}

    # Redact anything credential-shaped BEFORE it leaves the machine (audit HIGH):
    # the terminal may show keys/tokens/.env, and this text goes to the cloud.
    import hashlib

    from core.sentinel.checks import redact
    tail = redact("\n".join(screen.splitlines()[-30:]))

    # Skip the model call when the screen hasn't changed since last beat — no new
    # information, no reason to spend tokens (audit LOW #5).
    digest = hashlib.sha256(tail.encode()).hexdigest()[:16]
    if getattr(app.state, "observe_digest", None) == digest:
        return getattr(app.state, "observe_last", None) or {"state": "idle"}

    chosen = providers.configured()[0]
    model = RouterConfig.load().tiers.get("fireworks_cheap", "fireworks/gpt-oss-20b")
    brief = await _project_brief(session, active)
    try:
        client = providers.make_client(chosen, timeout=30)
        result = await client.chat(providers.resolve_model(chosen, model),
                                   build_messages(active.objective, tail, brief=brief),
                                   max_tokens=400, temperature=0.0, reasoning_effort="low")
        obs = parse_observation(result.content)
        app.state.observe_digest = digest
        app.state.observe_last = obs

        async def _steer_chat(p: str) -> str:
            r = await client.chat(providers.resolve_model(chosen, model),
                                  [{"role": "user", "content": p}],
                                  max_tokens=200, temperature=0.3, reasoning_effort="low")
            return r.content

        # Conductor, not just reviewer: when the agent is stuck or drifting, type a
        # concrete, project-aware instruction to steer it back toward the goal —
        # rather than waiting for a permission prompt. Cooled down so we nudge, then
        # give it room to act before nudging again.
        if obs.get("state") in ("stuck", "off_task"):
            import time
            now = time.time()
            if now - getattr(app.state, "last_steer_ts", 0) > 45:
                from core.memory import MemoryStore
                from core.supervision import steering_nudge
                nudge = await steering_nudge(active.objective, brief, obs,
                                             chat_fn=_steer_chat)
                try:
                    terminal_watch.type_text(nudge, window_id)
                    app.state.last_steer_ts = now
                    obs["steered"] = True
                    obs["steer_text"] = nudge
                    await MemoryStore(session).audit(
                        "jardo", "terminal.steered",
                        {"state": obs.get("state"), "nudge": nudge[:300]})
                    await session.commit()
                except Exception:  # noqa: BLE001 — couldn't type; owner can step in
                    pass

        # Token-budget awareness (Lane C): when the agent is running low on context,
        # tell it to /compact before it hits the wall — once per low spell, so it
        # doesn't nag.
        if obs.get("context") == "low" and not getattr(app.state, "nudged_low", False):
            from core.supervision import compaction_nudge
            try:
                terminal_watch.type_text(compaction_nudge(active.objective), window_id)
                app.state.nudged_low = True
                obs["nudged"] = True
            except Exception:  # noqa: BLE001 — couldn't type; owner can compact
                pass
        elif obs.get("context") != "low":
            app.state.nudged_low = False  # reset once context recovers
        return obs
    except Exception:  # noqa: BLE001 — transient → say nothing this beat
        return {"state": "unknown"}


# Coding-agent TUIs (Claude Code, Gemini) render recognisable chrome while alive:
# an input box, a "for shortcuts" hint, "esc to interrupt", etc. When the agent
# exits (Ctrl-C or /exit) the window drops back to a bare shell prompt with none
# of that. We use the absence of any agent marker PLUS a shell-prompt-looking last
# line to spot an exit (debounced by the caller to avoid false positives).
_AGENT_MARKERS = (
    "esc to interrupt", "for shortcuts", "? for shortcuts", "auto-accept",
    "bypass permissions", "│ >", "╭─", "claude", "gemini",
    "tokens", "context left", "do you want", "proceed?",
)
_SHELL_PROMPT = re.compile(r"[\$%#❯➜]\s*$")


async def _project_brief(session, active) -> str:
    """The supervised project's brief (goal + CLAUDE.md + progress), cached with a
    short TTL so the supervisor reasons with full context without rebuilding git
    state on every beat."""
    import time

    from core.projects import ProjectStore
    from core.supervision import build_project_brief

    cache = getattr(app.state, "brief_cache", None)
    now = time.time()
    if cache and now - cache[1] < 25:
        return cache[0]
    path = None
    try:
        proj = await ProjectStore(session).get_active(active.owner_id)
        path = proj.path if proj else None
    except Exception:  # noqa: BLE001
        path = None
    brief = build_project_brief(path, active.objective)
    app.state.brief_cache = (brief, now)
    return brief


def _agent_exited(screen: str, agent: str) -> bool:
    lines = [ln.rstrip() for ln in screen.splitlines() if ln.strip()]
    if not lines:
        return False
    low = "\n".join(lines[-12:]).lower()
    if any(m in low for m in _AGENT_MARKERS):
        return False  # agent UI still on screen → still running
    return bool(_SHELL_PROMPT.search(lines[-1]))


@app.post("/terminal/tick")
async def terminal_tick(session: AsyncSession = Depends(get_session)) -> dict:
    """One supervision beat: read the terminal, and if the agent is waiting on a
    permission prompt, decide and press the answer. The desktop calls this on a
    short timer while supervising; keeping the loop client-driven means it stops
    the instant the owner stops watching."""
    import hashlib

    from core.agents import terminal_watch
    from core.autonomy.decider import Decision, autonomous_decision
    from core.memory import MemoryStore
    from core.supervision import get_active

    active = await get_active(session)
    if active is None:
        return {"watching": False}

    from core.supervision import end_active

    window_id = getattr(app.state, "supervise_window_id", None)

    async def _finish(reason: str) -> dict:
        app.state.exit_streak = 0
        await end_active(session, active.owner_id)
        await session.commit()
        return {"watching": False, "ended": True, "ended_reason": reason}

    # The owner closed the supervised window → supervision is over, cleanly.
    if not terminal_watch.window_exists(window_id):
        return await _finish("the terminal window was closed")

    try:
        screen = terminal_watch.read_terminal(window_id)
    except Exception as exc:  # noqa: BLE001
        return {"watching": True, "readable": False, "detail": str(exc)}

    # The owner stopped the agent (Ctrl-C or /exit) and it dropped back to a bare
    # shell prompt. Debounced over two beats so a momentary prompt between steps
    # doesn't look like an exit.
    if _agent_exited(screen, active.agent):
        app.state.exit_streak = getattr(app.state, "exit_streak", 0) + 1
        if app.state.exit_streak >= 2:
            return await _finish(f"{active.agent} is no longer running")
    else:
        app.state.exit_streak = 0

    tail = "\n".join(screen.splitlines()[-6:]).strip()
    prompt = terminal_watch.detect_permission_prompt(screen)
    if prompt is None:
        return {"watching": True, "readable": True, "prompt": False, "tail": tail}

    answered = getattr(app.state, "answered_prompts", None)
    if answered is None:
        answered = app.state.answered_prompts = set()
    fingerprint = hashlib.sha256(
        (prompt.question + "|" + prompt.action).encode()).hexdigest()[:16]
    if fingerprint in answered:
        return {"watching": True, "readable": True, "prompt": True,
                "action": prompt.action, "already": True, "tail": tail}

    # The instinct: safe + on-task → Yes; otherwise No. Alignment judging prefers a
    # capable cloud model (accurate) over the tiny local model, which is too weak
    # to judge on-task reliably.
    async def _align(p: str) -> str:
        msgs = [{"role": "user", "content": p}]
        if providers.configured():
            chosen = providers.configured()[0]
            model = RouterConfig.load().tiers.get("fireworks_cheap", "fireworks/gpt-oss-20b")
            client = providers.make_client(chosen, timeout=30)
            r = await client.chat(providers.resolve_model(chosen, model), msgs,
                                  max_tokens=400, temperature=0.0, reasoning_effort="low")
            return r.content
        r = await app.state.ollama.chat(
            RouterConfig.load().tiers.get("ollama_local", "qwen2.5:0.5b"), msgs)
        return r.content

    # The folder-trust prompt Claude shows on first launch in a new directory:
    # trusting the owner's own project (or one Jardo just created) is their
    # intent, so approve it — it isn't a shell command to vet.
    if prompt.kind == "trust":
        decision = Decision(True, "trusting your project folder", "low")
    # Fail safe (audit #4): if we couldn't confidently isolate the command being
    # asked about, decline rather than approve on a misread.
    elif not prompt.action.strip():
        decision = Decision(False, "couldn't read the command clearly — declined "
                            "to be safe", "low")
    else:
        chat_fn = _align if (providers.configured()
                             or await app.state.ollama.is_up()) else None
        brief = await _project_brief(session, active)
        decision = await autonomous_decision(session, prompt.action, active.objective,
                                             chat_fn=chat_fn, conservative=True,
                                             brief=brief)
    pressed = False
    needs_accessibility = False
    try:
        terminal_watch.press_answer(prompt, decision.approve, window_id)
        pressed = True
    except terminal_watch.AccessibilityDenied:
        needs_accessibility = True
    except Exception:  # noqa: BLE001 — couldn't inject this time; try again next tick
        pass

    # Only remember it as handled once we actually pressed — otherwise we retry
    # on the next tick (e.g. after the owner grants Accessibility).
    if pressed:
        answered.add(fingerprint)

    # A decline that just presses "No" leaves the agent stalled waiting for "what
    # should I do differently?". So after declining a real command, Jardo TYPES an
    # instruction telling the agent to adapt and keep working — the difference
    # between supervising and blocking (owner's insight).
    guided = False
    if pressed and not decision.approve and prompt.kind == "command":
        import asyncio

        from core.supervision import decline_guidance
        # Prefer the model's concrete, project-aware "do this instead" guidance;
        # fall back to the generic redirect only when it didn't give one.
        guidance = (decision.guidance.strip() if decision.guidance.strip()
                    else decline_guidance(prompt.action, decision.reason,
                                          active.objective))
        await asyncio.sleep(0.7)  # let the agent render its follow-up input
        try:
            terminal_watch.type_text(guidance, window_id)
            guided = True
        except Exception:  # noqa: BLE001 — couldn't type; the owner can step in
            pass

    await MemoryStore(session).audit(
        "jardo", "terminal.answered",
        {"action": prompt.action[:300], "approved": decision.approve,
         "reason": decision.reason, "pressed": pressed, "guided": guided})
    await session.commit()
    return {"watching": True, "readable": True, "prompt": True,
            "answered": pressed, "approved": decision.approve, "pressed": pressed,
            "guided": guided, "needs_accessibility": needs_accessibility,
            "action": prompt.action, "reason": decision.reason,
            "answer": prompt.approve_key if decision.approve else prompt.deny_key,
            "tail": tail}


@app.get("/supervision/report")
async def supervision_report(session: AsyncSession = Depends(get_session)) -> dict:
    """The away-mode payoff: what Jardo did while supervising (spec §4.4)."""
    from core.supervision import session_report
    return await session_report(session)


@app.delete("/supervision")
async def supervision_end(session: AsyncSession = Depends(get_session)) -> dict:
    from core.memory import MemoryStore
    from core.supervision import end_active

    owner = await MemoryStore(session).get_owner()
    if owner is not None:
        await end_active(session, owner.id)
        await session.commit()
    return {"ended": True}


# ---- Coding-environment surface (owner scope) — for the desktop Agents tab.

@app.get("/coding/tools")
async def coding_tools() -> dict:
    """Detected coding environments Jardo can operate (editors/terminals/…)."""
    from core.coding_env.detect import detect
    return detect().as_dict()


@app.get("/coding/decisions")
async def coding_decisions(session: AsyncSession = Depends(get_session),
                           limit: int = 25) -> list[dict]:
    """Recent agent-prompt decisions and action reviews (from the audit log)."""
    from sqlalchemy import select
    from core.schema import AuditLog

    rows = (await session.execute(
        select(AuditLog).where(
            AuditLog.event_type.in_(("prompt.answered", "action.review"))
        ).order_by(AuditLog.ts.desc()).limit(limit)
    )).scalars().all()
    return [
        {"ts": r.ts.isoformat(), "actor": r.actor, "event": r.event_type,
         "detail": r.detail}
        for r in rows
    ]


class SuperviseRequest(BaseModel):
    actor: str = "claude-code"
    tool_name: str
    tool_input: dict = {}
    stated_goal: str = ""


@app.post("/supervise")
async def supervise(request: SuperviseRequest,
                    session: AsyncSession = Depends(get_session)) -> dict:
    """Answer an external agent's permission question (spec §4.3). Called by the
    Claude Code PreToolUse hook (mcp/claude-code/)."""
    from core.supervisor import supervise_tool_call

    # Alignment judging uses the local model when available (supervision is a
    # critical decision; upgrades to the quality tier once a Fireworks key exists).
    # These judgments repeat, so they go through the cache (semantic ok: single-shot).
    from core.cache import cached_call

    async def _align(prompt: str) -> str:
        local_model = RouterConfig.load().tiers.get("ollama_local", "qwen2.5:0.5b")
        msgs = [{"role": "user", "content": prompt}]

        async def _miss() -> tuple[str, int]:
            r = await app.state.ollama.chat(local_model, msgs)
            return r.content, (r.prompt_tokens or 0) + (r.completion_tokens or 0)

        res = await cached_call(session, local_model, msgs, _miss, allow_semantic=True)
        return res.content

    chat_fn = _align if await app.state.ollama.is_up() else None
    decision = await supervise_tool_call(
        session, request.actor, request.tool_name, request.tool_input,
        request.stated_goal, align_chat_fn=chat_fn,
    )
    await session.commit()
    return {
        "hookSpecificOutput": {"hookEventName": "PreToolUse", **decision}
    }


class RouteRequest(BaseModel):
    message: str


@app.post("/assistant/route")
async def assistant_route(body: RouteRequest,
                          session: AsyncSession = Depends(get_session)) -> dict:
    """The tool-use layer: let the model decide what the owner wants (understanding,
    not keyword regex). Only trusted when a capable cloud model is configured —
    otherwise we return fallback:true so the desktop uses its offline heuristics,
    which are more reliable than the tiny local model for this.

    Routing is stateless (utterance -> intent), so it goes through the response
    cache: repeated commands ("where am I", "supervise claude", "stop") cost zero
    tokens on a hit — always cheaper than an uncached call (spec §5)."""
    from core.assistant import build_messages, parse_intent
    from core.cache import cached_call

    msg = body.message.strip()[:_MAX_ROUTE_CHARS]  # routing needs little (audit MED)
    if not msg:
        return {"intent": "chat"}
    if not providers.configured():
        return {"intent": "chat", "fallback": True}  # no capable model → use regex

    chosen = providers.configured()[0]
    model = RouterConfig.load().tiers.get("fireworks_cheap", "fireworks/gpt-oss-20b")
    resolved = providers.resolve_model(chosen, model)
    messages = build_messages(msg)

    async def _miss() -> tuple[str, int]:
        client = providers.make_client(chosen, timeout=30)
        r = await client.chat(resolved, messages, max_tokens=400, temperature=0.0,
                              reasoning_effort="low")
        return r.content, (r.prompt_tokens or 0) + (r.completion_tokens or 0)

    try:
        # Exact cache only — semantic could conflate near-but-different intents
        # ("supervise claude" vs "stop supervising").
        cached = await cached_call(session, resolved, messages, _miss,
                                   allow_semantic=False)
        await session.commit()
        return parse_intent(cached.content)
    except Exception:  # noqa: BLE001 — router failed → let the desktop fall back
        return {"intent": "chat", "fallback": True}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, session: AsyncSession = Depends(get_session)) -> ChatResponse:
    message = request.message.strip()[:_MAX_CHAT_CHARS]  # bound cost + context (audit MED)
    if not message:
        raise HTTPException(status_code=400, detail="Empty message.")
    store = MemoryStore(session)
    owner = await store.get_owner()
    if owner is None:
        raise HTTPException(status_code=409, detail="Not set up. Run: jardo setup")

    if request.conversation_id is not None:
        conversation = await store.get_conversation(request.conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Unknown conversation")
    else:
        conversation = await store.create_conversation(owner.id, title=message[:200])

    await store.add_message(conversation.id, "user", message)

    facts = await store.list_facts(owner.id)
    history = await store.recent_messages(conversation.id, settings.history_window)
    messages = [{"role": "system", "content": build_system_prompt(owner, facts)}]
    messages += [{"role": m.role, "content": m.content} for m in history]

    # Cost-Accuracy Router (§5): classify → decide → dispatch.
    task = await app.state.classifier.classify(message)
    ollama_up = await app.state.ollama.is_up()
    input_tokens = sum(len(m["content"]) for m in messages) // 4  # rough chars/4
    try:
        decision: RouteDecision = app.state.router.decide(
            task, input_tokens, ollama_up, await spent_today_usd(session)
        )
    except BudgetExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    decision = _premium_frontdoor(decision, cloud_ready=bool(providers.configured()),
                                  input_tokens=input_tokens)

    # Cost optimization (§5): serve from the response cache when we've answered
    # this exact request before — zero tokens, and free on the paid tiers.
    from core.cache import cached_call

    dispatched: dict = {}

    async def _miss() -> tuple[str, int]:
        r = await _dispatch(decision, messages)
        dispatched["model"] = r.model
        dispatched["prompt_tokens"] = r.prompt_tokens
        dispatched["completion_tokens"] = r.completion_tokens
        return r.content, (r.prompt_tokens or 0) + (r.completion_tokens or 0)

    try:
        cached = await cached_call(session, decision.model, messages, _miss)
    except FireworksError as exc:
        # Free trial used up: answer plainly instead of throwing a scary error.
        if getattr(exc, "trial_exhausted", False):
            reply = ("You've used up the free trial. To keep going, add your own "
                     "Fireworks API key in Settings, or point me at a local Ollama "
                     "model for free.")
            await store.add_message(conversation.id, "assistant", reply)
            await session.commit()
            return ChatResponse(reply=reply, conversation_id=conversation.id,
                                model="trial-exhausted", prompt_tokens=0,
                                completion_tokens=0)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except OllamaUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if cached.cached:
        reply_model = f"{decision.model} (cached)"
        prompt_tokens = completion_tokens = 0
    else:
        reply_model = dispatched.get("model", decision.model)
        prompt_tokens = dispatched.get("prompt_tokens")
        completion_tokens = dispatched.get("completion_tokens")

    # A reasoning model that got cut off can return empty content — never show the
    # owner a blank reply (audit LOW).
    reply_text = cached.content.strip() or "Sorry, I didn't catch that — could you rephrase?"

    class _R:
        content = reply_text
    result = _R()

    await log_decision(
        session, decision, task_id=str(conversation.id),
        actual_cost_usd=(0.0 if cached.cached
                         else (None if decision.backend != "fireworks"
                               else decision.est_cost_usd)),
    )

    await store.add_message(
        conversation.id,
        "assistant",
        result.content,
        model=reply_model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    await store.audit(
        "core",
        "chat.completion",
        {
            "conversation_id": str(conversation.id),
            "model": reply_model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cached": cached.cached,
            "tokens_saved": cached.tokens_saved,
        },
    )
    await session.commit()

    # Async fact extraction — proves the task queue end-to-end (Phase 1 demo).
    await app.state.arq.enqueue_job("extract_facts", str(conversation.id))

    return ChatResponse(
        reply=result.content,
        conversation_id=conversation.id,
        model=reply_model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
