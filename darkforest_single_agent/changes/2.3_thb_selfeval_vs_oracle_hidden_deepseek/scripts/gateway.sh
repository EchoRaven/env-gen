#!/usr/bin/env bash
# The model gateway of 2.3 (it replaces 2.2's vLLM server): scripts/llm_gateway.py as the persistent user unit of
# scripts/gateway.json (Restart=on-failure), listening on 127.0.0.1 only. It holds the API key (the worker sandbox gets
# a dummy key and cannot see .envs/secrets), forwards POST /v1/responses for the configured model only, sends it
# upstream as `upstream_model`, keeps at most `max_in_flight` requests in flight, and retries 429/5xx with backoff.
# The reasoning effort is passed through unchanged. Log: logs/gateway/gateway.jsonl (one line per request, no prompts).
#   scripts/gateway.sh          start if not running (idempotent); exit 0 once /health answers
#   scripts/gateway.sh stop     stop the unit
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
read -r UNIT HOST PORT UPSTREAM MODEL UPMODEL MAXF KEYF < <(python3 -I -c "
import json; g=json.load(open('$HERE/scripts/gateway.json'))
print(g['unit'], g['host'], g['port'], g['upstream'], g['model'], g['upstream_model'], g['max_in_flight'], g['api_key_file'])")
PY=/home/user/project/shabi_forest/.envs/bin/python3.12
health() { curl -sf -m 10 "http://$HOST:$PORT/health" >/dev/null; }
if [ "${1:-}" = stop ]; then
  systemctl --user stop "$UNIT" 2>/dev/null || true
  systemctl --user reset-failed "$UNIT" 2>/dev/null || true
  echo "gateway $UNIT stopped"; exit 0
fi
if systemctl --user is-active --quiet "$UNIT" && health; then
  echo "gateway $UNIT healthy on $HOST:$PORT"; exit 0
fi
if ! systemctl --user is-active --quiet "$UNIT"; then
  if health; then echo "ERROR: $HOST:$PORT answers /health but $UNIT is not running; inspect it" >&2; exit 1; fi
  systemctl --user reset-failed "$UNIT" 2>/dev/null || true
  mkdir -p "$HERE/logs/gateway"
  systemd-run --user --quiet --unit="$UNIT" -p Restart=on-failure -p RestartSec=10 \
    --working-directory="$HERE" --setenv=GATEWAY_HOST="$HOST" \
    "$PY" -I "$HERE/scripts/llm_gateway.py" "$PORT" "$HERE/logs/gateway" "$KEYF" "$UPSTREAM" "$MODEL" "$MAXF" 0 "$UPMODEL" -
fi
for _ in $(seq 30); do
  if health; then echo "gateway $UNIT healthy on $HOST:$PORT ($MODEL -> $UPMODEL, at most $MAXF in flight)"; exit 0; fi
  sleep 1
done
echo "ERROR: gateway $UNIT not healthy; see: journalctl --user -u $UNIT" >&2
exit 1
