"""#1202od: a step whose request never reached the app is not a broken endpoint.

tiktok-r124: 50 chains / 121 steps recorded as failing business_chain, every one
`POST /auth/register → None (ConnectionResetError: [Errno 104])`. The app was fine; the stack
was mid-recycle. Across the corpus 121 of 501 broken steps (24%) are transport errors, 114 of
them in the last three days. A lane dispatched at those is chasing a socket.

#272 already carved `framework_defect` out of `broken` for the same reason — not the lane's to
fix, so not `broken`. This carves out the environment, and the three readers that turn a chain
result into a verdict all honour it: the gate check says NOT VERIFIED (never a pass), and
neither writer flips the stored status.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import chain_executor as CE  # noqa: E402
from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def test_a_transport_error_is_recognised_and_an_answer_is_not():
    assert CE.is_transport_failure_1202od(
        {"status": None, "error": "ConnectionResetError: [Errno 104] Connection reset by peer"})
    assert CE.is_transport_failure_1202od({"status": None, "error": "<urlopen error [Errno 111] Connection refused>"})
    assert CE.is_transport_failure_1202od({"status": None, "error": "read timed out"})
    # an app that ANSWERED is never environment, whatever the body says
    assert not CE.is_transport_failure_1202od({"status": 500, "error": "Connection reset by peer"})
    assert not CE.is_transport_failure_1202od({"status": None, "error": "unresolved ${tenantId}"})
    assert not CE.is_transport_failure_1202od({})


def test_the_chain_report_keeps_it_out_of_broken(monkeypatch):
    monkeypatch.setattr(CE, "_http", lambda *a, **k: {
        "status": None, "error": "ConnectionResetError: [Errno 104] Connection reset by peer"})
    out = CE.execute_chain("http://127.0.0.1:1", {
        "name": "auth_roundtrip",
        "steps": [{"method": "POST", "path": "/auth/register",
                   "body": {"email": "a@b.c"}, "expect": [200, 201, 409]}]})
    assert out["broken"] == []
    assert len(out["environment_1202od"]) == 1
    assert "/auth/register" in out["environment_1202od"][0]


def test_a_real_failure_still_breaks_the_chain(monkeypatch):
    monkeypatch.setattr(CE, "_http", lambda *a, **k: {
        "status": 500, "body_text": '{"detail":"create failed"}'})
    out = CE.execute_chain("http://127.0.0.1:1", {
        "name": "auth_roundtrip",
        "steps": [{"method": "POST", "path": "/auth/register", "expect": [200, 201]}]})
    assert out["environment_1202od"] == []
    assert len(out["broken"]) == 1


def test_an_unreachable_run_does_not_flip_a_stored_verdict(tmp_path):
    hr = HubRegistry(tmp_path)
    rh = hr.registryhub
    for m, p in (("POST", "/auth/register"), ("GET", "/api/items")):
        rh.register_endpoint(m, p, agent="backend", status="implemented")
    rh.register_verification_chain("flow", steps=[
        {"method": "GET", "path": "/api/items", "expect": [200]}], agent="verifier")
    rh.record_chain_result("flow", {"broken": ["GET /api/items → 500"]}, agent="")
    assert rh.get_verification_chains()["flow"]["status"] == "failing"
    out = rh.record_chain_result("flow", {
        "broken": [], "environment_1202od": ["GET /api/items → None (ConnectionResetError)"]},
        agent="")
    assert rh.get_verification_chains()["flow"]["status"] == "failing"   # not flipped to passing
    assert out.get("environment_blocked_1202od") == 1


def test_the_gate_check_says_not_verified_instead_of_passing():
    import inspect
    from multi_agent.runtime import validation_runner as VR
    src = inspect.getsource(VR.run_smoke_validation)
    i = src.index('_add("business_chain", True')
    guard = src[src.index('elif _chain.get("environment_1202od")'):i]
    assert "NOT VERIFIED" in guard and '"business_chain", False' in guard
    # and the tool that syncs verdicts skips such a chain entirely
    from tools import validation_tools as VT
    sync = inspect.getsource(VT.RunValidationTool._record_chain_status)
    j = sync.rindex("registryhub.record_chain_result(")   # the call, not the docstring
    assert "environment_1202od" in sync[:j] and "continue" in sync[:j]
