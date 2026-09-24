"""#1177 — the most common terminal blocker is a deadlock the remediation text creates.

`validation_ui_evidence_failed` is "7 of the last 10 declining runs" (#1040) and the gate's
own note records it as "the ONLY failing check for 85 minutes". Three framework statements
cannot all hold at once:

  1. the gate pools EVERY failing UI record, `ui_flow:*` and `ui_smoke:*` alike;
  2. its remediation says re-run `run_validation` and "Do NOT close the gate item by
     editing the record";
  3. `validation_tools` says "ui_smoke stays the verifier's browser job — run_validation is
     api-only and does not probe the UI."

So a failing `ui_smoke` record cannot be refreshed by the prescribed action, and the only
action that can refresh it is forbidden. r17 (live, 2026-08-30) died on exactly that: one
stale `validation:ui_smoke:landing_page` from 03:10:14, 21 other UI records passing,
`ui_flow:landing_page` PASSING, and the page's real defect repaired at ~03:20 — FAILED at
$336 with the milestone already marked delivered.
"""
import json

from env_generator.llm_generator.multi_agent.runtime.remediation_dispatcher import (
    ui_smoke_refresh_1177,
)


class _Orch:
    def __init__(self, root):
        self.output_dir = str(root)


def _with_records(tmp_path, records):
    hubs = tmp_path / "shared" / "hubs"
    hubs.mkdir(parents=True)
    (hubs / "codehub_checks.json").write_text(json.dumps({"checks": records}))
    return _Orch(tmp_path)


def test_the_unrefreshable_record_is_named(tmp_path):
    orch = _with_records(tmp_path, [
        {"name": "validation:ui_smoke:landing_page", "status": "failure",
         "evidence": {"summary": "emitted GET /api/titles/top10 401"}},
    ])
    out = ui_smoke_refresh_1177(orch, ["landing_page"])
    assert "validation:ui_smoke:landing_page" in out
    assert "API-ONLY" in out, "the reason run_validation cannot help must be stated"
    # The corrected refresh path, and the boundary that keeps it from being a green-flip.
    assert "codehub_record_check the SAME check name" in out
    assert "without looking at the page" in out


def test_a_failing_ui_flow_record_is_left_to_the_walk(tmp_path):
    """`ui_flow` records ARE rewritten by run_validation — the original advice is correct
    for them, so #1177 must not contradict it."""
    orch = _with_records(tmp_path, [
        {"name": "validation:ui_flow:landing_page", "status": "failure", "evidence": {}},
    ])
    assert ui_smoke_refresh_1177(orch, ["landing_page"]) == ""


def test_a_passing_ui_smoke_record_says_nothing(tmp_path):
    orch = _with_records(tmp_path, [
        {"name": "validation:ui_smoke:landing_page", "status": "success", "evidence": {}},
    ])
    assert ui_smoke_refresh_1177(orch, ["landing_page"]) == ""


def test_only_the_pages_the_gate_named(tmp_path):
    """r17 had 21 passing UI records beside the one failure; the text addresses the one."""
    orch = _with_records(tmp_path, [
        {"name": "validation:ui_smoke:landing_page", "status": "failure", "evidence": {}},
        {"name": "validation:ui_smoke:browse_home_page", "status": "failure", "evidence": {}},
    ])
    out = ui_smoke_refresh_1177(orch, ["landing_page"])
    assert "landing_page" in out and "browse_home_page" not in out


def test_missing_hub_falls_back_to_the_generic_text(tmp_path):
    assert ui_smoke_refresh_1177(_Orch(tmp_path), ["landing_page"]) == ""
    assert ui_smoke_refresh_1177(_Orch(None), ["landing_page"]) == ""


def test_the_dispatcher_calls_it_in_the_evidence_branch():
    """Anchored on the next branch landmark, not a byte count (#943, and #1176's lesson)."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as rd
    src = inspect.getsource(rd)
    i = src.index('if name == "validation_ui_evidence_failed":')
    branch = src[i:src.index('if name == "deliverability_ui_flow_failed":', i)]
    assert "ui_smoke_refresh_1177(orch, _fp)" in branch
