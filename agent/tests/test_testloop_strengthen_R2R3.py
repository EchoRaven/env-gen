"""R2+R3 — strengthen the user-agent test loop so it catches FUNCTIONAL bugs the
declared-contract tests miss (the "test loop optimizes the app" lever).

ROOT PROBLEM: every test layer derived tasks/chains from the DECLARED endpoints, so a
MISSING write-path (a state entity's write endpoint) was silently skipped and coverage
read 100%; and the existing assertions checked 2xx-reachability, not real outcomes
(``_appears`` ALWAYS returned True; the write-intent verb set omitted play/resume/rate).

These tests pin the two fixes (Stage 1 = detection + real-outcome assertions; findings
flow through the EXISTING bug_create / framework-defect path — no new hard-block gate):

  R2(a) plan_test_user_goals — a state entity / mutation flow with no write yields an
        explicit ``missing_write_path`` goal (not silent skip); byte-identical when the
        entity already has its write or no table/inventory is supplied.
  R2(b) synthesize_default_chain — the same gap surfaces as a ``framework_defect`` step
        on the chain gate; byte-identical when nothing is missing / tables omitted.
  R3(a) _created_appears / _readback_persisted / _write_lost — a created row absent from
        the list, or a state value that did not persist, is now BROKEN (was always-True);
        and the full _api_crud_journey wiring marks that step broken.
  R3(b) _WRITE_INTENT_WORDS / implies_write — the mutation-verb set now includes
        play/resume/rate/… and a state control that fires no persisting call is flagged.
"""

import json

from env_generator.llm_generator.multi_agent.runtime.test_user_squad import (
    plan_test_user_goals,
)
from env_generator.llm_generator.multi_agent.runtime.chain_executor import (
    synthesize_default_chain,
    execute_chain,
)
from env_generator.llm_generator.multi_agent.runtime import test_user_validation as tv
from env_generator.llm_generator.multi_agent.runtime.test_user_validation import (
    _created_appears,
    _readback_persisted,
    _write_lost,
)
from env_generator.llm_generator.multi_agent.runtime import control_exercise as cx
from env_generator.llm_generator.multi_agent.runtime.control_exercise import (
    implies_write,
    evaluate_control,
    _WRITE_INTENT_WORDS,
)


# ---------------------------------------------------------------------------
# Fixtures (mirror test_completeness_audit_557 shapes)
# ---------------------------------------------------------------------------

def _col(name, type_="integer", **kw):
    return {"name": name, "type": type_, **kw}


def _table(name, columns, status="implemented"):
    return {"id": name, "name": name, "status": status, "schema": {"columns": columns}}


def _ep(method, path, **kw):
    return {"method": method, "path": path, "status": "implemented", **kw}


# a state-bearing table: PK + owner FK + a mutable scalar + a timestamp
_STATE_TABLE = _table("watch_progress", [
    _col("id", "integer", primary_key=True),
    _col("user_id", "integer", references="users.id"),
    _col("item_id", "integer", references="items.id"),
    _col("progress_seconds", "integer", default=0),
    _col("updated_at", "timestamp"),
])


# ===========================================================================
# R2(a) — plan_test_user_goals emits missing_write_path goals
# ===========================================================================

def test_r2a_state_entity_without_write_yields_missing_write_goal():
    goals = plan_test_user_goals(
        business_eps=[_ep("GET", "/api/watch-progress")],
        tables={"watch_progress": _STATE_TABLE},
    )
    mw = [g for g in goals if g.get("kind") == "missing_write_path"]
    assert len(mw) == 1, goals
    g = mw[0]
    assert g["entity"] == "watch_progress"
    assert g["name"] == "missing_write_watch_progress"
    assert g["critical"] is True
    assert "POST" in (g["missing_verb"] or "")
    # fails loudly: the briefing tells the agent to file the bug via bug_create
    assert "bug_create" in g["goal"]
    assert "no endpoint to create/update watch_progress" in g["goal"]


def test_r2a_entity_with_write_is_byte_identical_no_extra_goal():
    eps = [_ep("GET", "/api/watch-progress"), _ep("POST", "/api/watch-progress")]
    baseline = plan_test_user_goals(business_eps=eps)               # no tables
    with_tables = plan_test_user_goals(
        business_eps=eps, tables={"watch_progress": _STATE_TABLE})  # entity HAS a write
    assert not any(g.get("kind") == "missing_write_path" for g in with_tables)
    assert with_tables == baseline  # byte-identical


