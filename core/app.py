"""FastAPI application (Phase 1).

Loopback-only in Phase 1 (core.config). The chat path is:
persist user msg → persona prompt (identity + facts) → Fireworks → persist reply
→ enqueue fact-extraction job on the Arq queue → respond.
"""

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
from core.db import engine, get_session
from core.inference.fireworks import FireworksClient, FireworksError
from core.inference.ollama import OllamaClient, OllamaUnavailable
from core.memory import MemoryStore
from core.persona import build_system_prompt
from core.router.classifier import HeuristicClassifier, ModelClassifier
from core.router.router import BudgetExceeded, CostRouter, RouteDecision, RouterConfig
from core.router.spend import log_decision, spent_today_usd


@asynccontextmanager
async def lifespan(app: FastAPI):
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


async def _dispatch(decision: RouteDecision, messages: list[dict]):
    """Route a chat to the decided backend. vLLM speaks the OpenAI-compatible
    protocol (docs/vendor/local-inference/vllm-openai-compatible-server.md), so
    it reuses FireworksClient pointed at the droplet endpoint."""
    if decision.backend == "ollama":
        return await app.state.ollama.chat(decision.model, messages)
    if decision.backend == "vllm":
        client = FireworksClient("vllm-local", app.state.router._config.vllm_endpoint,
                                 timeout=settings.request_timeout_seconds)
        return await client.chat(decision.model, messages)
    api_key = secrets.read_secret(secrets.FIREWORKS_API_KEY)
    if not api_key:
        raise HTTPException(
            status_code=409,
            detail="Route chose Fireworks but no API key is in the Keychain "
                   "(QUESTIONS.md Q1). Local tip: install Ollama for key-free chat.",
        )
    client = FireworksClient(api_key, settings.fireworks_base_url,
                             timeout=settings.request_timeout_seconds)
    # Fireworks model ids in PRICING_TABLE.md are short ("fireworks/x");
    # the API wants "accounts/fireworks/models/x"
    # (docs/vendor/fireworks/querying-text-models.md).
    model = decision.model
    if model.startswith("fireworks/"):
        model = "accounts/fireworks/models/" + model.removeprefix("fireworks/")
    return await client.chat(model, messages)


class ChatRequest(BaseModel):
    message: str
    conversation_id: uuid.UUID | None = None


class ChatResponse(BaseModel):
    reply: str
    conversation_id: uuid.UUID
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None


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
    seconds: float = 5.0


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
    voice_label = (
        "Piper (neural)" if settings.voice_tts_backend == "piper"
        else settings.voice_tts_voice
    )
    return {
        "available": True,
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
    from core.voice import mic
    from core.voice.stt import SpeechToText

    if not hasattr(app.state, "stt"):
        app.state.stt = SpeechToText(settings.voice_stt_model)

    audio = await run_in_threadpool(mic.record_seconds, request.seconds)
    amplitude = float(np.abs(audio.astype(np.float32) / 32768.0).max())
    transcript = await run_in_threadpool(app.state.stt.transcribe, audio)
    return {"transcript": transcript, "amplitude": round(amplitude, 4)}


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
    from core.voice.tts import get_tts

    tts = get_tts(settings.voice_tts_backend, voice=settings.voice_tts_voice,
                  model_path=settings.voice_piper_model)
    await run_in_threadpool(tts.speak, request.text)
    return {"spoken": True}


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
    async def _align(prompt: str) -> str:
        local_model = RouterConfig.load().tiers.get("ollama_local", "qwen2.5:0.5b")
        result = await app.state.ollama.chat(
            local_model, [{"role": "user", "content": prompt}])
        return result.content

    chat_fn = _align if await app.state.ollama.is_up() else None
    decision = await supervise_tool_call(
        session, request.actor, request.tool_name, request.tool_input,
        request.stated_goal, align_chat_fn=chat_fn,
    )
    await session.commit()
    return {
        "hookSpecificOutput": {"hookEventName": "PreToolUse", **decision}
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, session: AsyncSession = Depends(get_session)) -> ChatResponse:
    store = MemoryStore(session)
    owner = await store.get_owner()
    if owner is None:
        raise HTTPException(status_code=409, detail="Not set up. Run: jardo setup")

    if request.conversation_id is not None:
        conversation = await store.get_conversation(request.conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Unknown conversation")
    else:
        conversation = await store.create_conversation(owner.id, title=request.message[:200])

    await store.add_message(conversation.id, "user", request.message)

    facts = await store.list_facts(owner.id)
    history = await store.recent_messages(conversation.id, settings.history_window)
    messages = [{"role": "system", "content": build_system_prompt(owner, facts)}]
    messages += [{"role": m.role, "content": m.content} for m in history]

    # Cost-Accuracy Router (§5): classify → decide → dispatch.
    task = await app.state.classifier.classify(request.message)
    ollama_up = await app.state.ollama.is_up()
    input_tokens = sum(len(m["content"]) for m in messages) // 4  # rough chars/4
    try:
        decision: RouteDecision = app.state.router.decide(
            task, input_tokens, ollama_up, await spent_today_usd(session)
        )
    except BudgetExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    try:
        result = await _dispatch(decision, messages)
    except (FireworksError, OllamaUnavailable) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await log_decision(
        session, decision, task_id=str(conversation.id),
        actual_cost_usd=None if decision.backend != "fireworks" else decision.est_cost_usd,
    )

    await store.add_message(
        conversation.id,
        "assistant",
        result.content,
        model=result.model,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
    )
    await store.audit(
        "core",
        "chat.completion",
        {
            "conversation_id": str(conversation.id),
            "model": result.model,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
        },
    )
    await session.commit()

    # Async fact extraction — proves the task queue end-to-end (Phase 1 demo).
    await app.state.arq.enqueue_job("extract_facts", str(conversation.id))

    return ChatResponse(
        reply=result.content,
        conversation_id=conversation.id,
        model=result.model,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
    )
