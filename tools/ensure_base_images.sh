#!/usr/bin/env bash
# ensure_base_images.sh — idempotent preflight that makes forgingground-gen's
# docker_up build+up work OFFLINE on a sensitive devserver, immune to two failure
# modes that killed r22/r23 (see memory project-forgingground-netflix-bringup):
#
#   1. Base images get PRUNED → docker_up rebuild fails pulling FROM bases.
#   2. The docker.io mirror (vmvm-registry.fbinfra.net) mTLS client cert is a
#      SYMLINK into /var/facebook/credentials/... which rootless podman CANNOT
#      follow during the TLS handshake → ENOENT ("no such file") → every pull fails.
#
# It is generic (no app/product literals): these are the pipeline's standard bases
# for ANY FastAPI+Postgres+React app. Safe to run before every launch; a no-op when
# everything is already cached. Reversible: the only host change is real cert copies
# at the podman certs.d path (revert = re-symlink to the x509 pem).
#
# Usage: tools/ensure_base_images.sh   (exits non-zero if it cannot make bases ready)
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$REPO/tools/podman_shim:$PATH"
: "${http_proxy:=http://127.0.0.1:19080}"; : "${https_proxy:=http://127.0.0.1:19080}"
export http_proxy https_proxy
export no_proxy="${no_proxy:-127.0.0.1,localhost,.fbinfra.net,.fbcdn.net,.facebook.com,.thefacebook.com}"

MIRROR="vmvm-registry.fbinfra.net"
CERTD="$HOME/.config/containers/certs.d/$MIRROR"
SRC_PEM="/var/facebook/credentials/${USER}/x509/${USER}.pem"   # combined cert+key
# docker.io bases (pulled via the mirror); uv base is BUILT (ghcr is not mirrored).
DOCKER_IO_BASES=(node:20-alpine nginx:alpine postgres:16 python:3.11-slim-bookworm)
UV_BASE="ghcr.io/astral-sh/uv:python3.11-bookworm-slim"

log(){ printf '[ensure-bases] %s\n' "$*"; }
have(){ podman image exists "$1" 2>/dev/null; }

# --- 1. mirror mTLS cert: ensure REAL readable files (not an unfollowable symlink) ---
ensure_cert(){
  mkdir -p "$CERTD"
  local ok=1 f
  for f in client.cert client.key; do
    # A plain readable regular file that podman can open is what we need. A symlink
    # into /var/facebook is exactly what rootless podman fails to follow → rebuild.
    if [ -f "$CERTD/$f" ] && [ ! -L "$CERTD/$f" ] && head -c1 "$CERTD/$f" >/dev/null 2>&1; then
      continue
    fi
    ok=0
  done
  [ "$ok" = 1 ] && { log "mirror cert: real copies present"; return 0; }
  if [ ! -r "$SRC_PEM" ]; then
    log "WARN: source pem $SRC_PEM not readable; cannot heal mirror cert (agent x509 may be re-provisioning)"
    return 1
  fi
  # combined pem holds both the cert chain and the private key; podman reads the
  # cert from client.cert and the key from client.key, so both point at the pem.
  install -m 600 "$SRC_PEM" "$CERTD/client.cert" && install -m 600 "$SRC_PEM" "$CERTD/client.key" \
    && log "mirror cert: healed (real 0600 copies from $SRC_PEM)" || { log "ERROR healing cert"; return 1; }
}

# --- 2. docker.io bases: pull any that are missing (via the working mirror) ---
ensure_docker_io(){
  local img rc=0
  for img in "${DOCKER_IO_BASES[@]}"; do
    if have "docker.io/library/$img" || have "$img"; then log "cached: $img"; continue; fi
    log "pull: $img"
    # The mirror (vmvm-registry.fbinfra.net) is INTERNAL. podman does NOT reliably
    # honor no_proxy for the registry ping, so with http_proxy set the mirror ping
    # goes through the external proxy → "Failed to resolve host" and the pull fails
    # (observed r46 launch-abort 2026-08-04: bases evicted between runs, then
    # unpullable WITH the proxy but pullable WITHOUT it). Pull with the proxy UNSET
    # (a subshell, so the uv-base BUILD below keeps its proxy for external pip).
    if ! ( unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY; podman pull "$img" ) >/dev/null 2>&1; then log "ERROR pulling $img"; rc=1; fi
  done
  return $rc
}

# --- 3. uv base: ghcr is blocked + not mirrored → build a functional equivalent ---
#     python-slim + `pip install uv`, tagged as the ghcr name so the backend
#     Dockerfile's `FROM ghcr.io/astral-sh/uv:...` resolves from cache (policy=missing).
#     Backend base does not affect UI fidelity, only the backend runtime.
ensure_uv_base(){
  if have "$UV_BASE"; then log "cached: $UV_BASE"; return 0; fi
  have python:3.11-slim-bookworm || have docker.io/library/python:3.11-slim-bookworm \
    || { log "ERROR: python:3.11-slim-bookworm missing (needed to build uv base)"; return 1; }
  local d; d="$(mktemp -d)"
  printf 'FROM python:3.11-slim-bookworm\nRUN pip install --no-cache-dir uv && uv --version\n' > "$d/Dockerfile"
  log "build: $UV_BASE (python-slim + pip install uv; via podman_shim --network=host + proxy)"
  local rc=0
  podman build -t "$UV_BASE" "$d" >/dev/null 2>&1 || { log "ERROR building uv base"; rc=1; }
  rm -rf "$d"; return $rc
}

rc=0
ensure_cert      || rc=1
ensure_docker_io || rc=1
ensure_uv_base   || rc=1

missing=()
for img in "${DOCKER_IO_BASES[@]}" "$UV_BASE"; do
  have "$img" || have "docker.io/library/$img" || missing+=("$img")
done
if [ "${#missing[@]}" -eq 0 ]; then
  log "OK: all base images cached; docker_up can build+up offline"
  exit 0
fi
log "NOT READY: missing ${missing[*]}"
exit "${rc:-1}"
