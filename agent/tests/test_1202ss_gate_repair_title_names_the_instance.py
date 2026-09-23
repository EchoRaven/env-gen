r"""#1202ss: a delivery-gate repair task must name the failing INSTANCE in its TITLE.

Measured over the 36 corpus runs since `#1202gz` collapsed same-title remediation (the
count is how many DISTINCT instances shipped under one title, i.e. how many the lane
never saw in a listing):

    126 hidden / 22 runs   Make business_chain pass (blocks delivery)
    115 hidden / 12 runs   Fix breaking change in GET /api/videos     ← `#1202sr`
     88 hidden / 17 runs   Test-user found UI defects (browser walkthrough) — fix
     53 hidden / 20 runs   Re-verify the failing UI evidence records (blocks delivery)

Every branch of `dispatch_gate_level_checks` already computes WHICH chain / page / flow /
endpoint failed and puts it in the task BODY. `#1202sr` fixed one title by hand; this fixes
the class at the single site that files the task, so a check nobody has hit yet is covered.

Two invariants the fix must not break, both verified below:
  * the base title stays a PREFIX — `_gate_still_fails_on_1202pg` (workhub/service.py)
    matches `"(blocks delivery)" in title and "business_chain" in title` by SUBSTRING;
  * `#794`'s open-task lookup must survive an instance set that CHANGES between
    re-dispatches, or the fix re-creates r130's 13 clones of one problem by another route.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import ast
import asyncio
import inspect
import logging
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime import remediation_dispatcher as rd  # noqa: E402
from multi_agent.runtime.remediation_dispatcher import RemediationDispatcher  # noqa: E402

_BASE = "Make business_chain pass (blocks delivery)"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


class _FakeWorkHub:
    def __init__(self, open_tasks=None):
        self.tasks = []
        self._open = list(open_tasks or [])

    def list_tasks(self):
        return list(self._open)

    def create_task(self, **kw):
        self.tasks.append(kw)
        return {"id": f"task_{len(self.tasks)}"}


class _FakeBus:
    def __init__(self):
        self.sent = []

    async def send(self, msg):
        self.sent.append(msg)


class _FakeRegistryHub:
    def __init__(self, chains):
        self._chains = chains

    def get_verification_chains(self):
        return self._chains


def _chains(*names):
    out = {"_meta": {"version": 3}}
    for n in names:
        out[n] = {
            "name": n, "kind": "flow", "status": "failing",
            "steps": [{"method": "GET", "path": "/api/videos/v1/comments"}],
            "last_result": {"broken": [], "steps": [
                {"action": "/api/videos/v1/comments", "method": "GET",
                 "path": "/api/videos/v1/comments", "status": 422,
                 "expect": [200], "ok": False},
            ]},
        }
    return out


def _stub(chains, open_tasks=None, milestone="1.2.0"):
    hubs = types.SimpleNamespace(workhub=_FakeWorkHub(open_tasks),
                                 registryhub=_FakeRegistryHub(chains))
    return types.SimpleNamespace(
        hubs=hubs, message_bus=_FakeBus(),
        _logger=logging.getLogger("test_1202ss"),
        _current_milestone_version=milestone,
    )


# --- the head extractor -------------------------------------------------------------

def test_the_chain_name_is_the_head_of_a_broken_step_line():
    line = ("browse_for_you_logged_out -> step '/api/videos/videos-d1-4/comments': "
            "GET /api/videos/videos-d1-4/comments returned 422, expected [200]")
    assert rd._instance_name_1202ss(line) == "browse_for_you_logged_out"


def test_a_plain_name_and_an_endpoint_pass_through():
    assert rd._instance_name_1202ss("login_page") == "login_page"
    assert rd._instance_name_1202ss("GET /api/videos") == "GET /api/videos"


def test_prose_is_refused_so_the_title_stays_generic():
    """A title reading `Make business_chain pass: frontend calls an authed API via` is
    WORSE than the generic one. `deliverability_bare_authed_fetch`'s detail lines are whole
    sentences, and `#983`'s generic prose replay can carry any shape at all."""
    assert rd._instance_name_1202ss(
        "frontend calls an authed API via bare unauthenticated fetch(): "
        "app/frontend/src/pages/Feed.jsx:42 fetches '/api/videos' with no header") == ""
    assert rd._instance_name_1202ss(
        "critical UI flow(s) failed: the walkthrough could not reach the page") == ""


def test_the_continuation_line_is_not_an_instance():
    """`#811` appends a "… and N more" row to the same list the title reads."""
    assert rd._instance_name_1202ss(
        "… and 4 more broken step(s) — the same reading applies to each") == ""
    assert rd._instance_name_1202ss("") == ""
    assert rd._instance_name_1202ss(None) == ""


# --- the title builder --------------------------------------------------------------

def test_the_base_title_is_kept_as_a_prefix():
    got = rd._instanced_gate_title_1202ss(_BASE, ["chain_a", "chain_b"])
    assert got.startswith(_BASE), (
        "_gate_still_fails_on_1202pg matches this title by substring and #794 by prefix")
    assert "chain_a, chain_b" in got


def test_nothing_recognisable_leaves_the_title_untouched():
    assert rd._instanced_gate_title_1202ss(_BASE, []) == _BASE
    assert rd._instanced_gate_title_1202ss(_BASE, None) == _BASE
    assert rd._instanced_gate_title_1202ss(_BASE, ["a whole sentence of prose here ok"]) == _BASE


