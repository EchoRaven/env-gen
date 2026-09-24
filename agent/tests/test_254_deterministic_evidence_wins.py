"""#254 — an evidence-free LLM verdict must not overwrite deterministic runtime evidence.

r51 (live, 117 min, aborted on ``deliverability_ui_flow_failed``) while the app WORKED:
the framework's authenticated browser walk rendered 8/8 pages cleanly and #240 recorded
8 PASS rows at 22:43:07-08 — and within 33 seconds the verifier LLM overwrote 7 of them
with ``failure`` rows whose entire evidence was ``{"flow": "explore"}``. No summary, no
execution_mode, no artifact: an opinion, stored on top of a measurement. The run then
failed the gate on flows that a DOM probe had just proven good.

Provenance, not recency, must decide. A deterministic runtime record may be superseded
only by another deterministic runtime record — which the heal pipeline re-emits every
cycle, so genuine breakage still lands and recovery is guaranteed.

This is the #240/#241/#244 false-negative class one layer deeper: those fixed the walk's
own verdicts; this stops a good verdict from being erased after the fact.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from env_generator.llm_generator.multi_agent.runtime.hub_registry import (  # noqa: E402
    HubRegistry,
    DETERMINISTIC_EVIDENCE_KEY,
)


class _CodeHub:
    """Minimal last-write-wins check store, matching CodeHub.record_check semantics."""

    def __init__(self):
        self.checks = {}

    def record_check(self, pr_id, name, status, evidence=None, agent=""):
        self.checks[name] = {
            "id": f"check_{pr_id}_{name}", "pr_id": pr_id, "name": name,
            "status": status, "evidence": evidence or {}, "updated_at": time.time(),
        }

    def list_checks(self):
        return list(self.checks.values())


def _reg():
    r = HubRegistry.__new__(HubRegistry)
    r.codehub = _CodeHub()
    return r


def _status(reg, name):
    return reg.codehub.checks[f"validation:{name}"]["status"]


def _record_deterministic_pass(reg, flow="explore"):
    reg.record_validation_result(
        task_id=f"ui_flow:{flow}", status="success", agent="framework-testuser",
        execution_mode="browser", summary="authenticated browser walk rendered cleanly",
        metadata={"check": "ui_flow", "flow": flow, DETERMINISTIC_EVIDENCE_KEY: True})


def _record_llm_failure(reg, flow="explore"):
    """The exact r51 shape: status + a bare flow tag, nothing else."""
    return reg.record_validation_result(
        task_id=f"ui_flow:{flow}", status="failure", agent="verifier",
        evidence={"flow": flow})


def test_r51_regression_llm_failure_cannot_erase_deterministic_pass():
    reg = _reg()
    _record_deterministic_pass(reg)
    _record_llm_failure(reg)
    assert _status(reg, "ui_flow:explore") == "passed"


def test_rejected_downgrade_is_reported_to_the_caller():
    """Silent is not acceptable — the writer must be able to see it was refused."""
    reg = _reg()
    _record_deterministic_pass(reg)
    out = _record_llm_failure(reg)
    assert out.get("downgrade_rejected") is True
    assert out.get("status") == "passed"


def test_another_deterministic_record_may_downgrade():
    """Real breakage still lands: the walk re-runs every heal cycle and its own
    failing verdict is authoritative, so recovery is never blocked."""
    reg = _reg()
    _record_deterministic_pass(reg)
    reg.record_validation_result(
        task_id="ui_flow:explore", status="failure", agent="framework-testuser",
        execution_mode="browser", summary="page rendered blank",
        metadata={"check": "ui_flow", "flow": "explore",
                  DETERMINISTIC_EVIDENCE_KEY: True})
    assert _status(reg, "ui_flow:explore") == "failed"


def test_llm_pass_over_deterministic_pass_is_untouched():
    """Only DOWNGRADES are guarded; ordinary writes keep last-write-wins."""
    reg = _reg()
    _record_deterministic_pass(reg)
    reg.record_validation_result(task_id="ui_flow:explore", status="success",
                                 agent="verifier", evidence={"flow": "explore"})
    assert _status(reg, "ui_flow:explore") == "passed"


def test_llm_failure_with_no_prior_record_is_stored_normally():
    reg = _reg()
    _record_llm_failure(reg, "messages")
    assert _status(reg, "ui_flow:messages") == "failed"


def test_llm_failure_over_a_NON_deterministic_pass_still_wins():
    """The guard protects measurements, not opinions — two LLM opinions stay
    last-write-wins so this cannot freeze an LLM-authored pass in place."""
    reg = _reg()
    reg.record_validation_result(task_id="ui_flow:view-explore", status="success",
                                 agent="verifier", evidence={"notes": "looks fine"})
    reg.record_validation_result(task_id="ui_flow:view-explore", status="failure",
                                 agent="verifier", evidence={})
    assert _status(reg, "ui_flow:view-explore") == "failed"


def test_guard_is_kind_agnostic_not_ui_flow_specific():
    """env-agnostic: any deterministic runtime measurement gets the same protection."""
    reg = _reg()
    reg.record_validation_result(
        task_id="api_smoke:videos", status="success", agent="framework",
        metadata={"check": "api_smoke", DETERMINISTIC_EVIDENCE_KEY: True})
    reg.record_validation_result(task_id="api_smoke:videos", status="failure",
                                 agent="verifier", evidence={})
    assert _status(reg, "api_smoke:videos") == "passed"


def test_store_read_failure_never_breaks_recording():
    """Fail-open: a hub read error must not stop a validation result being written."""
    reg = _reg()
    reg.codehub.list_checks = lambda: (_ for _ in ()).throw(RuntimeError("hub down"))
    reg.record_validation_result(task_id="ui_flow:x", status="failure", agent="verifier")
    assert _status(reg, "ui_flow:x") == "failed"
