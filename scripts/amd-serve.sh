#!/usr/bin/env bash
# Serve Gemma on your AMD Instinct droplet (ROCm + vLLM), OpenAI-compatible, and
# expose it with a public URL to paste into Vercel (AMD_BASE_URL). Run this in the
# droplet's JupyterLab **Terminal** (Launcher → Other → Terminal).
#
#   bash amd-serve.sh
#
# Then copy the printed https URL into Vercel env AMD_BASE_URL (+ AMD_API_KEY,
# AMD_MODEL=gemma) and redeploy. Jardo then serves inference from the AMD GPU.
set -euo pipefail

# ---- config (edit these) --------------------------------------------------
MODEL="${MODEL:-google/gemma-2-9b-it}"   # HF id; gemma-2-9b fits one MI300X easily
SERVED_NAME="${SERVED_NAME:-gemma}"      # the name Jardo/clients call it by
API_KEY="${API_KEY:-jardo-amd-$(openssl rand -hex 6)}"  # protects the endpoint
PORT="${PORT:-8000}"
export HF_TOKEN="${HF_TOKEN:-}"          # needed: Gemma is gated on Hugging Face

if [ -z "$HF_TOKEN" ]; then
  echo "!! Set HF_TOKEN first (accept Gemma's license at huggingface.co/${MODEL}):"
  echo "   export HF_TOKEN=hf_xxx ; bash amd-serve.sh"
  exit 1
fi

echo "==> GPUs / ROCm:"; rocm-smi --showproductname 2>/dev/null | sed -n '1,6p' || echo "(rocm-smi not found; ensure this is the AMD ROCm instance)"

# ---- vLLM (ROCm build) ----------------------------------------------------
if ! python -c "import vllm" 2>/dev/null; then
  echo "==> Installing vLLM (ROCm). If this fails, use the container instead:"
  echo "    docker run -it --network=host --device=/dev/kfd --device=/dev/dri \\"
  echo "      -e HF_TOKEN=\$HF_TOKEN rocm/vllm:latest \\"
  echo "      vllm serve $MODEL --served-model-name $SERVED_NAME --api-key $API_KEY --port $PORT"
  pip install -q vllm || { echo "pip vllm failed — use the rocm/vllm docker line above"; exit 1; }
fi

# ---- public URL via cloudflared quick tunnel (no account needed) ----------
if ! command -v cloudflared >/dev/null 2>&1; then
  echo "==> Fetching cloudflared…"
  curl -fsSL -o /tmp/cloudflared \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
  chmod +x /tmp/cloudflared; export PATH="/tmp:$PATH"
fi

echo "==> Starting vLLM ($MODEL as '$SERVED_NAME') on :$PORT …"
python -m vllm.entrypoints.openai.api_server \
  --model "$MODEL" --served-model-name "$SERVED_NAME" \
  --api-key "$API_KEY" --port "$PORT" --gpu-memory-utilization 0.9 &
VLLM_PID=$!

echo "==> Waiting for vLLM to load the model…"
for i in $(seq 1 90); do
  sleep 5
  curl -s -o /dev/null "http://127.0.0.1:$PORT/v1/models" -H "Authorization: Bearer $API_KEY" && break
done

echo ""
echo "==> Opening a public tunnel…"
/tmp/cloudflared tunnel --url "http://127.0.0.1:$PORT" 2>&1 | tee /tmp/cf.log &
sleep 8
URL=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" /tmp/cf.log | head -1)

echo ""
echo "==================================================================="
echo "  AMD inference is LIVE. Put these in Vercel → Settings → Env Vars:"
echo "    AMD_BASE_URL = ${URL:-<see /tmp/cf.log>}/v1"
echo "    AMD_API_KEY  = $API_KEY"
echo "    AMD_MODEL    = $SERVED_NAME"
echo "  Then redeploy. Jardo will serve from the AMD GPU (ROCm) first."
echo "  Keep this terminal open (Ctrl-C stops the server)."
echo "==================================================================="
wait $VLLM_PID
