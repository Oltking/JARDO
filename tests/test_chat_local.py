"""End-to-end chat through the real local model (no API keys involved).

Uses the ASGI app with the DB dependency overridden to the test database and a
seeded owner. Requires Ollama running with the configured local model — skipped
otherwise, so the suite stays green on machines without it."""

import httpx
import pytest

from core.app import _API_TOKEN, app
from core.db import get_session
from core.inference.ollama import OllamaClient
from core.router.router import RouterConfig
from core.schema import Owner


@pytest.fixture
async def local_model_ready():
    client = OllamaClient()
    if not await client.is_up():
        pytest.skip("ollama not running")
    model = RouterConfig.load().tiers.get("ollama_local", "")
    installed = await client.installed_models()
    if not any(m.startswith(model.split(":")[0]) for m in installed):
        pytest.skip(f"local model {model} not installed")


async def test_chat_end_to_end_via_local_model(session, local_model_ready):
    owner = Owner(name="Integration Test", pronoun_style="sir",
                  email="itest@example.test",
                  device_public_key="-----BEGIN PUBLIC KEY-----\nx\n-----END PUBLIC KEY-----")
    session.add(owner)
    await session.commit()

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://test") as client:
            async with app.router.lifespan_context(app):
                response = await client.post(
                    "/chat", json={"message": "Reply with exactly the word pong."},
                    headers={"Authorization": f"Bearer {_API_TOKEN}"})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["reply"].strip()
        # trivial task must have routed local: $0, no API key ever touched
        assert "qwen" in data["model"] or ":" in data["model"]
    finally:
        app.dependency_overrides.clear()
