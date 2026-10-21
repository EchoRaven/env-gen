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
# #1203qt: A UNIQUE basetemp, unless the caller named one.
#
# `--basetemp` does not mean "put the temp dirs here". pytest's own tmpdir.py does
#     if basetemp.exists(): rm_rf(basetemp)
#     basetemp.mkdir(mode=0o700)
# so ANY second pytest given the same path DELETES the first one's temp dirs mid-run. The
# symptom is a FileNotFoundError out of `json_store._save_raw`'s `os.replace` -- the temp
# file vanished between the write and the rename -- and it reads as a defect in the code
# under test. 2026-10-20 spent a while on one such failure that passed 4/4 alone.
#
# The flock above already refuses a second SUITE. What it cannot see is a hand-typed
# `python -m pytest ... --basetemp=<the shared path>`, which bypasses this script and so
# bypasses the lock; conftest.py prints a banner for that case, but a banner at the TOP of
# the output is invisible to anyone reading the tail. So the suite defends its own temp
# directory instead of relying on that.
#
# Cleaned up on success only: a failing run's temp tree is the evidence for the failure, and
# /data is a shared disk that nobody reclaims (#1202ap counted 5 orphaned partial writes on
# it), so a passing run should not leave one behind.
case " $* " in
  *" --basetemp"*|*" --basetemp="*) _own_basetemp="" ;;
  *)
    _own_basetemp="${SUITE_BASETEMP_ROOT:-/data/common/haibotong/pytest_tmp}/suite.$$"
    mkdir -p "$(dirname "$_own_basetemp")" 2>/dev/null
    set -- "$@" "--basetemp=$_own_basetemp"
    echo "[suite] basetemp: $_own_basetemp (unique per run; pytest rm_rf's whatever it is given)"
    ;;
esac

# #1203qy: `--basetemp` DOES NOT GOVERN `tempfile.mkdtemp()`. #1203qt above fixed where
# pytest's own `tmp_path`/`tmpdir` fixtures live, and stopped there -- which left the larger
# half open, because 299 test files under agent/tests, tests/ and multi_agent/tests call
# `tempfile.mkdtemp()` directly. Those honour TMPDIR, not --basetemp, and pytest never
# cleans them: nothing it did not create is its to remove.
#
# MEASURED 2026-10-20, and it had already happened: /tmp held 1,474,363 entries totalling
# 177G, and `/` was down to 77M of 1.8T. The leaked names map one-to-one onto the tests that
# make them -- glob_nopath_* from test_glob_no_path.py, appr_* from test_approval_gate.py,
# refmat_* from test_reference_materials.py, runbudget_shim_* from
# test_run_budget_extraction.py, pending_stale_* from test_pipeline_edge_cases.py -- plus
# the anonymous tmpXXXXXXXX from every bare mkdtemp(). The framework itself is clean: zero
# mkdtemp under agent/env_generator, so this is the suite leaking, not the product.
#
# A full root filesystem is the worst shape of failure here, because it is SILENT in the
# wrong direction: the harness loses every command's stdout while the commands still run, so
# a scan returns nothing and reads exactly like a clean result. That already cost a session.
#
# Same treatment as basetemp: a per-run directory on the roomy disk, removed on success, and
# an explicit caller choice is left alone. #1203qw did this for mutate.py's child pytest;
# the suite needs it for the same reason.
# `${TMPDIR:-}`, not `$TMPDIR`: this script runs under `set -u`, and the whole point of
# this block is the case where TMPDIR is UNSET -- so the naive spelling aborts the suite on
# the exact path it exists to handle. It did, immediately, the first time it ran for real.
if [ -n "${TMPDIR:-}" ]; then
  echo "[suite] TMPDIR left as the caller set it: $TMPDIR"
  _own_tmpdir=""
else
  _own_tmpdir="${SUITE_TMPDIR_ROOT:-/data/common/haibotong/pytest_tmp}/tmp.$$"
  if mkdir -p "$_own_tmpdir" 2>/dev/null; then
    export TMPDIR="$_own_tmpdir"
    echo "[suite] TMPDIR: $_own_tmpdir (299 test files call tempfile.mkdtemp() directly)"
  else
    # Do not silently fall back to /tmp: that is the condition this block exists to prevent.
    echo "[suite] WARNING: could not create $_own_tmpdir -- tempfile.mkdtemp() will land in" \
         "${TMPDIR:-/tmp} and is NOT cleaned by pytest. Check df before trusting this run."
    _own_tmpdir=""
  fi
fi

"$PY" -m pytest "$@"
rc=$?
if [ -n "$_own_basetemp" ] && [ "$rc" = "0" ]; then
  rm -rf -- "$_own_basetemp" 2>/dev/null
fi
if [ -n "$_own_tmpdir" ] && [ "$rc" = "0" ]; then
  rm -rf -- "$_own_tmpdir" 2>/dev/null
fi
echo "[suite] exit=$rc"
exit $rc
