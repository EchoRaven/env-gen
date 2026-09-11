"""#1202ko: the kickoff killed a run whose lane was committing code at the time.

`#28`'s fast stall escape exists for "a lane that can never emit a clean section" — Gemini
re-mangling its draft — so that one broken attendee cannot pin the run in phase=initial for the
full `KICKOFF_TIMEOUT_SEC` (1200s). For that case it is right. But it reads only the MEETING
DOCUMENT, so a lane that is busy looks exactly like a lane that is broken, and the run dies at
242s with ~958s of kickoff budget unspent.

tiktok-r115, reconstructed from its own ledgers:

    17:15:03  M2 kickoff opens
    17:15:05  kickoff_request delivered to frontend, priority=high
    17:18:46  frontend READS it
    17:18:57  frontend claims the P0 the framework had just dispatched
              (coord_frontend_gate_current_dead_files_m2)
    17:17-17:21  frontend makes FIVE commits and completes a task — all hub-visible
    17:23:15  driver declares `initial_stall` and ABORTS

The run had already DELIVERED milestone 1. The framework asked the lane to do two things at
once and then killed the run for finishing the urgent one.

So the check now asks the hubs whether a missing attendee is actually working, and declines the
FAST escape if so. `KICKOFF_TIMEOUT_SEC` still bounds the wait — that 1200s is exactly what it
is for.

WHAT IS VERIFIED: a missing attendee with hub writes inside the kickoff window declines the
fast escape; one with none still releases it; activity from BEFORE this kickoff does not count;
and any fault falls back to the old behaviour rather than extending a wait.

WHAT IS NOT — and the first draft of this file claimed otherwise, wrongly: that it tells r115
and r112 apart. Measured over the real ledgers it declines BOTH (r115 frontend: a completed
task + 2 commits; r112 backend: 1 endpoint re-registration). The earlier "r112 wrote nothing"
came from scanning two stores instead of five. This is a LOOSER escape, not a smarter one.

It is still the right trade for a reason that does not need that discrimination: declining only
DELAYS — at `KICKOFF_TIMEOUT_SEC` the driver runs the SAME `_kickoff_fallback_or_reconcile`, so
the worst case is ~16 extra minutes, against r115's actual cost of a run that had already
delivered milestone 1. And #28's own case — a lane re-mangling its draft, emitting nothing —
touches no hub either, so it still escapes at 242s.

Nor does it claim r115 would have completed M2: it would have had the remaining kickoff budget
instead of none, and whether the lane then recorded a section is unknown.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
_LLM = _AGENT / "env_generator" / "llm_generator"
for _p in (str(_LLM), str(_AGENT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ast          # noqa: E402
import inspect      # noqa: E402
import json         # noqa: E402
import textwrap     # noqa: E402
import time         # noqa: E402
import types        # noqa: E402

from multi_agent.runtime.kickoff_driver import KickoffDriver   # noqa: E402


def _driver(base_dir):
    orch = types.SimpleNamespace(hubs=types.SimpleNamespace(base_dir=str(base_dir)))
    d = KickoffDriver.__new__(KickoffDriver)
    d._orch = orch
    return d


def _hub(tmp, store, records):
    p = tmp / "shared" / "hubs"
    p.mkdir(parents=True, exist_ok=True)
    (p / (store + ".json")).write_text(json.dumps(records), encoding="utf-8")


# --- the two corpus cases -------------------------------------------------------------------

def test_r115s_working_frontend_holds_the_escape_open(tmp_path):
    """★ The case. Five commits and a completed task inside the stall window."""
    now = time.time()
    _hub(tmp_path, "codehub_commits", {
        "_meta": {"version": 1},
        "c1": {"_updated_by": "frontend", "_updated_at": now - 300},
        "c2": {"_updated_by": "frontend", "_updated_at": now - 240},
        "c3": {"_updated_by": "frontend", "_updated_at": now - 180},
    })
    got = _driver(tmp_path)._missing_attendee_is_working_1202ko(
        {"missing": ["frontend"]}, elapsed=480)
    assert got is not None, "a lane committing code is not stalled"
    assert got[0] == "frontend" and got[1] == 3


def test_a_genuinely_silent_lane_still_releases_the_escape(tmp_path):
    """★ The negative case: #28 must keep working for the lane it was written for — one that
    emits nothing anywhere. (NOT r112: measured against its real ledger, r112's backend made
    one hub write in the window, so this fix declines there too. See the module docstring.)"""
    now = time.time()
    _hub(tmp_path, "codehub_commits", {
        "_meta": {"version": 1},
        "c1": {"_updated_by": "frontend", "_updated_at": now - 100},   # a DIFFERENT lane
    })
    assert _driver(tmp_path)._missing_attendee_is_working_1202ko(
        {"missing": ["backend"]}, elapsed=480) is None


# --- scope ----------------------------------------------------------------------------------

def test_activity_before_this_kickoff_does_not_count(tmp_path):
    """★ The window matters: a lane that worked hard during milestone 1 and then went silent
    at the M2 kickoff is exactly what #28 must still catch."""
    now = time.time()
    _hub(tmp_path, "workhub_tasks", {
        "_meta": {},
        "t1": {"_updated_by": "frontend", "_updated_at": now - 5000},   # long before
    })
    assert _driver(tmp_path)._missing_attendee_is_working_1202ko(
        {"missing": ["frontend"]}, elapsed=480) is None


def test_nobody_missing_is_not_busy(tmp_path):
    assert _driver(tmp_path)._missing_attendee_is_working_1202ko({"missing": []}, 480) is None


def test_a_broken_hub_dir_restores_the_old_behaviour(tmp_path):
    """★ Fail-safe direction: a fault must never EXTEND a wait, only fall back to #28."""
    assert _driver(tmp_path / "nope")._missing_attendee_is_working_1202ko(
        {"missing": ["frontend"]}, 480) is None


def test_unparseable_store_is_survived(tmp_path):
    p = tmp_path / "shared" / "hubs"
    p.mkdir(parents=True)
    (p / "workhub_tasks.json").write_text("{ not json", encoding="utf-8")
    assert _driver(tmp_path)._missing_attendee_is_working_1202ko(
        {"missing": ["frontend"]}, 480) is None


# --- wiring ---------------------------------------------------------------------------------

def test_the_escape_actually_consults_it():
    """★ Reachability: the helper is inert unless the stall branch reads it. Read from the
    parse tree — the comment above the branch quotes the constant names in prose (#923)."""
    src = textwrap.dedent(inspect.getsource(KickoffDriver._drive_kickoff_to_completion))
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        g = ast.unparse(node.test)
        if "KICKOFF_INITIAL_STALL_MIN_SEC" in g and "stalled_polls" in g:
            assert "_busy_1202ko" in g, f"the stall escape ignores the busy check: {g}"
            return
    raise AssertionError("the stall escape branch is gone")


def test_only_the_fast_escape_is_declined_not_the_real_timeout():
    """★ Scope: the 1200s timeout must still bound the wait, or a genuinely wedged lane could
    hang the run forever — the very thing #28 was added to prevent."""
    src = inspect.getsource(KickoffDriver._drive_kickoff_to_completion)
    assert "KICKOFF_TIMEOUT_SEC" in src, "the real timeout must still be in force"
    i = src.index("_busy_1202ko")
    assert "KICKOFF_TIMEOUT_SEC" in src[i:i + 1600], (
        "the decline must say the real timeout still applies")
