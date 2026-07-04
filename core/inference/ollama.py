"""Ollama local-inference client (owner's laptop tier — spec §5.2 route 1).

API source (spec §0.1): docs/vendor/local-inference/ollama-api.md
  POST /api/chat  {"model", "messages": [{role, content}], "stream": false}
  → {"message": {"role", "content"}, "prompt_eval_count": int, "eval_count": int, ...}
  GET /api/tags lists installed models.
Local inference is costed at $0 in routing math (electricity ignored at MVP).
"""

from dataclasses import dataclass

import httpx


class OllamaUnavailable(RuntimeError):
    pass


@dataclass
class OllamaResult:
    content: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None


class OllamaClient:
    def __init__(self, base_url: str = "http://127.0.0.1:11434", timeout: float = 300.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def is_up(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{self._base_url}/api/tags")
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def installed_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{self._base_url}/api/tags")
        response.raise_for_status()
        return [m["name"] for m in response.json().get("models", [])]

    async def chat(self, model: str, messages: list[dict]) -> OllamaResult:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/api/chat",
                    json={"model": model, "messages": messages, "stream": False},
                )
        except httpx.HTTPError as exc:
            raise OllamaUnavailable(f"ollama unreachable: {exc}") from exc
        if response.status_code != 200:
            raise OllamaUnavailable(f"ollama error {response.status_code}: {response.text[:300]}")
        data = response.json()
        return OllamaResult(
            content=data.get("message", {}).get("content", ""),
            model=data.get("model", model),
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
        )
