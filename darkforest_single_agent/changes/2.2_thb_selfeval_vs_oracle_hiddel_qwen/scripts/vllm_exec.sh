#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
source /home/user/project/shabi_forest/.envs/env.sh
source /home/user/project/shabi_forest/changes/0.02_qwen_test/scripts/env.sh
export TMPDIR=/home/user/project/shabi_forest/.envs/tmp/q22
mkdir -p "$TMPDIR"
exec >> "$HERE/vllm_server.log" 2>&1
exec vllm serve RedHatAI/Qwen3.8-27B-INT4 \
  --host 127.0.0.1 --port 8000 --served-model-name local \
  --gpu-memory-utilization 0.92 --max-model-len 262144 \
  --max-num-seqs 8 --max-num-batched-tokens 8192 --kv-cache-dtype fp8 \
  --reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser qwen3_xml \
  --enable-prompt-tokens-details
