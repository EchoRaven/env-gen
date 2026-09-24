"""#258 — the deterministic-evidence guard has to sit on the STORE, not on one caller.

#254 put it in HubRegistry.record_validation_result. r52 then died on exactly the same
check as r51 (deliverability_ui_flow_failed, working app) and the guard never fired once:
the framework's measured PASSes were erased by ``codehub_record_check``, an AGENT-FACING
TOOL that writes straight to ``CodeHub.record_check``. Its own description tells agents to
use ``validation:ui_flow:<flow_name>``, so the verifier LLM overwrote 8 measured PASSes
with rows whose entire evidence was ``{"error": ...}`` — one layer below where I had put
the protection.

Three writers reach this store (the tool, HubRegistry, the task-suite executor), so the
invariant belongs to the store itself: a record carrying DETERMINISTIC_EVIDENCE_KEY may be
downgraded only by another record that also carries it.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from env_generator.llm_generator.multi_agent.runtime.hub_registry import (  # noqa: E402
    DETERMINISTIC_EVIDENCE_KEY,
)


def _codehub():
    import tempfile
    from pathlib import Path as _P
    from env_generator.llm_generator.multi_agent.runtime.hubs.codehub.service import (
        CodeHub,
    )
    d = _P(tempfile.mkdtemp())
    (d / "repo").mkdir(exist_ok=True)
    (d / "hub").mkdir(exist_ok=True)
    return CodeHub(d / "repo", d / "hub")


NAME = "validation:ui_flow:explore"


def _det_pass(hub):
    return hub.record_check(
        pr_id="main", name=NAME, status="success",
        evidence={"summary": "authenticated browser walk rendered this page cleanly",
                  "execution_mode": "browser", "flow": "explore",
                  DETERMINISTIC_EVIDENCE_KEY: True},
        agent="")


def _llm_fail(hub):
    """The exact r52 shape: a status and a bare error tag, nothing measured."""
    return hub.record_check(pr_id="main", name=NAME, status="failure",
                            evidence={"error": "page did not load"}, agent="verifier")


def _status(hub):
    for c in hub.list_checks():
        if c.get("name") == NAME:
            return c.get("status")
    return None


def test_r52_regression_agent_tool_cannot_erase_a_measured_pass():
    hub = _codehub()
    _det_pass(hub)
    _llm_fail(hub)
    assert _status(hub) == "success"


def test_refusal_is_visible_to_the_caller():
    hub = _codehub()
    _det_pass(hub)
    out = _llm_fail(hub)
    assert isinstance(out, dict) and out.get("downgrade_rejected") is True


def test_another_measured_result_may_downgrade():
    """Real breakage still lands — the walk re-runs every heal cycle."""
    hub = _codehub()
    _det_pass(hub)
    hub.record_check(pr_id="main", name=NAME, status="failure",
                     evidence={"summary": "page rendered blank",
                               "execution_mode": "browser",
                               DETERMINISTIC_EVIDENCE_KEY: True},
                     agent="")
    assert _status(hub) == "failure"


def test_upgrade_to_pass_is_never_blocked():
    hub = _codehub()
    _det_pass(hub)
    hub.record_check(pr_id="main", name=NAME, status="success",
                     evidence={"notes": "looks fine"}, agent="verifier")
    assert _status(hub) == "success"


def test_unmarked_records_keep_last_write_wins():
    """The guard protects measurements, not opinions — two opinions stay as before,
    so it can never freeze an LLM-authored pass in place."""
    hub = _codehub()
    hub.record_check(pr_id="main", name=NAME, status="success",
                     evidence={"notes": "looks fine"}, agent="verifier")
    hub.record_check(pr_id="main", name=NAME, status="failure",
                     evidence={"error": "nope"}, agent="verifier")
    assert _status(hub) == "failure"


def test_guard_is_check_kind_agnostic():
    hub = _codehub()
    hub.record_check(pr_id="main", name="build:docker", status="success",
                     evidence={"source": "run_validation",
                               DETERMINISTIC_EVIDENCE_KEY: True}, agent="")
    hub.record_check(pr_id="main", name="build:docker", status="failure",
                     evidence={}, agent="verifier")
    got = [c for c in hub.list_checks() if c.get("name") == "build:docker"][0]
    assert got.get("status") == "success"


def test_first_write_of_a_failure_is_stored_normally():
    hub = _codehub()
    _llm_fail(hub)
    assert _status(hub) == "failure"
