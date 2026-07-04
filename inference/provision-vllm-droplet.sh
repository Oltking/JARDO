#!/usr/bin/env bash
# Provision an on-demand AMD MI300X droplet running vLLM (spec §3 topology: scale-to-zero).
#
# Sources (spec §0.1):
#   docs/vendor/amd/developer-cloud-getting-started.md  (droplet creation, ROCm image, SSH)
#   docs/vendor/local-inference/vllm-rocm-install.md    (rocm/vllm docker image)
#   docs/vendor/local-inference/vllm-openai-compatible-server.md (serve flags)
#
# Cost reality (ARCHITECTURE.md finding 1): ~$1.99/hr while up. This script is meant
# to be run for batch work / evals, and the droplet DESTROYED afterwards.
# Requires: doctl authenticated against the AMD Developer Cloud (DigitalOcean-based),
# an SSH key uploaded, and GPU droplet quota. Not yet run — validate on first GPU session.
set -euo pipefail

MODEL="${1:?usage: provision-vllm-droplet.sh <model-id> [droplet-name]}"
NAME="${2:-jarvis-vllm}"
REGION="${JARVIS_GPU_REGION:-atl1}"
SIZE="${JARVIS_GPU_SIZE:-gpu-mi300x1-192gb}"

echo ">> creating droplet $NAME ($SIZE, $REGION) — billing starts NOW (~\$1.99/hr)"
doctl compute droplet create "$NAME" \
  --region "$REGION" --size "$SIZE" \
  --image "amd-pytorch-rocm" \
  --ssh-keys "$(doctl compute ssh-key list --format ID --no-header | head -1)" \
  --wait

IP=$(doctl compute droplet get "$NAME" --format PublicIPv4 --no-header)
echo ">> droplet up at $IP — starting vLLM (OpenAI-compatible server on :8000)"

ssh -o StrictHostKeyChecking=accept-new "root@$IP" bash -s <<EOF
docker run -d --name vllm \
  --device=/dev/kfd --device=/dev/dri --security-opt seccomp=unconfined \
  --group-add video --shm-size 16g -p 8000:8000 \
  rocm/vllm:latest \
  vllm serve "$MODEL" --host 0.0.0.0 --port 8000
EOF

echo ">> vLLM starting. Set in inference/routing.toml:"
echo "     vllm_endpoint = \"http://$IP:8000/v1\""
echo "     vllm_large    = \"$MODEL\""
echo ">> WHEN DONE (stop billing):  doctl compute droplet delete $NAME"