def test_r2a_no_tables_no_inventory_is_byte_identical():
    eps = [_ep("GET", "/api/notes"), _ep("POST", "/api/notes")]
    assert plan_test_user_goals(business_eps=eps) == plan_test_user_goals(
        business_eps=eps, tables=None, feature_inventory=None)


def test_r2a_feature_inventory_mutation_flow_without_write_flagged():
    goals = plan_test_user_goals(
        business_eps=[_ep("GET", "/api/continue-watching")],
        feature_inventory={"flows": ["continue_watching"]},
    )
    mw = [g for g in goals if g.get("kind") == "missing_write_path"]
    assert [g.get("flow") for g in mw] == ["continue_watching"]
    assert "bug_create" in mw[0]["goal"]


# ===========================================================================
# R2(b) — synthesize_default_chain surfaces missing writes as framework_defects
# ===========================================================================

def test_r2b_state_entity_without_write_emits_synthetic_defect_chain():
    chains = synthesize_default_chain(
        [_ep("GET", "/api/watch-progress")],           # readable, no write
        tables={"watch_progress": _STATE_TABLE},
    )
    assert len(chains) == 1
    ch = chains[0]
    assert ch["name"] == "framework_missing_write_paths"
    assert len(ch["steps"]) == 1
    st = ch["steps"][0]
    assert st["synthetic_defect"] is True
    assert "watch_progress" in st["note"]
    assert "missing_write_path" in st["note"]


def test_r2b_synthetic_defect_records_as_framework_defect_on_gate():
    chains = synthesize_default_chain(
        [_ep("GET", "/api/watch-progress")], tables={"watch_progress": _STATE_TABLE})
    # execute_chain never makes an HTTP call for a synthetic_defect step (base is a stub).
    result = execute_chain("http://unused.invalid", chains[0])
    assert result["broken"] == []                     # not a lane-dispatched app bug
    assert len(result["framework_defects"]) == 1      # surfaced as framework work (#272)
    assert result["steps"][0]["kind"] == "framework_defect"
    assert result["steps"][0]["ok"] is False


def test_r2b_byte_identical_when_tables_omitted():
    # no creatable collection + no tables → [] exactly as before
    assert synthesize_default_chain([_ep("GET", "/api/watch-progress")]) == []
    # a creatable collection → the same CRUD chain with or without an (empty) tables arg
    eps = [_ep("POST", "/api/notes", schema={"request": {"title": "string"}}),
           _ep("GET", "/api/notes")]
    assert synthesize_default_chain(eps) == synthesize_default_chain(eps, tables=None)


def test_r2b_byte_identical_when_entity_already_has_write():
    eps = [_ep("POST", "/api/watch-progress", schema={"request": {"progress_seconds": "int"}}),
           _ep("GET", "/api/watch-progress")]
    baseline = synthesize_default_chain(eps)                                  # no tables
    with_tables = synthesize_default_chain(eps, tables={"watch_progress": _STATE_TABLE})
    assert not any(c["name"] == "framework_missing_write_paths" for c in with_tables)
    assert with_tables == baseline


# ===========================================================================
# R3(a) — real list-persistence + write->read-back value assertions
# ===========================================================================

def test_r3a_created_appears_true_when_present():
    ok, note = _created_appears({"items": [{"id": 7}]}, "note", 7)
    assert ok is True and "appears" in note


def test_r3a_created_appears_false_when_absent():
    ok, note = _created_appears({"items": []}, "note", 7)
    assert ok is False and "ABSENT" in note


def test_r3a_created_appears_advisory_when_no_id():
    # not applicable (no created id captured) -> advisory True (byte-identical intent)
    ok, _ = _created_appears({"items": [{"id": 1}, {"id": 2}]}, "note", None)
    assert ok is True


def test_r3a_created_appears_state_value_mismatch_is_broken():
    # present in the list but the state value was lost -> broken (non-persisting write)
    ok, note = _created_appears(
        {"items": [{"id": 7, "progress_seconds": 0}]}, "progress", 7,
        {"progress_seconds": 1})
    assert ok is False and "not persisted" in note


def test_r3a_created_appears_state_value_match_ok():
    ok, _ = _created_appears(
        {"items": [{"id": 7, "progress_seconds": 1}]}, "progress", 7,
        {"progress_seconds": 1})
    assert ok is True


