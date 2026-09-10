"""#1202kk: delivery blocked forever, and the fix-it message went to a page name.

tiktok-r114, live. Two P0 tasks sat `status: failed`, and they were the run's ONLY remaining
delivery blocker (`unresolved_failed_tasks`; 150 of its 160 tasks had completed):

    id          task_fa25c950f3
    assignee    frontend
    claimed_by  backend                         (misclaimed)
    created_by  browser_test_user_10_page_profile_own_pag
    fail_reason "Misclaimed by backend although assignee/root cause is frontend ...
                 close this misclaimed instance and continue through frontend-owned tasks."

`#1128` routes the re-wake by AUTHORITY, which is right: `complete_task` needs
`claimed_by == agent` and `cancel_task` needs creator-or-orchestrator, so telling the assignee
to do either would be refused by both guards. For this task it computes

    can_complete = (assignee == claimed_by) = frontend == backend  -> False
    can_cancel   = (assignee == created_by) or assignee == orchestrator -> False

and falls through to `created_by or "orchestrator"` — i.e. to
`browser_test_user_10_page_profile_own_pag`, a synthetic per-page test actor. The URGENT
message is then `_create_message(target_agent_id=<that>)` and lands in a dead inbox. Nobody can
resolve the task, and `unresolved_failed_tasks` blocks the cut for the rest of the run.

The framework already names this exact failure mode elsewhere. `registryhub.request_review`
refuses a reviewer that is not currently running because "the review request lands in a dead
inbox and nobody will action it", and it decides that from `_live_agents_provider` — the
orchestrator's own roster. This uses the same source.

The answer is in `#1128`'s own docstring: `cancel_task` is granted to the creator **or the
orchestrator (unconditionally)**, and `#1127` made `failed` cancellable. So when the recorded
owner is not a running agent, the orchestrator is not a fallback — it is the only agent with
the authority, and the message has to go there.

Measured over the 153 runs with a task ledger: 41 failed tasks, of which 2 route to a
non-agent — both in r114, both live blockers while this was written. Small, and total where it
lands: there is no second escape.

WHAT IS VERIFIED: an owner that is not in the live roster becomes `orchestrator`; every
routing #1128 already got right is unchanged; and an absent roster leaves the old behaviour
exactly, so nothing depends on the provider being attached.

WHAT IS NOT: that r114 would have delivered. It clears one blocker; the visual gate is
separate and was still failing at 0.14.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
_LLM = _AGENT / "env_generator" / "llm_generator"
for _p in (str(_LLM), str(_AGENT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import inspect                                                        # noqa: E402

from multi_agent.runtime.remediation_dispatcher import (              # noqa: E402
    failed_task_owner_1128,
)

LANES = ["orchestrator", "backend", "frontend", "verifier", "debugger"]

# r114's record, verbatim in the fields that decide the routing.
R114 = {
    "id": "task_fa25c950f3",
    "assignee": "frontend",
    "claimed_by": "backend",
    "created_by": "browser_test_user_10_page_profile_own_pag",
    "status": "failed",
}


def test_r114s_task_no_longer_routes_to_a_page_name():
    """★ The case."""
    assert failed_task_owner_1128(R114, live_agents=LANES) == "orchestrator"


def test_without_the_roster_the_old_answer_is_unchanged():
    """★ Fail-safe: nothing may depend on the provider being attached. Every existing caller
    and every pre-#1202kk test passes no roster."""
    assert failed_task_owner_1128(R114) == "browser_test_user_10_page_profile_own_pag"


def test_an_empty_roster_is_treated_as_no_roster():
    """A provider that returns [] means "not known", not "no agent exists" — the same reading
    `request_review` takes (`if live is not None and live:`)."""
    assert failed_task_owner_1128(R114, live_agents=[]) == (
        "browser_test_user_10_page_profile_own_pag")


def test_a_real_creator_is_still_the_owner():
    """★ Scope. #1128's routing is right whenever the recorded owner can actually act."""
    t = dict(R114, created_by="verifier")
    assert failed_task_owner_1128(t, live_agents=LANES) == "verifier"


def test_the_claimer_who_can_complete_is_still_the_owner():
    """Non-regression: assignee == claimed_by means `complete_task` will accept it."""
    t = {"assignee": "backend", "claimed_by": "backend", "created_by": "orchestrator"}
    assert failed_task_owner_1128(t, live_agents=LANES) == "backend"


def test_the_creator_assignee_who_can_cancel_is_still_the_owner():
    t = {"assignee": "verifier", "claimed_by": "backend", "created_by": "verifier"}
    assert failed_task_owner_1128(t, live_agents=LANES) == "verifier"


def test_an_unknowable_record_still_keeps_its_assignee():
    """Pre-#1128 ledgers carry neither claimed_by nor created_by."""
    t = {"assignee": "frontend"}
    assert failed_task_owner_1128(t, live_agents=LANES) == "frontend"


def test_an_assignee_that_is_not_running_also_goes_to_the_orchestrator():
    """★ The same dead-inbox rule, on the other branch. An `unknowable` record whose assignee
    has since exited would otherwise be told to fix it — and #1128 returns the assignee there
    without any authority check at all."""
    t = {"assignee": "database_worker"}          # not in LANES
    assert failed_task_owner_1128(t, live_agents=LANES) == "orchestrator"


def test_the_dispatcher_passes_the_live_roster():
    """★ Reachability, not presence: the parameter is inert unless the call site fills it."""
    import ast
    import textwrap
    from multi_agent.runtime import remediation_dispatcher as RD
    # Read the CALL out of the parse tree. Slicing to the next `)` — which is what the first
    # draft did — ends on a bare delimiter, so any argument that gains nesting moves the end;
    # the #923 ratchet caught it in the full suite, having passed every targeted run.
    src = textwrap.dedent(
        inspect.getsource(RD.RemediationDispatcher.dispatch_gate_level_checks))
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "failed_task_owner_1128"]
    assert calls, "the dispatcher no longer routes failed tasks through #1128 at all"
    for c in calls:
        assert any(kw.arg == "live_agents" for kw in c.keywords), (
            "the call site must hand it the roster, or the parameter is inert")


def test_the_orchestrator_can_actually_cancel_a_failed_task():
    """★ The premise, checked against the real guard rather than assumed — routing to an agent
    that would also be refused is the very defect being fixed.

    `cancel_task` allows creator-or-orchestrator, and #1127 removed `failed` from the terminal
    states it refuses."""
    from multi_agent.runtime.hubs.workhub import service as WH
    src = inspect.getsource(WH.WorkHub.cancel_task)
    assert 'if task.get("status") in {"completed", "cancelled"}:' in src, (
        "#1127: `failed` must stay cancellable")
    assert 'agent not in ("orchestrator", creator)' in src, (
        "the orchestrator must retain unconditional cancel authority")
