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
    app.state.classifier = ModelClassifier(
        app.state.ollama, config.tiers.get("ollama_local", "llama3.2:3b"),
        HeuristicClassifier(),
    )
    yield
    await app.state.arq.aclose()
    await engine.dispose()


app = FastAPI(title="JARVIS core", lifespan=lifespan)


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


@app.get("/memory")
async def list_memory(session: AsyncSession = Depends(get_session)) -> list[dict]:
    store = MemoryStore(session)
    owner = await store.get_owner()
    if owner is None:
        raise HTTPException(status_code=409, detail="Not set up. Run: jarvis setup")
    facts = await store.list_facts(owner.id)
    return [
        {"id": str(f.id), "kind": f.kind, "content": f.content, "source": f.source}
        for f in facts
    ]


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, session: AsyncSession = Depends(get_session)) -> ChatResponse:
    store = MemoryStore(session)
    owner = await store.get_owner()
    if owner is None:
        raise HTTPException(status_code=409, detail="Not set up. Run: jarvis setup")

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
