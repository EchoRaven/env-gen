"""#505 (netflix r82, 2026-08-05) — deliver_project CRASHED on a string checklist,
so the run NEVER delivered despite being fully deliverable.

GROUND TRUTH from r82 (gm_netflix-web-r82.log): the whole delivery tail went green —
business_chain resolved (11:09), visual fidelity PASSED at ENVGEN_VISUAL_MIN=0.01
(11:12:46), and the LIVE delivery gate reported ``verdict=deliverable, 0 blockers``
(11:25:10). The orchestrator then called ``deliver_project`` ~20× over 14min, and every
call ERRORED: "deliver_project tool is broken: with checklist -> 'str' object has ...".
Root: ``DeliverProjectTool.execute`` declares ``checklist: dict`` but the LLM passed it
as a JSON STRING; a non-empty str is truthy so ``checklist or {}`` kept the str and
``checklist.get(check)`` raised ``AttributeError('str' object has no attribute 'get')``.
The tool failed on every attempt → ``create_release`` never ran → ``codehub_releases``
stayed empty → r82 recorded as undelivered though it was deliverable.

FIX: coerce ``checklist`` — parse a JSON-string into a dict; any non-dict (prose / null
/ list) → {} (fails the SELF-ASSERTED checks with a clear error, never a crash). This
generalizes to every app: all deliveries route through this tool.

These tests lock: (1) a JSON-string all-true checklist delivers (the r82 case), (2) a
dict checklist is byte-identical to before, (3) prose/None/list never crash — they
degrade to a clear failed-checks rejection."""
from env_generator.llm_generator.tools.agent_interaction_tools import DeliverProjectTool


_ALL_TRUE = {"no_bugs": True, "requirements_met": True,
             "fully_functional": True, "docker_ok": True}


def _tool():
    # agent=None → GUARD 2 (live gate) and GUARD 2c (visual defer) are skipped
    # (both require self.agent), isolating the checklist-coercion path under test.
    return DeliverProjectTool(agent=None)


# ---- the r82 case: LLM passed the checklist as a JSON STRING ----
def test_json_string_all_true_checklist_delivers_not_crash():
    import json
    r = _tool().execute("CONFIRMED", "Netflix web clone delivered.",
                        checklist=json.dumps(_ALL_TRUE))
    assert r.success is True                      # pre-fix: AttributeError → success False
    assert r.data and r.data.get("delivered") is True


def test_json_string_partial_checklist_fails_cleanly_not_crash():
    import json
    r = _tool().execute("CONFIRMED", "summary",
                        checklist=json.dumps({"no_bugs": True}))  # missing 3 checks
    assert r.success is False
    assert "Failed checks" in (r.error_message or "")            # actionable, not a crash


# ---- dict checklist: byte-identical to prior behavior ----
def test_dict_all_true_checklist_delivers():
    r = _tool().execute("CONFIRMED", "summary", checklist=dict(_ALL_TRUE))
    assert r.success is True
    assert r.data.get("delivered") is True


def test_dict_partial_checklist_fails():
    r = _tool().execute("CONFIRMED", "summary",
                        checklist={"no_bugs": True, "requirements_met": True})
    assert r.success is False
    assert "Failed checks" in (r.error_message or "")


# ---- non-dict junk never crashes; degrades to a clear failed-checks rejection ----
def test_prose_string_checklist_does_not_crash():
    r = _tool().execute("CONFIRMED", "summary",
                        checklist="all green, ready to ship")   # unparseable prose
    assert r.success is False
    assert "Failed checks" in (r.error_message or "")


def test_none_checklist_does_not_crash():
    r = _tool().execute("CONFIRMED", "summary", checklist=None)
    assert r.success is False
    assert "Failed checks" in (r.error_message or "")


def test_list_checklist_does_not_crash():
    r = _tool().execute("CONFIRMED", "summary", checklist=["no_bugs", "docker_ok"])
    assert r.success is False
    assert "Failed checks" in (r.error_message or "")


def test_json_string_that_parses_to_list_does_not_crash():
    # a JSON string that decodes to a non-dict must still coerce to {} safely.
    r = _tool().execute("CONFIRMED", "summary", checklist="[1, 2, 3]")
    assert r.success is False
    assert "Failed checks" in (r.error_message or "")


# ---- confirmation guard still enforced regardless of checklist shape ----
def test_bad_confirmation_still_rejected_before_checklist():
    r = _tool().execute("yes", "summary", checklist=dict(_ALL_TRUE))
    assert r.success is False
    assert "CONFIRMED" in (r.error_message or "")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
