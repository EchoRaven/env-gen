"""FIX #284 — the ui_flow_missing dispatch never NAMES the missing flows (tiktok r68, live).

r68 idled 40+ minutes on a single gate check, `deliverability_ui_flow_missing`, with the whole
rest of the run green (api_smoke 13/13, 24 chains / 166 steps, frontend audits green).

Ground truth from its hub (codehub_checks.json): only FOUR validation:ui_flow records existed
— guest_browse / guest_like_prompts_login / signup_then_like / login_persists_across_reload —
all status='failure'. The gate required `fyp_feed` and `login_modal_route`: NO record under
either name ever existed. Yet the verifier broadcast, twice:

    "both critical ui_flow records (fyp_feed, login_modal_route) are recorded status=success"
    "task_e37b62f426 was already completed on a prior wake"

Both false, and NOTHING contradicted them — the exact verifier-drift the gate's own docstring
predicts ("smoke #14: 5 declared flows, 0 records"). The remediation text could not break the
loop because it is GENERIC (#280: "RECORD each named flow (e.g. login / signup / search)") —
example names, never the flows THIS run is missing. So a drifting verifier had nothing to
contradict its own belief and answered "already done" every re-fire.

Fix: the dispatcher already injects gate-specific detail for business_chain_failing /
api_coverage / bare_authed_fetch. Add the same for ui_flow_missing — recompute the gate's own
`compute_flow_coverage(...).missing` and name those exact flows, with an explicit contradiction
notice (the record you believe you wrote does not exist; re-read the hub before claiming done).
ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import multi_agent.runtime.remediation_dispatcher as rd  # noqa: E402


def test_extra_text_names_the_flows_and_states_the_contradiction():
    txt = rd._ui_flow_missing_extra(["fyp_feed", "login_modal_route"])
    assert "fyp_feed" in txt and "login_modal_route" in txt
    low = txt.lower()
    # the anti-drift contradiction — r68's verifier claimed "already completed"
    assert ("does not exist" in low or "no passing" in low
            or "no record" in low or "does not make the record exist" in low)
    assert ("already" in low or "claim" in low or "believe" in low or "re-read" in low)


def test_no_missing_flows_yields_empty_extra():
    """Nothing missing → say nothing, so #280's generic text is left intact."""
    assert rd._ui_flow_missing_extra([]) == ""


def test_missing_names_recovered_from_flow_coverage(monkeypatch):
    """The dispatcher must re-derive the SAME missing set the gate computed, from the
    hub — not from a status string it was handed."""
    class _Report:
        missing = ["fyp_feed", "login_modal_route"]

    called = {}

    def _fake_compute(hub_registry, workspace=None):
        called["hub"] = hub_registry
        return _Report()

    monkeypatch.setattr(rd, "compute_flow_coverage", _fake_compute, raising=False)

    class _RH:
        pass

    class _WH:
        def list_documents(self, kind=None):
            return []

    class _Hubs:
        registryhub = _RH()
        workhub = _WH()

    class _Orch:
        hubs = _Hubs()

    assert rd._ui_flow_missing_names(_Orch()) == ["fyp_feed", "login_modal_route"]
    # #1203fu: the CONTAINER, not the RegistryHub. This assertion used to read
    # `called["hub"] is _Orch.hubs.registryhub` and that is how the defect survived: the
    # stand-in above accepts any object, so the test stayed green while the real
    # `compute_flow_coverage` was being handed something it rejects on its first line
    # (`workhub = getattr(hub_registry, "workhub", None); if workhub is None: return None`),
    # returning `source="none"` and an EMPTY missing list on every call in production. 0 of 26
    # `deliverability_ui_flow_missing` tasks across r14x-r16x named a single flow. Same shape
    # #1178 fixed for the sibling producer, and the same reason it was invisible.
    assert called["hub"] is _Orch.hubs
    # ... and pin what the REAL function needs, so a future stand-in cannot re-freeze the bug:
    # whatever is passed must carry `.workhub`, which a RegistryHub does not.
    assert getattr(called["hub"], "workhub", None) is not None
    from multi_agent.runtime.flow_coverage import _derive_ui_spec_from_hub as _spec
    assert _spec(_RH()) is None, "a RegistryHub alone must still be rejected upstream"


def test_missing_names_never_raises(monkeypatch):
    """Best-effort: any hub/import hiccup yields [] (falls back to #280 generic text)."""
    def _boom(*a, **k):
        raise RuntimeError("hub down")
    monkeypatch.setattr(rd, "compute_flow_coverage", _boom, raising=False)

    class _Orch:
        hubs = None
    assert rd._ui_flow_missing_names(_Orch()) == []
    assert rd._ui_flow_missing_names(object()) == []


def test_the_dispatch_branch_that_wires_this_fix_still_exists():
    """#1203rm: what THIS file actually depends on — the branch that calls the helpers.

    This test used to read

        src = Path(rd.__file__).read_text(...)
        assert "deliverability_ui_flow_missing" in src
        assert "deliverability_ui_flow_failed" in src

    and it could not fail. Those strings occur 7 and 10 times in the dispatcher, 4 and 3 of
    them on COMMENT or docstring lines — including `_ui_flow_missing_extra`'s own docstring,
    which names the gate it serves. Delete every real mapping entry and branch and the
    assertion stays green, in the guard for the check that appears in 84 corpus runs, more
    than any other.

    THE OWNER MAP IS NOT THIS FILE'S JOB. `test_280_ui_flow_failed_has_owner` already
    extracts the `_GATE_OWNER` dict literal BY AST and asserts both keys structurally, so
    re-asserting it here would duplicate an invariant that has a real owner. What this file
    needs is the WIRING: a branch keyed on the gate name that calls `_ui_flow_missing_names`,
    because every other test here drives the two helpers directly and none of them would
    notice if nothing called them.
    """
    import ast as _ast
    tree = _ast.parse(Path(rd.__file__).read_text(encoding="utf-8"))
    wired = []
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.If):
            continue
        test = node.test
        if not (isinstance(test, _ast.Compare)
                and isinstance(test.left, _ast.Name) and test.left.id == "name"
                and len(test.comparators) == 1
                and isinstance(test.comparators[0], _ast.Constant)
                and test.comparators[0].value == "deliverability_ui_flow_missing"):
            continue
        called = {c.func.id for c in _ast.walk(node)
                  if isinstance(c, _ast.Call) and isinstance(c.func, _ast.Name)}
        wired.append(called)
    assert wired, (
        "no `if name == \"deliverability_ui_flow_missing\":` branch in the dispatcher, so "
        "#284's specific text is computed by nothing — the generic #280 body that let r68 "
        "idle 40 minutes is what the verifier would receive")
    assert any("_ui_flow_missing_names" in c for c in wired), (
        "the branch exists but never calls `_ui_flow_missing_names`, so the flow names this "
        "file's other tests verify are never derived: %r" % (wired,))
