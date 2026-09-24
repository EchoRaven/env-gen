"""#280 — deliverability_ui_flow_failed must have a remediation owner.

r63 (opus-4.7, all fixes): backend healthy, everything green except the FYP feed ui_flow,
which failed because the SPA crashed post-login with '(void 0) is not a function' — a genuine
frontend runtime bug. The gate declined delivery AND logged "NO remediation owner (needs a fix
at source or an owner mapping): ['deliverability_ui_flow_failed']".

The dispatcher's _GATE_OWNER map has an entry for deliverability_ui_flow_MISSING (a flow with
no validation record) but NONE for deliverability_ui_flow_FAILED (a flow that ran and failed).
So a flow that is merely unrecorded gets an owner and a flow that genuinely BROKE does not —
exactly backwards. With no owner, the gate dead-ends: it blocks delivery forever while a lane
that could fix the crash is never told. Env-agnostic; any run whose delivered app has a broken
critical flow hits it.

The verifier owns ui_flow (it runs the browser walk and records the results); on a failure it
locates the crash and bug_creates for the owning lane (usually frontend), mirroring the
ui_flow_missing entry's own guidance ("if a flow FAILS, bug_create for the owning lane").
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _gate_owner_map():
    """Extract the _GATE_OWNER dict literal from the dispatcher source (it is defined inside
    a method, so read it statically rather than import a live orchestrator)."""
    import ast
    src = (ROOT / "env_generator/llm_generator/multi_agent/runtime"
           / "remediation_dispatcher.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and node.targets
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "_GATE_OWNER"
                and isinstance(node.value, ast.Dict)):
            keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
            return keys
    return []


def test_ui_flow_failed_is_in_the_owner_map():
    keys = _gate_owner_map()
    assert "deliverability_ui_flow_failed" in keys, (
        "a FAILED critical flow has no remediation owner — the r63 dead-end. "
        f"map keys: {sorted(keys)}")


def test_ui_flow_missing_still_has_its_owner():
    """The pre-existing entry must remain — we ADD, not replace."""
    assert "deliverability_ui_flow_missing" in _gate_owner_map()


def test_ui_flow_failed_owner_spec_is_well_formed():
    """The spec tuple must be (owner, title, detail) with a real lane owner."""
    import ast
    src = (ROOT / "env_generator/llm_generator/multi_agent/runtime"
           / "remediation_dispatcher.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and node.targets
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "_GATE_OWNER"
                and isinstance(node.value, ast.Dict)):
            for k, v in zip(node.value.keys, node.value.values):
                if getattr(k, "value", None) == "deliverability_ui_flow_failed":
                    assert isinstance(v, ast.Tuple) and len(v.elts) == 3, "spec must be a 3-tuple"
                    owner = v.elts[0].value
                    assert owner in ("frontend", "verifier"), owner
                    return
    raise AssertionError("deliverability_ui_flow_failed entry not found")
