r"""#1203c6: `api_failed` counted the UI's broken flows, because `broken` was rebound.

    broken = [... for s in steps if s.get("kind") == "broken"]      # API only
    _ui_broken = [f"UI {f['flow']}: ..." for f in _uifl.get("flows", []) if not f.get("ok")]
    broken = broken + _ui_broken                                   # rebound: API + UI
    ...
    "api_failed": len(broken),                                     # read the rebound value

Its three siblings — `api_steps`, `api_passed`, `api_missing` — all come from `steps`. Only
`api_failed` did not, and the asymmetry inside one dict is the tell.

MEASURED over every persisted test-user report: 118 of 198 (59%), across 96 runs, carry an
`api_failed` the steps do not support, over by exactly 1 or 2 — the number of UI auth flows
(signup, login). Sharpest shape, in six runs: `api_steps: 0` with `api_failed: 2` — nothing
ran, and two things failed.

★ r146 is the live case and it misled ME within minutes of opening the file: M1.1 says
`api_steps: 2, api_passed: 2, api_failed: 2` while both steps carry `ok: true, kind: "ok"`.
Its M1.0 report says the same, so it reproduces.

★ NOTHING DECIDES ON IT — the verdict ladder reads the combined `broken` LIST, and
`describe_non_pass_1038` formats `broken`/`missing`. That is why it survived: a number nobody
computes with still misinforms every reader of the artifact, and this report is the one thing in
a run that claims to say what a new user would hit.

These tests drive `run_test_user_validation` itself, not the summary block in isolation — the
defect is in what the CALLER assembles, and I have repeatedly tested a helper instead of its
caller.
"""
import json
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.test_user_validation as TUV  # noqa: E402


def _run(monkeypatch, tmp_path, steps, ui_flows, mcp_complete=True):
    """Replace only the OUTSIDE WORLD (sockets, browser, MCP probe); every number under test is
    still computed by the real function."""
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
        return {"ran": True, "flows": list(ui_flows), "passed": all(
            f.get("ok") for f in ui_flows)}
    monkeypatch.setattr(TUV, "_ui_auth_flow", _flows)

    import multi_agent.runtime.validation_runner as VR
    monkeypatch.setattr(VR, "_service_host_port", lambda *a, **k: 8021, raising=False)

    return TUV.run_test_user_validation(tmp_path, [{"path": "/api/videos/feed"}],
                                        version="1.1.0")


_OK2 = [{"action": "create feed", "method": "POST", "path": "/api/videos/feed",
         "status": 200, "ok": True, "kind": "ok", "note": "author_id=10"},
        {"action": "list feed", "method": "GET", "path": "/api/videos/feed",
         "status": 200, "ok": True, "kind": "ok", "note": "persisted"}]
_UI_FAIL2 = [{"flow": "signup", "ok": False, "note": "landed on '/' which still shows sign in"},
             {"flow": "login", "ok": False, "note": "ERR_CONNECTION_REFUSED"}]


def test_r146s_green_api_is_not_reported_as_failed(monkeypatch, tmp_path):
    """★ The live case, verbatim: two steps, both ok, two broken UI flows."""
    s = _run(monkeypatch, tmp_path, _OK2, _UI_FAIL2)["summary"]
    assert s["api_steps"] == 2 and s["api_passed"] == 2, s
    assert s["api_failed"] == 0, s


def test_nothing_ran_so_nothing_failed(monkeypatch, tmp_path):
    """★ The absurd shape six runs actually persisted: `api_steps: 0, api_failed: 2`."""
    s = _run(monkeypatch, tmp_path, [], _UI_FAIL2)["summary"]
    assert s["api_steps"] == 0
    assert s["api_failed"] == 0, s


def test_a_real_api_failure_is_still_counted(monkeypatch, tmp_path):
    """The fix must not trade one wrong number for another — this is the direction that
    matters, and the direction a naive `api_failed: 0` would have broken."""
    steps = _OK2 + [{"action": "comment", "method": "POST", "path": "/api/videos/1/comments",
                     "status": 500, "ok": False, "kind": "broken", "note": "boom"}]
    s = _run(monkeypatch, tmp_path, steps, _UI_FAIL2)["summary"]
    assert s["api_failed"] == 1, s


def test_the_ui_count_is_not_lost(monkeypatch, tmp_path):
    """#1202z7's rule: a summary whose numbers do not add up reads as complete anyway. The UI
    failures leave `api_failed` and must land somewhere a reader can sum."""
    s = _run(monkeypatch, tmp_path, _OK2, _UI_FAIL2)["summary"]
    assert s["ui_flows_failed_1203c6"] == 2, s


def test_the_arithmetic_closes(monkeypatch, tmp_path):
    steps = _OK2 + [{"method": "POST", "path": "/x", "status": 500, "ok": False,
                     "kind": "broken", "note": "boom"}]
    s = _run(monkeypatch, tmp_path, steps, _UI_FAIL2)["summary"]
    assert s["api_failed"] + s["ui_flows_failed_1203c6"] == len(s["broken"]), s


def test_the_broken_list_is_unchanged(monkeypatch, tmp_path):
    """★ The combined list is what the verdict ladder and `describe_non_pass_1038` consume.
    Only the COUNT was wrong, so the list must still carry both kinds, UI last."""
    s = _run(monkeypatch, tmp_path, _OK2, _UI_FAIL2)["summary"]
    assert len(s["broken"]) == 2
    assert all(b.startswith("UI ") for b in s["broken"]), s["broken"]


def test_the_verdict_is_unchanged(monkeypatch, tmp_path):
    """A UI-only breakage still reads ISSUES — the ladder keys off the LIST, not the count,
    and this patch must not quietly downgrade a run to PARTIAL."""
    s = _run(monkeypatch, tmp_path, _OK2, _UI_FAIL2)["summary"]
    assert s["verdict"] == "ISSUES", s
    clean = _run(monkeypatch, tmp_path,
                 _OK2, [{"flow": "signup", "ok": True}, {"flow": "login", "ok": True}])["summary"]
    assert clean["verdict"] == "PASS", clean
    assert clean["api_failed"] == 0 and clean["ui_flows_failed_1203c6"] == 0


def test_the_message_formatter_is_unchanged(monkeypatch, tmp_path):
    """`describe_non_pass_1038` reads the lists; its output must be byte-identical."""
    s = _run(monkeypatch, tmp_path, _OK2, _UI_FAIL2)["summary"]
    txt = TUV.describe_non_pass_1038(s, {"complete": True})
    assert "UI signup" in txt and "UI login" in txt, txt


def test_the_persisted_report_carries_it(monkeypatch, tmp_path):
    """The artifact is the deliverable here — a reader opens the FILE, not the dict."""
    _run(monkeypatch, tmp_path, _OK2, _UI_FAIL2)
    d = json.loads((tmp_path / "test_user_reports" / "1.1.0.json").read_text(encoding="utf-8"))
    assert d["summary"]["api_failed"] == 0
    assert d["summary"]["ui_flows_failed_1203c6"] == 2


def test_api_failed_is_not_read_from_the_rebound_name():
    """★ Structural, so the next edit cannot re-introduce it: the value assigned to
    `api_failed` must not be `len(broken)` — `broken` is API+UI by the time the dict is built,
    and that single name serving two meanings IS the defect."""
    import ast
    import inspect

    src = inspect.getsource(TUV.run_test_user_validation)
    tree = ast.parse(src.lstrip())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and k.value == "api_failed":
                dumped = ast.dump(v)
                assert "'broken'" not in dumped and "id='broken'" not in dumped, dumped
                return
    raise AssertionError("the api_failed key is gone")
