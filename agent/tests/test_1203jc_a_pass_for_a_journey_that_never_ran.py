r"""#1203jc: PASS was the verdict for an API journey that never ran a single step.

The ladder is `broken -> ISSUES`, `missing or MCP -> PARTIAL`, else `PASS`. Both `broken`
and `missing` are derived FROM `steps`, so an empty journey empties both and the ladder
fell through to its strongest claim. Measured over the 263 persisted reports in this
corpus: 121 walked 0 steps, and 33 of those were recorded PASS — 33 of the 42 PASS
verdicts that exist, 79%. The sentence that produces reads "PASS — 0/0 API journey steps
OK + MCP surface complete".

★ 0 STEPS IS LEGITIMATE and is not what this fixes. `_api_crud_journey` drives a
create→list→read→update→delete from each collection that supports create, so a read-heavy
early milestone has nothing to start from (`api_smoke` probes every registered endpoint
separately and covers the reads). tiktok-web-r185 is the timeline: its first business
collection POST (`/api/notifications`) was registered at 18:48:58, while the v1.0.0 and
v1.1.0 walks ran at 17:51 and 18:29 — before one existed; the three `/api/v1/*`
collections that did exist are `is_business() == False`. The journey behaved correctly.
Only the verdict lied, and `instagram-core-r175` v1.1.0 (2026-10-10) is the current
generation's instance: PASS, 0 steps, 33 declared endpoints.

The branch is LAST in the ladder, so an empty journey can only withdraw a PASS — never
downgrade a finding somebody did collect. r185's own UI signup failure must stay ISSUES.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.test_user_validation as TUV  # noqa: E402


def _run(monkeypatch, tmp_path, steps, ui_flows, mcp_complete=True):
    """Replace only the OUTSIDE WORLD; the verdict under test is computed by the real
    function. Same shape as #1203c6's helper, which drives this same ladder."""
    (tmp_path / "docker").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docker" / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr(TUV, "_http", lambda *a, **k: {"status": 200, "json": {}},
                        raising=False)
    monkeypatch.setattr(TUV, "_backend_host_port", lambda *a, **k: 8080, raising=False)
    monkeypatch.setattr(TUV, "_api_test_user",
                        lambda *a, **k: {"steps": list(steps), "actor": "alpha"})
    monkeypatch.setattr(TUV, "_mcp_test_user",
                        lambda *a, **k: {"complete": mcp_complete, "tools_found": 1})

    async def _flows(_base):
        return {"ran": True, "flows": list(ui_flows),
                "passed": all(f.get("ok") for f in ui_flows)}
    monkeypatch.setattr(TUV, "_ui_auth_flow", _flows)
    import multi_agent.runtime.validation_runner as VR
    monkeypatch.setattr(VR, "_service_host_port", lambda *a, **k: 8021, raising=False)
    return TUV.run_test_user_validation(tmp_path, [{"path": "/api/videos"}],
                                        version="1.1.0")


_OK = [{"action": "create videos", "method": "POST", "path": "/api/videos",
        "status": 201, "ok": True, "kind": "ok", "note": "author_id=10"}]
_UI_OK = [{"flow": "signup", "ok": True, "note": ""}, {"flow": "login", "ok": True, "note": ""}]
_UI_FAIL = [{"flow": "signup", "ok": False,
             "note": "Locator.fill: Malformed value (input[type=date])"}]


def test_an_unwalked_journey_is_not_a_pass(monkeypatch, tmp_path):
    """★ THE TICKET, in the exact shape r175 v1.1.0 shipped: nothing walked, UI clean,
    MCP complete — previously PASS."""
    s = _run(monkeypatch, tmp_path, [], _UI_OK)["summary"]
    assert s["api_steps"] == 0
    assert s["verdict"] != "PASS", "an empty journey is still being reported as a PASS"
    assert s["verdict"] == "NOT_WALKED", s["verdict"]


def test_a_walked_journey_still_passes(monkeypatch, tmp_path):
    """WITHOUT THIS THE FIX IS A REGRESSION: PASS must remain reachable."""
    s = _run(monkeypatch, tmp_path, _OK, _UI_OK)["summary"]
    assert s["api_steps"] == 1 and s["verdict"] == "PASS", s


def test_an_empty_journey_never_downgrades_a_real_finding(monkeypatch, tmp_path):
    """★ r185's own case. The new branch is last precisely so that evidence someone DID
    collect keeps its verdict — an absence of evidence must not outrank a finding."""
    s = _run(monkeypatch, tmp_path, [], _UI_FAIL)["summary"]
    assert s["api_steps"] == 0
    assert s["verdict"] == "ISSUES", (
        "the UI signup failure lost its verdict to the empty API journey: %s" % s["verdict"])
    assert s["ui_flows_failed_1203c6"] == 1


def test_an_incomplete_mcp_surface_still_reads_partial(monkeypatch, tmp_path):
    """Also unchanged, and for the same reason: PARTIAL names a real gap in the MCP
    surface, which an unwalked journey says nothing about."""
    s = _run(monkeypatch, tmp_path, [], _UI_OK, mcp_complete=False)["summary"]
    assert s["verdict"] == "PARTIAL", s["verdict"]


def test_the_cause_slot_names_the_unwalked_journey(monkeypatch, tmp_path):
    """The verdict has exactly two readers and both only LOG, so the sentence IS the
    mechanism. `describe_non_pass_1038`'s fallback would otherwise answer "no cause
    recorded (report a framework defect)" for a cause that is known and is not a defect."""
    r = _run(monkeypatch, tmp_path, [], _UI_OK)
    msg = TUV.describe_non_pass_1038(r["summary"], r.get("mcp"))
    assert "NOT WALKED" in msg.upper(), msg
    assert "no cause recorded" not in msg, msg
    assert "not a verdict about the app" in msg.lower(), msg


def test_it_is_said_even_when_something_else_is_broken(monkeypatch, tmp_path):
    """A reader deciding whether the app works needs to know the API half contributed no
    evidence either way, including on the reports that already name a UI finding — which
    is 65 of the 121 zero-step reports."""
    r = _run(monkeypatch, tmp_path, [], _UI_FAIL)
    msg = TUV.describe_non_pass_1038(r["summary"], r.get("mcp"))
    assert "BROKEN" in msg and "NOT WALKED" in msg.upper(), msg


def test_a_walked_journey_does_not_claim_it_was_unwalked(monkeypatch, tmp_path):
    """The equivalence the previous test could hide: the note is conditional on the count,
    not appended to every message."""
    r = _run(monkeypatch, tmp_path, _OK, _UI_FAIL)
    msg = TUV.describe_non_pass_1038(r["summary"], r.get("mcp"))
    assert "NOT WALKED" not in msg.upper(), msg


def test_the_fallback_still_exists_for_a_causeless_non_pass(monkeypatch, tmp_path):
    """#1035's lesson is still in force for the case it was written for: a non-PASS with
    steps walked and nothing flagged must not render an empty cause."""
    msg = TUV.describe_non_pass_1038({"api_steps": 2, "broken": [], "missing": []})
    assert msg.strip(), "the cause slot rendered empty"
    assert "no cause recorded" in msg, msg
