"""Client tests against the response shape documented in
docs/vendor/fireworks/api-chat-completions.md (mocked with respx)."""

import httpx
import pytest
import respx

from core.inference.fireworks import FireworksClient, FireworksError

BASE = "https://api.fireworks.ai/inference/v1"


@respx.mock
async def test_chat_parses_documented_response_shape():
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "cmpl-x",
                "created": 1,
                "model": "accounts/fireworks/models/gpt-oss-20b",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "Hello, sir."},
                     "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
            },
        )
    )
    client = FireworksClient("test-key", BASE)
    result = await client.chat("accounts/fireworks/models/gpt-oss-20b",
                               [{"role": "user", "content": "hi"}])
    assert result.content == "Hello, sir."
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 4


@respx.mock
async def test_chat_sends_bearer_auth_and_model():
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"id": "x", "created": 1, "model": "m",
                  "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"},
                               "finish_reason": "stop"}]},
        )
    )
    client = FireworksClient("secret-key", BASE)
    await client.chat("some-model", [{"role": "user", "content": "hi"}])
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer secret-key"
    assert b'"model": "some-model"' in request.content or b'"model":"some-model"' in request.content


@respx.mock
async def test_chat_raises_on_error_status():
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(401, json={"error": "invalid key"})
    )
    client = FireworksClient("bad-key", BASE)
    with pytest.raises(FireworksError, match="401"):
        await client.chat("m", [{"role": "user", "content": "hi"}])
