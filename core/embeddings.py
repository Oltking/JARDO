"""Local text embeddings via Ollama (for the semantic cache).

Uses the nomic-embed-text model when present. Fully graceful: if the model
isn't installed or Ollama is down, embed() returns None and the semantic cache
is simply skipped (the exact cache still works). No paid API, no data leaves
the machine.
"""

import httpx

EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768
_OLLAMA = "http://127.0.0.1:11434"


async def embed(text: str) -> list[float] | None:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{_OLLAMA}/api/embeddings",
                                     json={"model": EMBED_MODEL, "prompt": text})
        if resp.status_code != 200:
            return None
        vec = resp.json().get("embedding")
        return vec if vec and len(vec) == EMBED_DIM else None
    except (httpx.HTTPError, ValueError):
        return None


def to_pgvector(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
