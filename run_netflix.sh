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
# 2026-08-18: fall back to the repo venv. ~/.conda/envs/fgen does not exist on devvm57505, and
# the repo venv has env_generator + playwright (every fix of 2026-08-18 was validated on it).
FGEN_PY="${FGEN_PY:-$HOME/.conda/envs/fgen/bin/python}"
[ -x "$FGEN_PY" ] || FGEN_PY="$REPO/.venv/bin/python"
MODEL="${MODEL:-gpt-5-6-sol-genai-responses}"
PORT="${PORT:-8900}"
NAME="${NAME:-netflix-web-r1}"
ENVGEN_SINGLE_MILESTONE="${ENVGEN_SINGLE_MILESTONE:-1}"

# 2026-08-18: the shim MUST be first on PATH. This host has no `docker` binary; the repo ships
# tools/podman_shim (docker->podman, docker compose->podman-compose). Without it every container
# call used to fail silently inside a try — and since #945 the preflight ABORTS the run instead,
# so a launcher that does not set this would now stop at second one.
case ":$PATH:" in *":$REPO/tools/podman_shim:"*) ;; *) PATH="$REPO/tools/podman_shim:$PATH" ;; esac
export PATH

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

# ── package-registry egress for the app builds ───────────────────────────────
# The generated frontend/backend Dockerfiles run `npm install` / `pip install` with no
# proxy args of their own, and this host cannot resolve registry.npmjs.org or pypi.org
# directly (`getaddrinfo EAI_AGAIN`). The local forwarder on :19080 is what makes them
# reachable, and `--network=host` builds see it on 127.0.0.1 — this is exactly what
# launch_netflix.sh:41-42 has always exported. run_netflix.sh did not, so r155/r156 both
# died on EAI_AGAIN: three identical 682s frontend builds before the run gave up. It only
# stayed hidden this long because a warm image cache meant npm never actually ran.
#
# NOTE the asymmetry: base IMAGES come from the internal mirror and need the proxy
# UNSET (tools/ensure_base_images.sh, see COMMANDS_next_session.md); package registries
# need it SET. Do not "simplify" these into one setting.
PKG_PROXY="${PKG_PROXY:-http://127.0.0.1:19080}"
if curl -sf -m 3 -o /dev/null -x "$PKG_PROXY" https://registry.npmjs.org/ 2>/dev/null; then
  export http_proxy="$PKG_PROXY" https_proxy="$PKG_PROXY"
  export HTTP_PROXY="$PKG_PROXY" HTTPS_PROXY="$PKG_PROXY"
  export no_proxy="127.0.0.1,localhost,.fbinfra.net,.fbcdn.net,.facebook.com,.thefacebook.com"
  export NO_PROXY="$no_proxy"
  say "package-registry proxy OK ($PKG_PROXY) — npm/pip reachable inside builds"
else
  say "WARN: no package-registry egress via $PKG_PROXY — every frontend build will fail"
  say "      with 'EAI_AGAIN registry.npmjs.org' after ~682s, twice per validation."
  say "      Start the forwarder (or set PKG_PROXY=...) before trusting this run."
fi

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
