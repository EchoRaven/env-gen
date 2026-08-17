"""#417 (2026-08-02, live r13 diagnosis): the visual-fidelity gate judged the app
BEFORE the frontend was wired. api_smoke (which triggers the gate via
framework_validation) probes the BACKEND only, so it goes green while declared
ui_pages are still unwired — their routes fall through App.jsx's `*` catch-all and
render a redirect/404 (a NON-blank page, so the existing capture_transient refund
misses it). r13 judged 12 screens at 18:22 (player.png 9.7KB, my_list.png 14KB —
empty), scored them 0.00-0.35, filed a misleading "UI doesn't match" P1, and
BURNED its one real per-source attempt; the frontend didn't wire App.jsx until
18:51 (24min later) and the projector's REAL output was never judged (the run
delivered below-threshold). FIX: maybe_run() skips (no attempt spent, no verdict,
no remediation) while _frontend_wiring_blockers() is non-empty — reusing the
delivery gate's OWN single-source ui_page_delivery_blockers check — so the FIRST
judgment lands on the WIRED app. This locks that precondition in.

Isolation harness mirrors test_visual_coverage_routed_screens.py: visual_fidelity's
only unconditional sibling import is `from .validation_runner import
_service_host_port` — stub it, then exec the module under a synthetic package."""
import asyncio
import sys
import types
from pathlib import Path

_SRC = (Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
        / "multi_agent" / "runtime" / "visual_fidelity.py")


def _load():
    pkg = types.ModuleType("vf_pkg")
    pkg.__path__ = []
    vr = types.ModuleType("vf_pkg.validation_runner")
    vr._service_host_port = lambda *a, **k: None
    sys.modules["vf_pkg"] = pkg
    sys.modules["vf_pkg.validation_runner"] = vr
    # #898: `visual_fidelity` derives its ceilings via `stage_contract.llm_ceiling_898`, imported
    # inside the accessor. This harness hand-stubs each module the source reaches, so a new one
    # must be added here too — the same contract `validation_runner` above is satisfying.
    import env_generator.llm_generator.multi_agent.runtime.stage_contract as _sc
    sys.modules["vf_pkg.stage_contract"] = _sc
    mod = types.ModuleType("vf_pkg.visual_fidelity")
    mod.__package__ = "vf_pkg"
    exec(compile(_SRC.read_text(encoding="utf-8"), str(_SRC), "exec"), mod.__dict__)
    return mod


VF = _load()


class _Logger:
    def warning(self, *a, **k):
        pass

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass


class _Orch:
    def __init__(self, tmp):
        self._reference_images = ["/ref/a.jpg"]
        self.output_dir = tmp
        self.llm = object()
        self._logger = _Logger()
        self._sig = "sig1"

    def _compute_app_source_signature(self):
        return self._sig


def _judged_result():
    return {"passed": True, "summary": "ok",
            "screens": [{"name": "browse", "similarity": 0.9, "advisory": False}]}


def _gate_with_fake_judge(tmp_path):
    """A gate whose run_visual_fidelity is a call-counting async stub."""
    orch = _Orch(tmp_path)
    gate = VF.VisualFidelityGate(orch)
    calls = {"n": 0}

    async def _fake_run(*a, **k):
        calls["n"] += 1
        return _judged_result()

    VF.run_visual_fidelity = _fake_run
    return gate, calls


def test_skips_judge_while_frontend_unwired(tmp_path):
    gate, calls = _gate_with_fake_judge(tmp_path)
    gate._frontend_wiring_blockers = lambda: [
        "ui_page `landing` declared but unusable: route `/` not wired in App.jsx"]
    asyncio.run(gate.maybe_run())
    assert calls["n"] == 0, "must NOT judge a pre-wiring app"
    assert gate.attempts == 0, "unwired skip must NOT burn a per-source attempt"
    assert gate.passed is False
    assert gate.total_judgments == 0, "no verdict recorded for an unwired skip"
    assert gate.last_judged_sig is None, "sig not latched → re-evaluated once wired"


def test_judges_once_frontend_is_wired(tmp_path):
    gate, calls = _gate_with_fake_judge(tmp_path)
    gate._frontend_wiring_blockers = lambda: []   # fully wired
    asyncio.run(gate.maybe_run())
    assert calls["n"] == 1, "a wired app MUST be judged"
    assert gate.attempts == 1
    assert gate.passed is True


def test_unwired_then_wired_first_verdict_is_on_wired_app(tmp_path):
    """The exact r13 sequence: an early (unwired) tick must not consume the budget,
    so the FIRST real verdict is the wired app — not the blank pre-wiring one."""
    gate, calls = _gate_with_fake_judge(tmp_path)
    unwired = {"v": True}
    gate._frontend_wiring_blockers = lambda: (
        ["route `/` not wired in App.jsx"] if unwired["v"] else [])
    # tick 1: api_smoke green but frontend unwired → skip
    asyncio.run(gate.maybe_run())
    assert calls["n"] == 0 and gate.attempts == 0
    # frontend lane wires the pages; a later tick judges the WIRED app
    unwired["v"] = False
    asyncio.run(gate.maybe_run())
    assert calls["n"] == 1, "first real judgment is on the wired app"
    assert gate.attempts == 1


def test_wiring_blockers_best_effort_empty(tmp_path):
    """_frontend_wiring_blockers never raises into the gate: missing output_dir /
    workhub / a frontend_audit hiccup all yield [] (judge proceeds, never wedged)."""
    orch = _Orch(tmp_path)
    orch.output_dir = None
    gate = VF.VisualFidelityGate(orch)
    assert gate._frontend_wiring_blockers() == []

    orch2 = _Orch(tmp_path)
    orch2.hubs = types.SimpleNamespace(workhub=None)
    gate2 = VF.VisualFidelityGate(orch2)
    assert gate2._frontend_wiring_blockers() == []


def test_wiring_blockers_delegates_to_delivery_check(tmp_path):
    """When output_dir + workhub exist, the check delegates to the delivery gate's
    OWN ui_page_delivery_blockers (single-source), passing the frontend/src path."""
    seen = {}

    fa = types.ModuleType("vf_pkg.frontend_audit")

    def _blockers(src, workhub):
        seen["src"] = str(src)
        seen["workhub"] = workhub
        return ["ui_page `x` unwired"]

    fa.ui_page_delivery_blockers = _blockers
    sys.modules["vf_pkg.frontend_audit"] = fa
    try:
        (tmp_path / "app" / "frontend" / "src").mkdir(parents=True, exist_ok=True)
        orch = _Orch(tmp_path)
        orch.hubs = types.SimpleNamespace(workhub="WH")
        gate = VF.VisualFidelityGate(orch)
        out = gate._frontend_wiring_blockers()
        assert out == ["ui_page `x` unwired"]
        assert seen["workhub"] == "WH"
        assert seen["src"].endswith("app/frontend/src")
    finally:
        sys.modules.pop("vf_pkg.frontend_audit", None)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
