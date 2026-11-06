#!/usr/bin/env bash
# Start the fixed native-262K Qwen server as a persistent user service.
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
UNIT=shabi-forest-qwen-2-2.service
PIDF="$HERE/vllm_server.pid"

if systemctl --user is-active --quiet "$UNIT"; then
  pid=$(systemctl --user show "$UNIT" --property=MainPID --value)
  cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline")
  if [[ "$cmd" != *'vllm serve RedHatAI/Qwen3.8-27B-INT4'* ||
        "$cmd" != *'--max-model-len 262144'* ||
        "$cmd" != *'--kv-cache-dtype fp8'* ]]; then
    echo "ERROR: $UNIT is active with an unexpected command" >&2
    exit 1
  fi
  echo "$pid" > "$PIDF"
else
  if curl -sf --max-time 3 http://127.0.0.1:8000/health >/dev/null; then
    echo "ERROR: port 8000 has a healthy server outside $UNIT; inspect it before reuse" >&2
    exit 1
  fi
  systemctl --user reset-failed "$UNIT" 2>/dev/null || true
  systemd-run --user --collect --unit="${UNIT%.service}" \
    --property=Restart=on-failure --property=RestartSec=30s \
    --working-directory="$HERE" /usr/bin/bash "$HERE/scripts/vllm_exec.sh"
  pid=$(systemctl --user show "$UNIT" --property=MainPID --value)
  echo "$pid" > "$PIDF"
fi

for _ in $(seq 1 120); do
  if curl -sf --max-time 3 http://127.0.0.1:8000/health >/dev/null; then
    echo "vLLM healthy (pid $(cat "$PIDF"), unit $UNIT)"
    exit 0
  fi
  systemctl --user is-active --quiet "$UNIT" || {
    echo "vLLM service stopped; see $HERE/vllm_server.log" >&2
    exit 1
  }
  sleep 10
done
echo "vLLM not healthy after 20 min; see $HERE/vllm_server.log" >&2
exit 1