def test_the_cap_declares_what_it_hid():
    """#1034: a count and the list it summarises must agree — a silently truncated title is
    the same defect one layer down from the one this fix is closing."""
    got = rd._instanced_gate_title_1202ss(_BASE, ["c1", "c2", "c3", "c4", "c5"])
    assert "c1, c2, c3" in got and "c4" not in got
    assert "(+2 more not shown)" in got


def test_duplicate_instances_are_named_once():
    got = rd._instanced_gate_title_1202ss(_BASE, ["c1", "c1", "c2"])
    assert got.count("c1") == 1 and "more not shown" not in got


# --- end to end through the dispatcher ----------------------------------------------

def test_a_filed_business_chain_task_names_its_chains():
    orch = _stub(_chains("browse_for_you_logged_out", "comment_round_trip"))
    _run(RemediationDispatcher(orch).dispatch_gate_level_checks(["business_chain_failing"]))
    assert len(orch.hubs.workhub.tasks) == 1
    title = orch.hubs.workhub.tasks[0]["title"]
    assert title.startswith(_BASE)
    assert "browse_for_you_logged_out" in title and "comment_round_trip" in title, title


def test_a_redispatch_whose_instances_changed_rewakes_the_open_task():
    """The riskiest way this fix could go wrong: a title that varies per tick would defeat
    `#794` and re-create r130's 13 simultaneous copies of one problem."""
    open_task = {"id": "task_old", "status": "in_progress",
                 "title": _BASE + ": browse_for_you_logged_out"}
    orch = _stub(_chains("comment_round_trip"), open_tasks=[open_task])
    _run(RemediationDispatcher(orch).dispatch_gate_level_checks(["business_chain_failing"]))
    assert orch.hubs.workhub.tasks == [], "an open twin must be re-woken, not cloned (#794)"
    assert orch.message_bus.sent
    assert "task_old" in orch.message_bus.sent[0].payload


def test_a_completed_twin_still_lets_the_check_refile():
    orch = _stub(_chains("comment_round_trip"),
                 open_tasks=[{"id": "task_old", "status": "completed", "title": _BASE}])
    _run(RemediationDispatcher(orch).dispatch_gate_level_checks(["business_chain_failing"]))
    assert len(orch.hubs.workhub.tasks) == 1


# --- the invariant the prefix lookup rests on ---------------------------------------

def test_no_gate_owner_title_is_a_prefix_of_another():
    """#794 now matches an open task by PREFIX. If one row's title were a prefix of
    another's, a still-open task for check A would suppress the P0 for check B."""
    tree = ast.parse(inspect.getsource(rd))
    titles = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "_GATE_OWNER" for t in node.targets):
            for value in node.value.values:
                titles.append(ast.literal_eval(value)[1])
    assert len(titles) > 20, "the dispatch table was not found — re-anchor this test"
    collisions = [(a, b) for a in titles for b in titles if a != b and b.startswith(a)]
    assert collisions == [], collisions


# --- #1202st: the same class in the test-user walkthrough task ----------------------

_TU_BASE = "Test-user found UI defects (browser walkthrough) — fix"


def _heal_tree():
    from multi_agent.runtime import heal_pipeline
    return ast.parse(inspect.getsource(heal_pipeline)), heal_pipeline


def _tu_create_call():
    """The `create_task` call that files the test-user defect P0, found by PARSING rather
    than by a source window (#943)."""
    tree, _ = _heal_tree()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "create_task"):
            continue
        src = ast.dump(node)
        if _TU_BASE in src:
            return node
    raise AssertionError("the test-user defect task site was not found — re-anchor")


def test_the_test_user_defect_title_is_built_not_literal():
    call = _tu_create_call()
    title = [k.value for k in call.keywords if k.arg == "title"]
    assert title and isinstance(title[0], ast.Call), (
        "the title must be built from the failing pages (#1202st), not a bare literal")
    assert getattr(title[0].func, "id", "") == "_instanced_gate_title_1202ss"
    assert ast.literal_eval(title[0].args[0]) == _TU_BASE, (
        "the base title stays the PREFIX so any substring reader keeps matching")


def test_the_report_keys_the_title_reads_are_keys_the_report_really_has():
    """My most-repeated defect class: a fix that reads something the real object does not
    have, with the miss swallowed. Every key below must be ASSIGNED by the producer."""
    from multi_agent.runtime import test_user_runner
    produced = inspect.getsource(test_user_runner)
    for key in ("blank_pages", "error_pages", "auth_redirect_pages",
                "visual_mismatches", "fake_map_pages", "auth_ok"):
        assert f'report["{key}"]' in produced, (
            f"#1202st reads report[{key!r}], which test_user_runner never writes")


def test_the_pages_it_reads_are_plain_names():
    """`_instance_name_1202ss` refuses anything that is not name-shaped, so a producer that
    started emitting dicts would silently blank the title rather than corrupt it — but the
    contract is plain names, and the producer builds them as `p["name"]`."""
    from multi_agent.runtime import test_user_runner
    produced = inspect.getsource(test_user_runner)
    assert 'blanks = [p["name"] for p in pages if p.get("blank")]' in produced
    assert rd._instanced_gate_title_1202ss(_TU_BASE, ["home_page", "profile_page"]) == (
        _TU_BASE + ": home_page, profile_page")
