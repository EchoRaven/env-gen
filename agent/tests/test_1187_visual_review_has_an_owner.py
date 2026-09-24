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
import inspect
import re

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
