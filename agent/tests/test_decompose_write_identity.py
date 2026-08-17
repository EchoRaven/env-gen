"""#453 (netflix r35/r38: decompose_reference FAILED x40/run = "write denied by
role gate: design/component_specs/<screen>.json"). The design_analyst IS allowed to
write design/** (ROUTING_TABLE), but decompose_reference self-gates on self._agent_id
— which set_hubs sets to the WRITE identity ('design_analyst') but set_team_protocols
→ inject_team_protocols then CLOBBERS back to the raw instance id ('design_analyst_1',
∉ the design/ writers set) for message routing, re-breaking the gate. FIX: set_hubs
also stashes the write identity under a dedicated _write_agent_id that team-injection
never touches; the tool gates on _write_agent_id (fallback _agent_id). Generalizable
to any dynamic-suffixed self-gating agent. Locks it in."""
import asyncio

from env_generator.llm_generator.tools import material_prep_tools
from env_generator.llm_generator.tools.material_prep_tools import DecomposeReferenceTool


def _run(coro):
    """Run a coroutine without polluting the process event-loop state. asyncio.run()
    leaves set_event_loop(None), which breaks sibling tests that use the deprecated
    asyncio.get_event_loop() — so we manage our own loop and restore a fresh, open
    current loop afterward."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


class _FakeWS:
    """Records the identity the tool passes to the write-gate; allows only the
    resolved PROFILE id (mirrors PathRoutedWorkspace: instance id ∉ writers)."""
    def __init__(self, tmp):
        self.tmp = tmp
        self.gate_calls = []

    def resolve(self, rel):
        p = self.tmp / rel
        return p

    def is_write_allowed(self, dest, agent_id):
        self.gate_calls.append(agent_id)
        return agent_id == "design_analyst"  # profile allowed, instance id denied


def _mk_tool(tmp, monkeypatch):
    # stub the vision call so execute reaches the write-gate deterministically
    async def _fake_decompose(path, llm):
        return {"components": [{"id": "hero", "role": "billboard",
                                "colors": {"bg": "#141414"}}]}
    monkeypatch.setattr(material_prep_tools.mp, "decompose_reference", _fake_decompose)
    ws = _FakeWS(tmp)
    img = tmp / "design" / "references" / "login.png"
    img.parent.mkdir(parents=True, exist_ok=True)
    img.write_bytes(b"\x89PNG\r\n\x1a\n")  # existence is all execute checks
    tool = DecomposeReferenceTool(workspace=ws, llm_client=object())
    return tool, ws


def test_gate_uses_write_identity_not_instance_id(tmp_path, monkeypatch):
    tool, ws = _mk_tool(tmp_path, monkeypatch)
    # set_hubs stashes the WRITE identity; inject_team_protocols clobbers _agent_id
    tool._agent_id = "design_analyst_1"          # instance id (post-clobber)
    tool._write_agent_id = "design_analyst"       # #453 dedicated write identity
    res = _run(tool.execute(image="design/references/login.png"))
    assert res.success, f"write should be allowed via the profile identity: {res.error_message if not res.success else ''}"
    assert ws.gate_calls == ["design_analyst"], "gate must receive the profile id, not the instance id"
    assert (tmp_path / "design" / "component_specs" / "login.json").exists()


def test_falls_back_to_agent_id_when_no_write_identity(tmp_path, monkeypatch):
    # plain Workspace / early-init / tests: no _write_agent_id → fall back to _agent_id
    tool, ws = _mk_tool(tmp_path, monkeypatch)
    tool._agent_id = "design_analyst"  # a plain (unsuffixed) id still resolves
    res = _run(tool.execute(image="design/references/login.png"))
    assert res.success and ws.gate_calls == ["design_analyst"]


def test_instance_id_without_write_identity_is_denied(tmp_path, monkeypatch):
    # the pre-#453 bug scenario: only the clobbered instance id present → denied
    tool, ws = _mk_tool(tmp_path, monkeypatch)
    tool._agent_id = "design_analyst_1"
    # no _write_agent_id
    res = _run(tool.execute(image="design/references/login.png"))
    assert not res.success and "denied" in (res.error_message or "").lower()



def test_decompose_caches_repeated_image_464(tmp_path, monkeypatch):
    """#464: the deterministic per-image vision decompose is cached within a run —
    the design_analyst re-decomposes the same screens many times; the repeats must
    reuse the first result (no redundant vision call)."""
    from env_generator.llm_generator.tools import material_prep_tools as MPT
    MPT._DECOMPOSE_MEM_CACHE.clear()  # isolate from other tests
    calls = {"n": 0}
    async def _counting_decompose(path, llm):
        calls["n"] += 1
        return {"components": [{"id": "hero", "role": "billboard"}]}
    monkeypatch.setattr(MPT.mp, "decompose_reference", _counting_decompose)
    ws = _FakeWS(tmp_path)
    img = tmp_path / "design" / "references" / "browse.png"
    img.parent.mkdir(parents=True, exist_ok=True)
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    tool = MPT.DecomposeReferenceTool(workspace=ws, llm_client=object())
    tool._write_agent_id = "design_analyst"
    r1 = _run(tool.execute(image="design/references/browse.png"))
    r2 = _run(tool.execute(image="design/references/browse.png"))  # same image → cached
    assert r1.success and r2.success
    assert calls["n"] == 1, "vision call must run ONCE (second call cached)"
    MPT._DECOMPOSE_MEM_CACHE.clear()

if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
