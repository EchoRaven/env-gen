#!/usr/bin/env bash
# Idempotent host setup so `podman-compose up --build` works on this locked-down agent box.
# Solves the two container blockers (see tools/fwdproxy_container_relay/relay.py for the why):
#   1) base images: mirror docker.io -> internal VMVM pull-through; local stand-in for the
#      ghcr `uv` base (not mirrored anywhere).
#   2) in-container pip/npm egress: a host relay carrying the agent's fwdproxy identity, plus
#      a `podman` wrapper that forces `podman build` onto the host network to reach it.
# Safe to run repeatedly. Source or exec before launching a generation.
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELAY_PORT="${RELAY_PORT:-19080}"
say(){ printf '\033[1;36m[podman_setup]\033[0m %s\n' "$*"; }

# 1a. docker.io -> VMVM mirror (pull-through cache; ghcr/docker.io egress is walled for the agent)
mkdir -p ~/.config/containers/registries.conf.d
cat > ~/.config/containers/registries.conf.d/vmvm-mirror.conf <<'EOF'
[[registry]]
location = "docker.io"
[[registry.mirror]]
location = "vmvm-registry.fbinfra.net"
EOF
say "docker.io -> vmvm-registry.fbinfra.net mirror in place"

# 1a2. netavark firewall_driver=none — on this host netavark's nftables ruleset apply FAILS
# ("nft did not return successfully"), so rootless containers can't START (stuck Created) and
# `podman-compose up` deadlocks on `podman wait --condition=healthy`. Skipping the firewall
# rules lets the project bridge + aardvark-dns come up; inter-container name resolution
# (backend -> database) works. NETWORK-only — no [engine] env (that would leak the build proxy
# into runtime containers). Verified: container starts + `database` resolves.
cat > ~/.config/containers/containers.conf <<'EOF'
[network]
firewall_driver = "none"
EOF
say "netavark firewall_driver=none in place"

# 2. host relay FIRST (the uv build below needs it): <host>:RELAY_PORT -> fwdproxy.
if ss -ltn 2>/dev/null | grep -q ":$RELAY_PORT "; then
  say "fwdproxy relay already up on :$RELAY_PORT"
else
  setsid python3 "$REPO/tools/fwdproxy_container_relay/relay.py" >/tmp/fwdproxy_relay.log 2>&1 &
  sleep 2
  ss -ltn 2>/dev/null | grep -q ":$RELAY_PORT " && say "relay started on :$RELAY_PORT" || say "WARN: relay did not start — see /tmp/fwdproxy_relay.log"
fi

# 1b. local stand-in for ghcr.io/astral-sh/uv (VMVM/Harbor don't mirror it): python + uv.
if ! podman image exists ghcr.io/astral-sh/uv:python3.11-bookworm-slim 2>/dev/null; then
  say "building local stand-in for ghcr.io/astral-sh/uv ..."
  tmp="$(mktemp -d)"
  printf 'FROM python:3.11-slim-bookworm\nRUN pip install --no-cache-dir uv\n' > "$tmp/Dockerfile"
  podman build --network=host \
    --build-arg HTTPS_PROXY="http://127.0.0.1:$RELAY_PORT" --build-arg HTTP_PROXY="http://127.0.0.1:$RELAY_PORT" \
    --build-arg https_proxy="http://127.0.0.1:$RELAY_PORT" --build-arg http_proxy="http://127.0.0.1:$RELAY_PORT" \
    -t ghcr.io/astral-sh/uv:python3.11-bookworm-slim "$tmp" >/dev/null 2>&1 \
      && say "uv stand-in built" || say "WARN: uv stand-in build failed (is the relay up?)"
  rm -rf "$tmp"
else
  say "uv stand-in image already present"
fi

say "done. Put tools/podman_shim first on PATH (docker->podman, podman build --network=host),"
say "and export https_proxy=http://127.0.0.1:$RELAY_PORT for the build (podman forwards it)."
