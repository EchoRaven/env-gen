"""FIX #95 — ONE kickoff retry (re-broadcast + re-drive) before aborting the run.

Gemini MALFORMED storms are 20-50min BURSTS (runs 4, 10, 13 — 63/57 malformed in the
final 20min windows). A milestone kickoff landing in a burst times out with ZERO drafts
to reconcile → hard abort — twice discarding runs that had ALREADY delivered milestones
(run-10 M1; run-13 M1+M2). One bounded retry (re-broadcast kickoff_request to the missing
lanes + one more drive window) rescues a delivered run when the burst passes; a hopeless
run costs +20min once. LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.kickoff import run_kickoff  # noqa: E402


class _EventHub:
    def __init__(self):
        self.events = []

    def publish_event(self, **kw):
        self.events.append(kw)


class _WorkHub:
    def create_meeting(self, **kw):
        return {"id": "meet_1"}


class _Hubs:
    def __init__(self):
        self.eventhub = _EventHub()
        self.workhub = _WorkHub()


def test_handle_carries_requirements_for_rebroadcast():
    hubs = _Hubs()
    h = run_kickoff.start_kickoff(hubs=hubs, milestone_index=2,
                                  requirements=["build M2"],
                                  attendees=["backend", "frontend", "verifier"])
    assert h.get("requirements") == ["build M2"]


def test_rebroadcast_targets_missing_attendees_with_same_payload():
    hubs = _Hubs()
    h = run_kickoff.start_kickoff(hubs=hubs, milestone_index=2,
                                  requirements=["build M2"],
                                  attendees=["backend", "frontend", "verifier"])
    hubs.eventhub.events.clear()
    run_kickoff.rebroadcast_kickoff_request(hubs, h, only=["backend", "verifier"])
    assert len(hubs.eventhub.events) == 1
    ev = hubs.eventhub.events[0]
    assert ev["event_type"] == "kickoff_request"
    assert ev["recipients"] == ["backend", "verifier"]
    assert ev["payload"]["meeting_id"] == "meet_1"
    assert ev["payload"]["requirements"] == ["build M2"]


def test_orchestrator_retries_once_before_aborting():
    import inspect
    from multi_agent.orchestrator import Orchestrator
    src = inspect.getsource(Orchestrator.run)
    i_fallback = src.index('"timeout_fallback"')
    i_retry = src.index("rebroadcast_kickoff_request")
    i_raise = src.index("Kickoff timed out after")
    assert i_fallback < i_raise
    assert i_retry < i_raise                      # the retry precedes the abort


def _min_roadmap(tables):
    return {
        "contract": {
            "endpoints": [{"id": "get_feed", "method": "GET", "path": "/api/feed",
                           "auth_required": True, "response_key": "items"}],
            "data_model": {"tables": tables},
        },
        "task_tree": {"tasks": [{"id": "t1", "title": "do", "assignee": "backend"}]},
    }


def test_empty_tables_is_legit_at_milestone_2_plus():
    """FIX #96 (run-14 M2 live): the backend's M2 section arrived (after the #95
    re-broadcast!) with data_model.tables=[] — correct for a vertical slice on the
    CUMULATIVE contract (M1 registered all 10 tables) — but the validator's
    unconditional non-empty rule error'd → validation_failed → abort. At
    milestone_index > 1 an empty tables list must not be an ERROR."""
    from multi_agent.runtime.kickoff.roadmap_validator import validate_roadmap
    res = validate_roadmap(_min_roadmap([]), 2)
    errs = [f for f in res.get("findings", [])
            if f.get("severity") == "error" and "tables" in str(f.get("id", ""))]
    assert errs == [], errs


def test_empty_tables_still_errors_at_milestone_1():
    from multi_agent.runtime.kickoff.roadmap_validator import validate_roadmap
    res = validate_roadmap(_min_roadmap([]), 1)
    errs = [f for f in res.get("findings", [])
            if f.get("severity") == "error" and "tables" in str(f.get("id", ""))]
    assert errs, "milestone 1 (walking skeleton) still requires tables"


def test_visual_release_rejudges_fresh_before_escaping():
    """FIX #102 (run-20 live): the deferral escape released with a verdict from a STALE
    screenshot — the lane fixed the broken icon refs at ~23:45-23:55 but the gate escaped
    using the 23:45 pre-fix capture (the DELIVERED image serves all 47 icons with 200).
    The release branch must drive ONE final fresh capture+judge (self-guarded: only
    actually re-judges when the source changed) so the recorded verdict reflects the
    delivered source."""
    #943/#1202lk: anchored on the BRANCH, not on a byte count. The original
    # `src[i_release - 2500 : i_release]` asserted the same thing and broke the day #1202lk
    # added its re-capture arm — no logic changed, the call simply moved further than 2500
    # bytes from the log line it precedes. A backwards window is the same defect as the
    # forward ones #943 ratchets.
    #
    # ★ And the obvious re-anchor — `"_maybe_run_visual_fidelity" in <branch text>` — is
    # VACUOUS: #102's own comment inside that branch spells the method name, so deleting the
    # call still passes. (Written, counter-proved, and thrown away — not assumed.) The
    # assertion is therefore on CALL NODES.
    import ast
    import inspect
    from multi_agent.orchestrator import Orchestrator
    src = inspect.getsource(Orchestrator)
    escape = None
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.If) and node.orelse):
            continue
        seg = ast.get_source_segment(src, node) or ""
        if ('_vf_decision == "fast_release"' in seg
                and "Visual fidelity deferral RELEASED" in seg):
            escape = node.orelse
            break
    assert escape, "the visual escape branch moved — relocate this landmark"

    def _linenos(pred):
        return sorted(n.lineno for stmt in escape for n in ast.walk(stmt)
                      if isinstance(n, ast.Call) and pred(n))

    rejudge = _linenos(lambda n: isinstance(n.func, ast.Attribute)
                       and n.func.attr == "_maybe_run_visual_fidelity")
    released = _linenos(lambda n: any(
        isinstance(a, ast.Constant) and "Visual fidelity deferral RELEASED" in str(a.value)
        for a in n.args))
    assert rejudge, ("the escape branch no longer CALLS the final fresh capture+judge "
                     "(the name appearing in a comment is not a call)")
    assert released, "the RELEASED announcement moved out of this branch"
    assert min(rejudge) < min(released), (
        "the escape must drive ONE final fresh capture+judge BEFORE it announces the release")
    _lines = src.splitlines()
    assert "FIX #102" in "\n".join(_lines[escape[0].lineno - 10:min(released)]), (
        "#102's reasoning must stay with the mechanism it explains")


def test_capture_injects_token_under_all_common_key_aliases():
    """FIX #103 (runs 9+21 live): the gate injected localStorage 'token' but the lane's
    app read 'access_token' → every auth route bounced to /login → 'authenticated session
    rejected — skipping judgment' → visual coverage collapsed to the login screens. The
    key name is pure lane variance: inject the SAME token under every common alias (extra
    keys are inert) in both localStorage and sessionStorage."""
    import inspect
    from multi_agent.runtime import visual_fidelity as vf
    src = inspect.getsource(vf)
    # SEMANTIC window, not a fixed one: `src.index("add_init_script")` finds the
    # FIRST call in the module (a different, earlier injection), and a +/-1200
    # char window around it stopped reaching the alias tuple once the module grew.
    # Anchor on the tuple itself and stop at the end of the statement that consumes
    # it, so this keeps checking the same code however the file moves.
    i = src.index("_aliases = (")
    window = src[i:src.index("page = await ctx.new_page()", i)]
    for alias in ("access_token", "auth_token", "authToken",
                  "accessToken", "jwt"):
        assert alias in window, f"missing alias {alias}"
    assert "sessionStorage" in window


def test_auth_rejection_triggers_one_remint_retry():
    """FIX #105 (run-22 live, recurring despite #103): the wholesale auth rejection is a
    RACE — a parallel validation cycle resets the DB (the token's sub vanishes) or
    rotates JWT keys between mint and capture. The gate must re-mint ONCE and retry the
    capture before skipping the whole judgment."""
    # #943/#1202lk: the enclosing FUNCTION, located by AST, rather than "the 2500 bytes
    # before the string" — a backwards byte window breaks on comment growth exactly as a
    # forward one does, and the retry it guards must live in the same function as the skip.
    import ast
    import inspect
    from multi_agent.runtime import visual_fidelity as vf
    src = inspect.getsource(vf)
    i = src.index("authenticated session rejected — every auth route")
    _line = src[:i].count("\n") + 1
    _tree = ast.parse(src)
    _fn = None
    for _n in ast.walk(_tree):
        if (isinstance(_n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and _n.lineno <= _line <= (_n.end_lineno or _n.lineno)
                and (_fn is None or _n.lineno > _fn.lineno)):   # innermost wins
            _fn = _n
    assert _fn is not None, "the auth-wipeout skip moved out of any function"
    _lines = src.splitlines()
    window = "\n".join(_lines[_fn.lineno - 1:_line - 1])
    # a re-mint CALL (not merely the name in prose) happens before the final skip
    assert any(isinstance(_c, ast.Call)
               and "_mint_token" in (ast.unparse(_c.func) if _c.func else "")
               and _c.lineno < _line
               for _c in ast.walk(_fn)), "no re-mint call precedes the wholesale skip"
    assert "FIX #105" in window
    # semantic end (rest of the enclosing top-level function) rather than a
    # character count, so growth in the module cannot silently move it
    _end2 = src.find("\ndef ", i)
    assert "incl. one re-mint retry" in src[i:_end2 if _end2 != -1 else len(src)]


def test_heal_gate_bypassed_when_build_class_check_is_wedged():
    """FIX #107 (run-25 live): the heal-on-change signature gate skipped every repair
    while docker_up wedged 7 cycles (the lane's edits never reached integration → the
    signature never changed → the frontend import/export reconcilers — which DID fix
    run-25's App.jsx when invoked directly — never fired). A build-class failure in the
    last failure set must force the heal pass."""
    import inspect
    from multi_agent.runtime import framework_validation as fv
    src = inspect.getsource(fv)
    # Anchor on the FIX #107 marker itself and read FORWARD to its logic — the old
    # anchor (first _fwval_healed_sig use) put the marker just outside a fixed
    # 1500-char back-window whenever code was added between them (brittle).
    i = src.index("FIX #107")
    # semantic end (the rest of the enclosing top-level construct) rather than a
    # character count — the note above already records that a fixed window here
    # broke once when code was added between the anchor and what it checks.
    _end = src.find("\ndef ", i)          # last top-level construct -> EOF
    window = src[i:_end if _end != -1 else len(src)]
    assert "_build_wedged" in window
    assert "docker_up" in window
    # the build-wedged flag feeds the heal-sig regen gate a few lines further down
    assert "_should_regen_skeleton" in window


def test_missing_data_model_is_legit_at_milestone_2_plus():
    """FIX #108 (run-27 M3 live, sibling of #96): the backend's M3 section omitted
    data_model entirely (cumulative contract — M1 registered everything), but the
    validator's unconditional 'data_model MUST be a mapping' error → synthesis
    'conflict' → kickoff abort after M1+M2 delivered. At milestone 2+ a missing/None
    data_model degrades to a warning; milestone 1 still hard-requires it."""
    from multi_agent.runtime.kickoff.roadmap_validator import validate_roadmap
    rm = {"contract": {"endpoints": [{"id": "e", "method": "GET", "path": "/api/x",
                                      "auth_required": True, "response_key": "items"}]},
          "task_tree": {"tasks": [{"id": "t1", "title": "do", "assignee": "backend"}]}}
    res2 = validate_roadmap(rm, 2)
    errs2 = [f for f in res2.get("findings", [])
             if f.get("severity") == "error" and "data_model" in str(f.get("id", ""))]
    assert errs2 == [], errs2
    res1 = validate_roadmap(rm, 1)
    errs1 = [f for f in res1.get("findings", [])
             if f.get("severity") == "error" and "data_model" in str(f.get("id", ""))]
    assert errs1, "milestone 1 still requires a data_model mapping"


def test_visual_verify_tools_force_offered_in_edit_and_check_stages():
    """FIX #110 (runs 24+26 autopsy): the visual-gate remediation tasks carried perfect
    measured diffs + an executable zoom_compare mandate, but the frontend lane NEVER
    called zoom_compare/capture_webpage in any run — the ~10-slot ranker crowded the
    visual verify tools out of every step's offered subset (the documented
    never-offered class: V25/_ORCH_AUDIT_FLOW/_KNOWLEDGE_DOC_FLOW precedents). The lane
    was structurally blind to its own render. Force-offer them (bundle-intersected) in
    edit_code + run_checks."""
    from multi_agent.agents.base import EnvGenAgent
    inc = EnvGenAgent.ACTION_STAGE_ALWAYS_INCLUDE
    for tool in ("capture_webpage", "zoom_compare", "sample_color",
                 "compare_with_screenshot"):
        assert tool in inc["edit_code"], f"{tool} not force-offered in edit_code"
        assert tool in inc["run_checks"], f"{tool} not force-offered in run_checks"


def test_fix116_frontend_stage_allowlist_admits_visual_verify_tools():
    """FIX #116 (run-32 live, final-milestone visual window): #110 force-offered the
    visual verify tools at the RANKER layer, but tooling.py intersects always_include
    with the profile's stage_tool_allowlist — and the frontend's implementation:action
    / test_fix:action lists (33 tools) contained NONE of them, so the force-offer was
    stripped and the lane again never saw zoom_compare/capture_webpage (run-32: 4 judge
    rounds, scores flat, tools=32 per request, zero visual calls). The allowlist is the
    second fence; both layers must admit the tools."""
    import yaml
    from pathlib import Path as _P
    cfg = _P(__file__).resolve().parents[1] / (
        "env_generator/llm_generator/multi_agent/agents/agents_config.yaml")
    d = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    al = d["profiles"]["frontend"]["stage_tool_allowlist"]
    # compare_with_screenshot is EXCLUDED: it rides the llm_client-gated vision
    # bundle, which the cross-validator assembles without → dead-entry flag; the
    # remediation mandate's compare tool is zoom_compare anyway.
    vis = {"capture_webpage", "zoom_compare", "sample_color",
           "crop_reference", "extract_palette"}
    for stage in ("implementation:action", "test_fix:action"):
        missing = vis - set(al[stage])
        assert not missing, f"{stage} missing visual verify tools: {sorted(missing)}"
