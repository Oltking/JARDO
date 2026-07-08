"""Fireworks AI chat-completions client (OpenAI-compatible).

Endpoint/schema source (spec §0.1 — do not code vendor APIs from memory):
  docs/vendor/fireworks/api-chat-completions.md
    POST {base}/chat/completions  (server: https://api.fireworks.ai/inference, path /v1/...)
    security: BearerAuth
    request:  {"model": "accounts/<org>/models/<name>", "messages": [{role, content}], ...}
    response: {"choices": [{"message": {"content": ...}, "finish_reason": ...}],
               "usage": {"prompt_tokens", "completion_tokens", "total_tokens"}}
  docs/vendor/fireworks/reliability-error-handling.md (retry guidance)
"""

from dataclasses import dataclass

import httpx


class FireworksError(RuntimeError):
    pass


@dataclass
class ChatResult:
    content: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None


class FireworksClient:
    def __init__(self, api_key: str, base_url: str, timeout: float = 120.0,
                 extra_headers: dict | None = None):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        # Hosted-proxy mode adds a device header for trial metering (providers.py).
        self._extra_headers = extra_headers or {}

    async def chat(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0.6,
        reasoning_effort: str | None = None,
    ) -> ChatResult:
        payload: dict = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        # For reasoning models (gpt-oss), "low" effort skips most of the token-
        # burning internal reasoning — big savings on simple classification tasks
        # (intent, alignment, observation) that don't need it (spec §5).
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}", **self._extra_headers},
                json=payload,
            )
        if response.status_code != 200:
            # 401/403: bad key; 429: rate limit (docs/vendor/fireworks/rate-limits.md);
            # 5xx: transient. The Phase 2 router adds retries with backoff (§4.2).
            raise FireworksError(
                f"Fireworks API error {response.status_code}: {response.text[:500]}"
            )
        data = response.json()
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError) as exc:
            raise FireworksError(f"unexpected response shape: {data}") from exc
        # Reasoning models (e.g. gpt-oss) put thinking in `reasoning_content` and
        # the answer in `content`; if the reply was cut off (finish_reason=length)
        # `content` can be missing. Never crash on that — fall back to the
        # reasoning text, then empty, and let the caller handle it.
        content = message.get("content") or message.get("reasoning_content") or ""
        usage = data.get("usage") or {}
        return ChatResult(
            content=content,
            model=data.get("model", model),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )
