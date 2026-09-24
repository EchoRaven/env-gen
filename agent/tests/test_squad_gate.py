"""FIX #179 — the test-user SQUAD (the LLM agents that actually DRIVE the app across
api+browser+mcp modalities, click every control, and file P0 defects via bug_create) was
env-gated OFF by default (ENVGEN_TESTUSER_SQUAD=0), so real delivery runs never ran it —
that's why a gmaps build with dead buttons + a blank place-detail shipped past the test-user.
Validated live on gmrun13 (it spawned 9 agents, detected a broken frontend, filed bugs), so
flip it ON by default. Second bug: attempt 1 of the gate frequently fires before the app's
ports resolve (gather_squad_inputs → ran=False, "could not resolve running app ports"); that
transient must NOT burn an escape-budget attempt — otherwise flaky port timing erodes the
defer/escape budget. Wall-clock (squad_release_decision) stays the backstop. Pure gate helpers
unit-tested here. LOCAL-ONLY.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.test_user_squad import (  # noqa: E402
    squad_gate_enabled, squad_gate_outcome,
)


def test_squad_gate_on_by_default():
    # #179: the squad now runs on delivery unless the operator explicitly disables it.
    assert squad_gate_enabled({}) is True
    assert squad_gate_enabled({"ENVGEN_TESTUSER_SQUAD": "1"}) is True
    assert squad_gate_enabled({"ENVGEN_TESTUSER_SQUAD": "on"}) is True
    assert squad_gate_enabled({"ENVGEN_TESTUSER_SQUAD": "TRUE"}) is True


def test_squad_gate_explicit_off():
    assert squad_gate_enabled({"ENVGEN_TESTUSER_SQUAD": "0"}) is False
    assert squad_gate_enabled({"ENVGEN_TESTUSER_SQUAD": "false"}) is False
    assert squad_gate_enabled({"ENVGEN_TESTUSER_SQUAD": "no"}) is False
    assert squad_gate_enabled({"ENVGEN_TESTUSER_SQUAD": "off"}) is False


def test_gate_outcome_clean_pass():
    # squad ran and filed zero P0 → the milestone may release.
    assert squad_gate_outcome(ran=True, p0=0) == "pass"


def test_gate_outcome_defects_defer():
    # squad ran and filed P0 defects → defer (and this DOES burn an attempt).
    assert squad_gate_outcome(ran=True, p0=3) == "defect"
    assert squad_gate_outcome(ran=True, p0=1) == "defect"


def test_gate_outcome_transient_retry_not_defect():
    # ports not ready / empty contract → ran=False → RETRY: defer but do NOT burn an attempt,
    # kept distinct from a real-defect defer so flaky port timing can't erode the escape budget.
    assert squad_gate_outcome(ran=False, p0=0) == "retry"
    # even if some stale p0 count leaks in, a squad that didn't run can't have found them.
    assert squad_gate_outcome(ran=False, p0=5) == "retry"