def test_r3a_readback_persisted_match_and_mismatch():
    # GET-by-id round-trip: wrote 1, read 1 -> ok
    ok, _ = _readback_persisted({"item": {"progress_seconds": 1}}, "progress",
                                {"progress_seconds": 1})
    assert ok is True
    # wrote 1, read 0 (no-op progress endpoint) -> broken
    ok, note = _readback_persisted({"item": {"progress_seconds": 0}}, "progress",
                                   {"progress_seconds": 1})
    assert ok is False and "no-op" in note


def test_r3a_write_lost_heuristic():
    assert _write_lost(1, 0) is True            # wrote non-empty, read default -> lost
    assert _write_lost(1, None) is True         # field not persisted at all
    assert _write_lost(1, 1) is False           # persisted
    assert _write_lost(1, "1") is False         # type-tolerant
    assert _write_lost("persist-probe", "pending") is False  # server normalization, not lost
    assert _write_lost("persist-probe", "") is True          # dropped


def test_r3a_api_crud_journey_marks_missing_from_list_broken(monkeypatch):
    """Full wiring: a create whose row never appears in the list is a BROKEN step."""
    calls = {}

    def fake_http(method, url, token=None, body=None, **kw):
        path = url.split("://", 1)[-1].split("/", 1)[-1]
        path = "/" + path if not path.startswith("/") else path
        if path.startswith("/auth/register") or path.startswith("/auth/login"):
            return {"status": 200, "body_text": json.dumps({"access_token": "tok"})}
        if method == "POST" and path == "/api/progress":
            return {"status": 201, "body_text": json.dumps({"id": 1, "progress_seconds": 1})}
        if method == "GET" and path == "/api/progress":
            return {"status": 200, "body_text": json.dumps(calls["list_body"])}
        return {"status": 200, "body_text": "{}"}

    monkeypatch.setattr(tv, "_http", fake_http)
    eps = [_ep("POST", "/api/progress", schema={"request": {"progress_seconds": "int"}}),
           _ep("GET", "/api/progress")]

    # (a) created row ABSENT from the list -> the list step is broken
    calls["list_body"] = []
    report = tv._api_test_user("http://app", set(), eps)
    list_steps = [s for s in report["steps"] if s["action"] == "list progress"]
    assert list_steps and list_steps[0]["kind"] == "broken", report["steps"]

    # (b) present with the persisted value -> the list step passes
    calls["list_body"] = [{"id": 1, "progress_seconds": 1}]
    report = tv._api_test_user("http://app", set(), eps)
    list_steps = [s for s in report["steps"] if s["action"] == "list progress"]
    assert list_steps and list_steps[0]["ok"] is True

    # (c) present but the state value was lost (no-op write) -> broken
    calls["list_body"] = [{"id": 1, "progress_seconds": 0}]
    report = tv._api_test_user("http://app", set(), eps)
    list_steps = [s for s in report["steps"] if s["action"] == "list progress"]
    assert list_steps and list_steps[0]["kind"] == "broken"


# ===========================================================================
# R3(b) — broadened write-intent verbs + dead-control detection
# ===========================================================================

def test_r3b_write_intent_words_include_state_verbs():
    for w in ("play", "start", "resume", "watch", "rate", "like", "mark",
              "toggle", "progress", "track"):
        assert w in _WRITE_INTENT_WORDS
    # original UI-action vocabulary is preserved
    for w in ("save", "submit", "delete", "publish"):
        assert w in _WRITE_INTENT_WORDS


def test_r3b_implies_write_word_part_matched():
    assert implies_write("Resume watching") is True
    assert implies_write("Rate") is True
    assert implies_write("Mark as read") is True
    assert implies_write("Save changes") is True
    # word-part matching avoids the substring false positives the old set would hit
    assert implies_write("Display settings") is False   # 'display' !~ 'play'
    assert implies_write("Address book") is False       # 'address' !~ 'add'
    assert implies_write("Home") is False


def test_r3b_state_control_with_no_persisting_call_flagged_dead():
    # a 'Play'/'Rate' control that fires NO network call and does nothing observable
    for label in ("Play", "Rate", "Resume"):
        rec = {"label": label, "network": [], "navigated": False,
               "dom_changed": False, "console_errors": []}
        ev = evaluate_control(rec)
        assert ev["dead"] is True, label
        assert ev["effect"] == "no_effect"


def test_r3b_working_state_control_not_flagged():
    # a resume button that fires a persisting write is NOT dead
    rec = {"label": "Resume", "navigated": False, "dom_changed": True,
           "network": [{"method": "POST", "path": "/api/progress", "status": 200}],
           "console_errors": []}
    ev = evaluate_control(rec)
    assert ev["dead"] is False
    assert ev["effect"] == "network_write"
