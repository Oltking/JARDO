#!/usr/bin/env bash
# Serve Gemma on your AMD Instinct droplet via PyTorch/ROCm + transformers (no
# vLLM/CUDA), OpenAI-compatible, and expose it publicly to paste into Vercel.
#
# Run in the droplet's JupyterLab Terminal, in the same folder as
# amd_openai_server.py:
#     export HF_TOKEN=hf_xxx        # Read token; accept Gemma's license first
#     bash amd-serve.sh
set -euo pipefail

MODEL="${MODEL:-google/gemma-2-9b-it}"
SERVED_NAME="${SERVED_NAME:-gemma}"
API_KEY="${API_KEY:-jardo-amd-$(python3 -c 'import secrets;print(secrets.token_hex(6))')}"
PORT="${PORT:-8000}"
export MODEL SERVED_NAME API_KEY

[ -z "${HF_TOKEN:-}" ] && { echo "!! export HF_TOKEN=hf_xxx first (accept license at huggingface.co/$MODEL)"; exit 1; }

echo "==> GPU check (ROCm PyTorch):"
python3 -c "import torch;print('  torch',torch.__version__,'| gpu available:',torch.cuda.is_available(),'| hip:',getattr(torch.version,'hip',None))" \
  || { echo '!! torch not importable — this must run in the ROCm python env'; exit 1; }

echo "==> Installing server deps (transformers, accelerate, fastapi, uvicorn)…"
pip install -q -U "transformers>=4.44" accelerate fastapi "uvicorn[standard]" huggingface_hub
python3 -c "from huggingface_hub import login; import os; login(os.environ['HF_TOKEN'])"

echo "==> Starting the AMD/ROCm OpenAI server on :$PORT (model load can take a few min)…"
python3 -m uvicorn amd_openai_server:app --host 0.0.0.0 --port "$PORT" &
SRV=$!
for i in $(seq 1 120); do sleep 5
  curl -s -o /dev/null -H "Authorization: Bearer $API_KEY" "http://127.0.0.1:$PORT/v1/models" && { echo "  server up"; break; }
done

echo "==> Exposing a public URL…"
# The download host uses a TLS-inspecting proxy here, so -k is needed for this binary.
if ! command -v cloudflared >/dev/null 2>&1; then
  curl -kfsSL -o /tmp/cloudflared \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
    && chmod +x /tmp/cloudflared && export PATH="/tmp:$PATH" \
    || echo "  (cloudflared download failed — see the 'Plan B' note printed below)"
fi
if command -v cloudflared >/dev/null 2>&1; then
  cloudflared tunnel --url "http://127.0.0.1:$PORT" >/tmp/cf.log 2>&1 &
  sleep 10
  URL=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" /tmp/cf.log | head -1)
fi

echo ""
echo "==================================================================="
echo "  AMD inference is LIVE (Gemma on ROCm). Put in Vercel env vars:"
echo "    AMD_BASE_URL = ${URL:-<no tunnel — try the proxy URL, Plan B>}/v1"
echo "    AMD_API_KEY  = $API_KEY"
echo "    AMD_MODEL    = $SERVED_NAME"
echo ""
echo "  Plan B if no tunnel URL: this JupyterLab likely proxies ports, so try:"
echo "    https://radeon-global.anruicloud.com/instances/hf-254-7ebcfd21/proxy/$PORT/v1"
echo "  Redeploy Vercel, then: curl https://jardo.vercel.app/api/status"
echo "  Keep this terminal open (Ctrl-C stops the server)."
echo "==================================================================="
wait $SRV
