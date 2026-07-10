"""Minimal OpenAI-compatible chat server on AMD GPU via PyTorch/ROCm + transformers.

Serves google/gemma-2-9b-it (or $MODEL) at /v1/chat/completions and /v1/models,
so Jardo's proxy (AMD_BASE_URL) can route inference to the AMD Instinct GPU. No
vLLM/CUDA needed — uses the ROCm PyTorch already on the droplet.

  API_KEY=... MODEL=google/gemma-2-9b-it SERVED_NAME=gemma \
    python -m uvicorn amd_openai_server:app --host 0.0.0.0 --port 8000
"""
import os, time, uuid
import torch
from fastapi import FastAPI, Request, HTTPException
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL = os.environ.get("MODEL", "google/gemma-2-9b-it")
SERVED = os.environ.get("SERVED_NAME", "gemma")
API_KEY = os.environ.get("API_KEY", "")

print(f"[jardo-amd] torch={torch.__version__} cuda_available={torch.cuda.is_available()} "
      f"hip={getattr(torch.version, 'hip', None)}")
print(f"[jardo-amd] loading {MODEL} onto the GPU ...")
tok = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.bfloat16, device_map="auto")
print("[jardo-amd] model ready.")

app = FastAPI()

def _auth(request: Request):
    if API_KEY and request.headers.get("authorization", "") != f"Bearer {API_KEY}":
        raise HTTPException(401, "unauthorized")

@app.get("/v1/models")
async def models(request: Request):
    _auth(request)
    return {"object": "list", "data": [{"id": SERVED, "object": "model"}]}

def _normalize_messages(raw):
    """Flatten content, and fold any system message into the first user turn.
    Gemma's chat template rejects a 'system' role outright — and Jardo's
    supervisor/observer calls DO send system prompts — so without this every
    supervision request 500s. This keeps the instruction while satisfying Gemma."""
    msgs, system = [], ""
    for m in raw:
        c = m.get("content", "")
        if isinstance(c, list):  # multimodal → keep the text parts
            c = " ".join(p.get("text", "") for p in c
                         if isinstance(p, dict) and p.get("type") == "text")
        role = m.get("role", "user")
        if role == "system":
            system += (c + "\n\n")
            continue
        msgs.append({"role": role, "content": c})
    if system:
        for m in msgs:
            if m["role"] == "user":
                m["content"] = system + m["content"]
                break
        else:
            msgs.insert(0, {"role": "user", "content": system.strip()})
    return msgs or [{"role": "user", "content": ""}]


@app.post("/v1/chat/completions")
async def chat(request: Request):
    _auth(request)
    try:
        body = await request.json()
        max_new = int(body.get("max_tokens", 512) or 512)
        temp = float(body.get("temperature", 0.7) or 0.0)
        msgs = _normalize_messages(body.get("messages", []))
        # device_map="auto" means model.device can be unreliable — use a real
        # parameter's device. return_dict gives us the attention mask too.
        dev = next(model.parameters()).device
        enc = tok.apply_chat_template(msgs, add_generation_prompt=True,
                                      return_tensors="pt", return_dict=True)
        enc = {k: v.to(dev) for k, v in enc.items()}
        prompt_tokens = int(enc["input_ids"].shape[-1])
        with torch.no_grad():
            out = model.generate(**enc, max_new_tokens=max_new,
                                 do_sample=temp > 0,
                                 temperature=max(temp, 0.01) if temp > 0 else None,
                                 pad_token_id=tok.eos_token_id)
        gen = out[0][prompt_tokens:]
        text = tok.decode(gen, skip_special_tokens=True).strip()
        return {
            "id": "chatcmpl-" + uuid.uuid4().hex[:24], "object": "chat.completion",
            "created": int(time.time()), "model": SERVED,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": prompt_tokens,
                      "completion_tokens": int(gen.shape[-1]),
                      "total_tokens": prompt_tokens + int(gen.shape[-1])},
        }
    except Exception as exc:  # surface the real reason instead of a bare 500
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"generation failed: {type(exc).__name__}: {exc}")
