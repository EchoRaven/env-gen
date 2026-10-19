"""#1187 — a gate check that blocks delivery and had nobody to dispatch to.

`deliverability_critical_visuals_pending` declined a delivery alongside three other checks,
and the very next line of that run's log read:

    Delivery declined on gate check(s) with NO remediation owner (needs a fix at source or
    an owner mapping): ['deliverability_critical_visuals_pending']

That is #1040's shape, one check to the side. `_visual_summary` counts ui_page records whose
status is `pending`/`reviewing`, and the gate blocks on that when the UI is not otherwise
validated. `submit_visual_review` is locked to the verifier, so the verifier is the only
agent who could ever move one — which is precisely why a missing owner left it unmovable.

A sweep of every check the gate can emit, ranked by how often it has actually blocked a real
run, found this was the only ownerless one that has ever blocked. `deliverability_dead_
artifacts` looked like a second until the logs showed it dispatching to backend through the
generic path ("GATE-CHECK remediation dispatched to backend (task task_f63393e076)").
"""
import asyncio
import ast
import inspect
import re
import types

from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as rd

_SRC = inspect.getsource(rd)
# Anchor on the ASSIGNMENT, not on any mention: `_COVERED_ELSEWHERE` also appears inside
# a comment INSIDE the owner table, and slicing on the first occurrence cut the table off
# mid-entry — which read as "deliverability_ui_flow_missing has no owner" when it has one.
_OWNER_BLOCK = _SRC[_SRC.index("_GATE_OWNER = {"):_SRC.index("_COVERED_ELSEWHERE = {")]


def _entry(name):
    """The entry text from its key to the next key (or the end) — comments and all.

    Not `index("),")`: several entries carry multi-line comments containing parentheses,
    and slicing on the first `),` cut some of them mid-comment and raised.
    """
    i = _OWNER_BLOCK.index(f'"{name}": (')
    nxt = re.search(r'\n\s+"[a-z0-9_]+":\s*\(', _OWNER_BLOCK[i + 8:])
    return _OWNER_BLOCK[i:i + 8 + nxt.start()] if nxt else _OWNER_BLOCK[i:]


def _owner_of(name):
    """The lane string: the first bare "lane", that follows the key, past any comments."""
    m = re.search(r'"([a-z_]+)",\s*"', _entry(name))
    return m.group(1) if m else None


def test_the_check_has_an_owner_now():
    assert '"deliverability_critical_visuals_pending": (' in _OWNER_BLOCK


def test_it_is_owned_by_the_only_agent_that_can_clear_it():
    """submit_visual_review is verifier-locked; any other owner is told to do the impossible."""
    assert _owner_of("deliverability_critical_visuals_pending") == "verifier"


def test_the_body_names_the_tool_and_both_readings():
    entry = _entry("deliverability_critical_visuals_pending")
    assert "submit_visual_review" in entry
    assert "approved" in entry and "needs_revision" in entry
    # #958's measurement: a nonzero pending usually means a mis-registered page kind.
    assert "kind='visual_review'" in entry, "the second reading must be offered"


def test_every_owner_entry_names_a_real_lane():
    """A typo'd owner is the same dead end as no owner at all."""
    lanes = {"backend", "frontend", "verifier", "debugger", "orchestrator", "design"}
    names = re.findall(r'\n\s+"([a-z0-9_]+)":\s*\(', _OWNER_BLOCK)
    assert len(names) >= 16, f"expected the owner table, found {len(names)} entries"
    for name in names:
        assert _owner_of(name) in lanes, f"{name} -> {_owner_of(name)}"


# --- #1203pg: every owner in the table actually FILES, driven ------------------------------------
#
# The assertions above read the owner table out of the source and check the mapping. That is the
# right half for "is there an owner", and it is the half #1040/#1187 were about -- but it cannot
# see whether the dispatcher acts on the entry. #1139/#1148 is the standing lesson here: putting
# evidence in a table is one half, and a consumer reading it is the other, and #1203pd was a
# live instance earlier this session (a detector that warned, recorded, and had no dispatcher).
#
# MEASURED when this landed: all 40 entries file exactly one task, to the lane the table names.
# So this is a guard over a clean state, not a bug report -- and it is the cheapest possible
# guard for a class that has already gone wrong twice.

def _owner_table_names():
    """Every check name in the dispatcher's owner table, from the parse tree."""
    tree = ast.parse(inspect.getsource(
        rd.RemediationDispatcher.dispatch_gate_level_checks).lstrip())
    for n in ast.walk(tree):
        if not isinstance(n, ast.Dict):
            continue
        keys = [k.value for k in n.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        if len(keys) >= 10 and n.values and all(isinstance(v, ast.Tuple) for v in n.values):
            return keys
    raise AssertionError("the owner table moved; re-aim this test")


def _dispatch_one(check):
    """Run the gate-level dispatch for one check against a stub orchestrator."""
    _noop = lambda *a, **k: None  # noqa: E731

    class _WH:
        def __init__(self):
            self.created = []

        def list_tasks(self):
            return []

        def create_task(self, **kw):
            self.created.append(kw)
            return {"id": "t%d" % len(self.created)}

    class _Bus:
        async def send(self, *a, **k):
            return None

    wh = _WH()
    orch = types.SimpleNamespace(
        hubs=types.SimpleNamespace(workhub=wh, codehub=None, eventhub=None),
        _logger=types.SimpleNamespace(info=_noop, warning=_noop, error=_noop, debug=_noop),
        message_bus=_Bus(), output_dir=".", agents={}, _milestone_index=1,
        _gate_dispatch_guard={}, _gate_decline_counts={})
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(
            rd.RemediationDispatcher(orch).dispatch_gate_level_checks([check]))
    finally:
        loop.close()
    return wh.created


def test_the_table_is_not_empty():
    """Non-vacuity: an empty table would make the sweep below pass trivially."""
    assert len(_owner_table_names()) >= 16


def test_every_owned_check_files_exactly_one_task_to_its_named_lane():
    """The other half of "it has an owner": the owner has to be handed the work.

    One test over the whole table rather than one per entry, so a new check added to the table
    is covered the day it lands.
    """
    wrong = []
    for check in _owner_table_names():
        try:
            created = _dispatch_one(check)
        except Exception as exc:                 # a dispatch must never raise
            wrong.append((check, "raised %s: %s" % (type(exc).__name__, exc)))
            continue
        if len(created) != 1:
            wrong.append((check, "filed %d tasks" % len(created)))
            continue
        want = _owner_of(check)
        got = created[0].get("assignee")
        if got != want:
            wrong.append((check, "table says %s, task went to %s" % (want, got)))
    assert not wrong, "owned gate checks that do not reach their lane: %s" % wrong


def test_the_1187_check_reaches_the_verifier_specifically():
    """The ticket's own case, driven rather than read off the table."""
    created = _dispatch_one("deliverability_critical_visuals_pending")
    assert len(created) == 1
    assert created[0]["assignee"] == "verifier"
    assert created[0].get("priority") == "P0"
    assert "visual review" in created[0]["title"].lower()
