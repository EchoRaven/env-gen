#!/usr/bin/env bash
# Re-run the hidden evaluation on submissions, one at a time (the stack phase is serialised by evals/.hidden.lock).
# usage: rescore.sh <parts> <tag=workspace> ...     e.g. rescore.sh api,ui,static selfval-it1=/path/to/workspace
set -u
cd "$(dirname "$0")/.."
parts=$1; shift
for pair in "$@"; do
  tag=${pair%%=*}; ws=${pair#*=}
  sg docker -c "env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT -u CLAUDE_CODE_SESSION_ID -u CLAUDE_CODE_CHILD_SESSION PLAYWRIGHT_BROWSERS_PATH=/home/user/project/shabi_forest/.envs/cache/ms-playwright PYTHONDONTWRITEBYTECODE=1 /home/user/project/shabi_forest/.envs/venvs/thb-validator/bin/python -I -B scripts/hidden_eval.py $ws $tag --parts $parts"
done
