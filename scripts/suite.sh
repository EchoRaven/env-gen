#!/usr/bin/env bash
# Run the agent test suite under a repo-wide exclusive lock.
#
# WHY (2026-09-05): two Claude sessions ran `pytest tests/` on this same work tree at the
# same time. Three full runs produced 20 / 3 / 32 failures whose failure sets were PAIRWISE
# DISJOINT — zero tests failed in all three — because the runs contend on temp paths, on
# files the tests write into the repo, and on CPU. Four rounds of attribution were built on
# those numbers and all of them had to be retracted. Run exclusively: 14781 passed, 0 failed.
#
# Usage:  scripts/suite.sh [pytest args...]        # default: tests/ -q
#         SUITE_WAIT=1 scripts/suite.sh            # block until the lock frees instead of exiting
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
ROOT=$(pwd -P)
# absolute: the trap fires AFTER `cd agent`, and a relative path removed
# agent/.suite.lock.info instead, leaving a stale holder record at the root.
LOCK="$ROOT/.suite.lock"
INFO="$ROOT/.suite.lock.info"
exec 9>"$LOCK" || { echo "cannot open $LOCK" >&2; exit 1; }

if [ "${SUITE_WAIT:-0}" = "1" ]; then
  echo "[suite] waiting for the lock…"; flock 9
else
  if ! flock -n 9; then
    echo "[suite] ANOTHER RUN HOLDS THE LOCK — not starting (results would be untrustworthy)." >&2
    [ -f "$INFO" ] && sed 's/^/[suite]   /' "$INFO" >&2
    echo "[suite] re-run with SUITE_WAIT=1 to queue behind it." >&2
    exit 3
  fi
fi

printf 'pid=%s\nsession=%s\nstarted=%s\nargs=%s\n' \
  "$$" "${CLAUDE_SESSION_ID:-unknown}" "$(date -Is)" "${*:-<every test root, see below>}" > "$INFO"
trap 'rm -f "$INFO"' EXIT

export ENVGEN_SUITE_LOCK_HELD=1   # conftest: this run IS the holder, do not warn
PY=${SUITE_PYTHON:-/home/haibotong/miniconda3/envs/dt/bin/python}
cd agent || exit 1

# #1203gc: the default used to be `tests/` alone, and `tests/` means agent/tests/ from here.
# Two other test roots exist in this repo and the gate never ran either of them:
#   env_generator/llm_generator/multi_agent/tests/   78 tests, 1.9s -- lifecycle,
#       database_scaffold, oauth_scaffold, mcp_scaffold, dockerfile_lint, codehub.service
#   ../tests/                                        41 tests, 1.7s -- approval endpoints,
#       multitenant auth, chat console, generation task db
# 119 passing tests on live product modules, 3.6s, outside every patch gate since 2026-06-18
# (3b71e337 made both roots local-only; agent/tests is local-only too and IS run, so being
# untracked was never the reason). lifecycle.py in particular is the canonical endpoint-kind
# predicate module, patched as recently as #1203fy against the agent/tests suite alone.
# Absent roots are skipped rather than failing collection, because all three are untracked and
# a fresh clone has none of them.
if [ $# -eq 0 ]; then
  ROOTS=""
  for _root in tests ../tests env_generator/llm_generator/multi_agent/tests; do
    [ -d "$_root" ] && ROOTS="$ROOTS $_root"
  done
  echo "[suite] roots:$ROOTS"
  # shellcheck disable=SC2086  # word splitting is what builds the argv here
  set -- $ROOTS -q
fi
"$PY" -m pytest "$@"
rc=$?
echo "[suite] exit=$rc"
exit $rc
