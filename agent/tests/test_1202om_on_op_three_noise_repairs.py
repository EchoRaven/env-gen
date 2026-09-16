"""#1202om/#1202on/#1202op — three repairs for framework noise that costs lane time.

#1202om  `detect_breaking_change` compared declared types as raw strings, so re-registering
         `'is_read': 'bool'` as `'boolean'` minted a type_changed_fields event, an urgent
         message to every consumer and a P0 titled "Fix breaking change in <endpoint>".
         Measured: r125 filed 199 such tasks — 25% of ALL its tasks, 140 at the frontend;
         r124 77; r126 19.
#1202on  The debugger's triage wake opened a full agentic loop (system prompt, up to 30 steps)
         without asking whether anything was open. Its own transcripts: r125 229 cycles, 134
         (58%) ended in a finish() saying there was nothing to do, 80 with an empty queue;
         r124 75/155; r126 19/37.
#1202op  One coverage report named one file two ways — `dead_files` relative to the app tree
         (`frontend/src/pages/MessagesPage.jsx`, which resolves from no lane's cwd) and
         `pages_without_files` relative to the output root (`app/frontend/...`). r125's
         frontend lane spent five consecutive P0s on that confusion.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import coverage_audit as CA  # noqa: E402
from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _rh(tmp_path):
    return HubRegistry(tmp_path).registryhub


def test_1202om_the_same_type_spelled_two_ways_is_not_a_breaking_change(tmp_path):
    rh = _rh(tmp_path)
    old = {"response": {"is_read": "bool", "count": "int", "name": "str", "at": "datetime"}}
    new = {"response": {"is_read": "boolean", "count": "integer", "name": "string",
                        "at": "timestamp"}}
    out = rh.detect_breaking_change(old, new)
    assert out["type_changed_fields"] == [], out
    assert out["is_breaking"] is False, out


def test_1202om_a_real_type_change_is_still_breaking(tmp_path):
    rh = _rh(tmp_path)
    out = rh.detect_breaking_change({"response": {"count": "int", "tags": "list"}},
                                    {"response": {"count": "str", "tags": "array"}})
    assert out["type_changed_fields"] == ["count"], out       # tags list→array is one type
    assert out["is_breaking"] is True


def test_1202om_optionality_still_counts(tmp_path):
    rh = _rh(tmp_path)
    out = rh.detect_breaking_change({"response": {"x": "int"}}, {"response": {"x": "int?"}})
    assert out["type_changed_fields"] == ["x"], out


def test_1202on_an_empty_bug_queue_does_not_open_a_loop():
    from multi_agent.agents.runtime.messaging import AgentMessaging as M
    agent = SimpleNamespace(_hubs=SimpleNamespace(workhub=SimpleNamespace(
        list_open_bugs=lambda: [])))
    assert M._open_bugs_to_triage_1202on(agent) == []
    agent2 = SimpleNamespace(_hubs=SimpleNamespace(workhub=SimpleNamespace(
        list_open_bugs=lambda: [{"id": "bug1"}])))
    assert M._open_bugs_to_triage_1202on(agent2) == [{"id": "bug1"}]


def test_1202on_it_fails_open_so_a_triage_is_never_silently_dropped():
    from multi_agent.agents.runtime.messaging import AgentMessaging as M

    def _boom():
        raise RuntimeError("hub unreadable")

    for hubs in (None,
                 SimpleNamespace(workhub=None),
                 SimpleNamespace(workhub=SimpleNamespace()),
                 SimpleNamespace(workhub=SimpleNamespace(list_open_bugs=_boom))):
        assert M._open_bugs_to_triage_1202on(SimpleNamespace(_hubs=hubs)), hubs


def _triage_agent(open_bugs):
    """A stand-in with exactly what `_handle_bug_triage` touches, recording the expensive call."""
    from multi_agent.agents.runtime.messaging import AgentMessaging as M

    class _A(M):
        def __init__(self):
            self.agent_id = "debugger"
            self._logger = SimpleNamespace(info=lambda *a, **k: None,
                                           error=lambda *a, **k: None)
            self._hubs = SimpleNamespace(workhub=SimpleNamespace(
                list_open_bugs=lambda: list(open_bugs)))
            self._processing_state = "idle"
            self.loops = 0

        def _compose_system_prompt(self):
            return "sys"

        async def run_agentic_loop(self, **kw):
            self.loops += 1

        async def _drain_deferred_task_ready_messages(self):
            return None

    return _A()


def test_1202on_the_handler_does_not_pay_for_an_empty_queue():
    """Behavioural: the expensive loop must not run — not merely be preceded by a check."""
    import asyncio
    msg = SimpleNamespace(metadata={"msg_type": "bug_found"}, payload="a bug was filed")
    empty = _triage_agent([])
    asyncio.run(empty._handle_bug_triage(msg))
    assert empty.loops == 0
    busy = _triage_agent([{"id": "bug1", "priority": "P0"}])
    asyncio.run(busy._handle_bug_triage(msg))
    assert busy.loops == 1


def test_1202op_one_report_names_a_file_one_way(tmp_path, monkeypatch):
    """Behavioural: through `compute_coverage`, the reader the lane is handed."""
    pages = tmp_path / "app" / "frontend" / "src" / "pages"
    pages.mkdir(parents=True)
    (tmp_path / "app" / "backend").mkdir(parents=True)
    (pages / "MessagesPage.jsx").write_text("export default function MessagesPage(){}\n")
    monkeypatch.setattr(CA, "scan_dead_files",
                        lambda root: [{"path": "frontend/src/pages/MessagesPage.jsx"}])
    monkeypatch.setattr(CA, "scan_pages_without_files", lambda hub, root: [])
    monkeypatch.setattr(CA, "scan_dead_endpoints", lambda hub: [])
    monkeypatch.setattr(CA, "scan_dead_tables", lambda hub: [], raising=False)
    report = CA.compute_coverage(SimpleNamespace(), tmp_path)
    assert [r["path"] for r in report.dead_files] == [
        "app/frontend/src/pages/MessagesPage.jsx"], report.dead_files


def test_1202op_an_ambiguous_layout_is_left_exactly_as_before(tmp_path, monkeypatch):
    monkeypatch.setattr(CA, "scan_dead_files", lambda root: [{"path": "src/x.jsx"}])
    assert CA._dead_files_from_decl_root_1202op(tmp_path, tmp_path) == [{"path": "src/x.jsx"}]
