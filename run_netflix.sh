#!/usr/bin/env bash
# One-shot launcher: metagen sidecar (Buck PAR) + forgingground generation on a Meta model.
#
#   MG_KEY='mg-api-...' ./run_netflix.sh            # full launch (sidecar + generation)
#   ./run_netflix.sh --setup                        # one-time: install playwright into fgen
#   ./run_netflix.sh --sidecar-only                 # just (re)start the sidecar, then wait
#   MODEL=claude-5-fable-vertex-genai NAME=netflix-web-r2 ./run_netflix.sh
#
# Key hygiene: MG_KEY comes from the environment (or /tmp/envgen_key.sh) — never hardcoded here.
set -uo pipefail

# ── config (override via env) ────────────────────────────────────────────────
REPO=/home/haibotong/forgingground-gen
FBCODE="${FBCODE:-$HOME/fbsource/fbcode}"
SIDECAR_SUBPATH="${SIDECAR_SUBPATH:-scripts/haibotong/metagen_sidecar}"
FGEN_PY="${FGEN_PY:-$HOME/.conda/envs/fgen/bin/python}"
MODEL="${MODEL:-gpt-5-6-sol-genai-responses}"
PORT="${PORT:-8900}"
NAME="${NAME:-netflix-web-r1}"
ENVGEN_SINGLE_MILESTONE="${ENVGEN_SINGLE_MILESTONE:-1}"

SIDECAR_DIR="$FBCODE/$SIDECAR_SUBPATH"
TARGET="//${SIDECAR_SUBPATH}:metagen_sidecar"
BASE="http://127.0.0.1:$PORT"
LOG="$REPO/gm_${NAME}.log"
SIDECAR_LOG="$REPO/sidecar_${PORT}.log"

say() { printf '\033[1;36m[run_netflix]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[run_netflix] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# ── key ──────────────────────────────────────────────────────────────────────
if [ -z "${MG_KEY:-}" ] && [ -f /tmp/envgen_key.sh ]; then . /tmp/envgen_key.sh; fi

# ── one-time setup: playwright into fgen ─────────────────────────────────────
if [ "${1:-}" = "--setup" ]; then
  say "installing playwright into fgen ..."
  "$FGEN_PY" -m pip install playwright && "$FGEN_PY" -m playwright install chromium
  say "setup done."
  exit 0
fi

# ── sidecar: sync source, (re)start only if not already healthy ──────────────
sidecar_healthy() { curl -sf -m 3 "$BASE/health" >/dev/null 2>&1; }

start_sidecar() {
  [ -d "$FBCODE" ] || die "fbcode checkout not found at $FBCODE (set FBCODE=...). Run 'fbclone fbsource' first."
  [ -n "${MG_KEY:-}" ] || die "MG_KEY not set (export MG_KEY='mg-api-...' or put it in /tmp/envgen_key.sh)."
  mkdir -p "$SIDECAR_DIR"
  cp "$REPO/tools/metagen_sidecar/metagen_sidecar.py" "$SIDECAR_DIR/"
  cp "$REPO/tools/metagen_sidecar/TARGETS" "$SIDECAR_DIR/" 2>/dev/null || true
  say "starting sidecar (buck2 run $TARGET) -> $SIDECAR_LOG"
  ( cd "$FBCODE" && MG_KEY="$MG_KEY" setsid buck2 run "$TARGET" -- --port "$PORT" ) \
      >"$SIDECAR_LOG" 2>&1 &
  say "waiting for sidecar health (first build can take a few min) ..."
  for i in $(seq 1 150); do
    sidecar_healthy && { say "sidecar healthy: $(curl -s "$BASE/health")"; return 0; }
    sleep 5
  done
  die "sidecar did not become healthy in time — see $SIDECAR_LOG"
}

if sidecar_healthy; then
  say "sidecar already up on :$PORT ($(curl -s "$BASE/health"))"
else
  start_sidecar
fi

# ── smoke test ───────────────────────────────────────────────────────────────
say "smoke test ($MODEL) ..."
SMOKE=$(curl -s -m 60 "$BASE/v1/chat/completions" -H 'Content-Type: application/json' \
  -d "{\"model\":\"$MODEL\",\"max_tokens\":32,\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: pong\"}]}")
echo "  -> $(echo "$SMOKE" | head -c 300)"
echo "$SMOKE" | grep -q '"content": "pong"' || say "WARN: smoke didn't return 'pong' — check model access / sidecar log before trusting the run."

[ "${1:-}" = "--sidecar-only" ] && { say "sidecar-only: leaving it running on :$PORT (kill with: pkill -f metagen_sidecar)"; exit 0; }

# ── preflight: playwright present? ───────────────────────────────────────────
"$FGEN_PY" -c "import playwright" 2>/dev/null || \
  say "WARN: playwright missing in fgen — visual/browser gates will fail. Run: ./run_netflix.sh --setup"

# ── launch generation ────────────────────────────────────────────────────────
DESC_FILE="$REPO/design_inputs/netflix/DESCRIPTION.txt"
DESC=""; [ -f "$DESC_FILE" ] && DESC="$(cat "$DESC_FILE")"
[ -n "$DESC" ] || say "WARN: no DESCRIPTION.txt — generation will rely on screenshots+dataset only."
say "launching generation '$NAME' on $MODEL -> $LOG"
cd "$REPO/agent" || die "no $REPO/agent"
OPENAI_API_KEY=dummy \
ENVGEN_SINGLE_MILESTONE="$ENVGEN_SINGLE_MILESTONE" \
PYTHONPATH="$REPO/agent" \
"$FGEN_PY" -m env_generator.llm_generator.main \
  --provider openai --api-base "$BASE/v1" \
  --model "$MODEL" \
  --name "$NAME" \
  --description "$DESC" \
  --design-input "$REPO/design_inputs/netflix" \
  2>&1 | tee "$LOG"

say "generation process ended. log: $LOG   (sidecar still running; pkill -f metagen_sidecar to stop)"
