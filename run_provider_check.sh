#!/usr/bin/env bash
# Run the LLM provider smoke test with a Python that has the required SDKs.
#
# Usage:
#   ./run_provider_check.sh
#
# Keys: export them first, or prefix the command, e.g.
#   OPENAI_API_KEY=... OPENROUTER_API_KEY=... ANTHROPIC_API_KEY=... GOOGLE_API_KEY=... \
#     ./run_provider_check.sh
#
# Override the interpreter if you have a better-provisioned one:
#   PYTHON=/path/to/python ./run_provider_check.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Default to the env that already has yaml/openai/anthropic/google-genai.
PYTHON="${PYTHON:-/data/common/haibotong/DecodingTrust-Agent-Platform/.venv/bin/python}"

if [[ ! -x "$PYTHON" ]]; then
  echo "ERROR: Python not found at: $PYTHON" >&2
  echo "Set PYTHON=/path/to/python and retry." >&2
  exit 2
fi

echo "Using python: $PYTHON ($($PYTHON --version 2>&1))"

# Check required modules; auto-install missing ones via uv if available.
REQUIRED=(yaml openai anthropic google.genai)
missing=()
for m in "${REQUIRED[@]}"; do
  if ! "$PYTHON" -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('$m') else 1)" 2>/dev/null; then
    missing+=("$m")
  fi
done

if (( ${#missing[@]} > 0 )); then
  echo "Missing modules: ${missing[*]}"
  # map import names -> pip package names
  declare -A PKG=( [yaml]=pyyaml [openai]=openai [anthropic]=anthropic [google.genai]=google-genai )
  pkgs=(); for m in "${missing[@]}"; do pkgs+=("${PKG[$m]}"); done
  if command -v uv >/dev/null 2>&1; then
    echo "Installing with uv: ${pkgs[*]}"
    uv pip install --python "$PYTHON" "${pkgs[@]}"
  elif "$PYTHON" -m pip --version >/dev/null 2>&1; then
    echo "Installing with pip: ${pkgs[*]}"
    "$PYTHON" -m pip install "${pkgs[@]}"
  else
    echo "ERROR: cannot auto-install (no uv, no pip). Install manually: ${pkgs[*]}" >&2
    exit 3
  fi
fi

exec "$PYTHON" "$HERE/check_llm_providers.py"
