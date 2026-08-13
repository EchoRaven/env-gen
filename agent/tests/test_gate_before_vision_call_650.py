r"""#650: the role gate ran after the vision call, so a denial cost 12 seconds and a vision call.

Found while testing the last of eight constants I had called "unmeasurable" — a `429` grep turned
out to be UUID fragments (no throttling in 56 runs), but the same pass surfaced this:

    decompose_reference FAILED (12405ms): write denied by role gate: design/component_specs/landing.json

    12 denials across 6 of 56 runs, every one from `design_analyst_1`

The ordering was: resolve the image → **run the vision decomposition** → compute the destination →
check the write gate → deny. So ~12s and a full vision call's tokens were spent on work that was
never allowed to land. The destination is knowable before any of it: `save_as` defaults from the
image name.

Same shape as #634 — validate the call before making it. The allowed path is byte-identical; only
the denied path gets cheaper. The message also says what the analyst could not know: the framework
decomposes every reference itself, so `design/component_specs/` needs nothing from it.

(The denials all naming `design_analyst_1` is the instance-id shape #453 exists to handle. Whether
those runs predate that fix is not decidable from the artifacts, and #650 is correct either way:
a legitimate denial should also be cheap.)
"""
from pathlib import Path

import pytest

from env_generator.llm_generator.tools.material_prep_tools import DecomposeReferenceTool


class _WS:
    def __init__(self, root, allowed=True):
        self.root = Path(root)
        self.allowed = allowed
        self.checked = []

    def resolve(self, rel):
        return self.root / rel

    def is_write_allowed(self, dest, agent):
        self.checked.append((str(dest), agent))
        return self.allowed


class _LLM:
    pass


def _tool(tmp_path, allowed=True):
    t = DecomposeReferenceTool.__new__(DecomposeReferenceTool)
    t.workspace = _WS(tmp_path, allowed)
    t._llm = _LLM()
    t._write_agent_id = "design_analyst"
    (tmp_path / "design" / "references").mkdir(parents=True, exist_ok=True)
    (tmp_path / "design" / "references" / "landing.png").write_bytes(b"x")
    return t


def _run(tool, **kw):
    import asyncio
    return asyncio.run(tool.execute(image="design/references/landing.png", **kw))


# --- the denial is now free -----------------------------------------------------------------

def test_a_denied_write_never_reaches_the_vision_call(tmp_path, monkeypatch):
    """The whole fix: 12s and a vision call used to be spent before the gate said no."""
    called = []
    # patch the module object the TOOL holds: it imported material_prep under a
    # different sys.path prefix, so the two are distinct objects in sys.modules.
    from env_generator.llm_generator.tools import material_prep_tools as mpt

    async def _spy(*a, **k):
        called.append(1)
        return {"components": [], "count": 0}

    monkeypatch.setattr(mpt.mp, "decompose_reference", _spy)
    res = _run(_tool(tmp_path, allowed=False))
    assert res.success is False
    assert called == [], "the vision call must not run when the write is already refused"


def test_the_denial_still_names_the_path(tmp_path):
    res = _run(_tool(tmp_path, allowed=False))
    assert "design/component_specs/landing.json" in res.error_message


def test_it_says_nothing_was_spent(tmp_path):
    res = _run(_tool(tmp_path, allowed=False))
    assert "BEFORE the vision call" in res.error_message
    assert "nothing was spent" in res.error_message


def test_it_tells_the_analyst_the_framework_already_does_this(tmp_path):
    """A true-but-unactionable error is the #623/#634 class; this one says what to do instead."""
    res = _run(_tool(tmp_path, allowed=False))
    assert "written by the framework's own decomposition pass" in res.error_message


def test_an_agent_chosen_destination_is_gated_too(tmp_path):
    """`save_as` is agent-controllable — the pre-check must use it, not just the default."""
    t = _tool(tmp_path, allowed=False)
    _run(t, save_as="app/backend/main.py")
    assert t.workspace.checked and t.workspace.checked[0][0].endswith("app/backend/main.py")


def test_the_write_identity_is_the_resolved_profile(tmp_path):
    """#453: `_agent_id` is clobbered to the instance id; the gate must see the profile."""
    t = _tool(tmp_path, allowed=False)
    t._agent_id = "design_analyst_1"
    _run(t)
    assert t.workspace.checked[0][1] == "design_analyst"


# --- the allowed path is unchanged ---------------------------------------------------------------

def test_an_allowed_write_still_runs_and_saves(tmp_path, monkeypatch):
    # patch the module object the TOOL holds: it imported material_prep under a
    # different sys.path prefix, so the two are distinct objects in sys.modules.
    from env_generator.llm_generator.tools import material_prep_tools as mpt

    async def _ok(*a, **k):
        return {"components": [{"name": "nav"}], "count": 1}

    monkeypatch.setattr(mpt.mp, "decompose_reference", _ok)
    res = _run(_tool(tmp_path, allowed=True))
    assert res.success is True
    assert (tmp_path / "design" / "component_specs" / "landing.json").is_file()


def test_a_workspace_without_a_gate_is_unaffected(tmp_path, monkeypatch):
    """Plain Workspace (early init / tests) has no is_write_allowed — must not block."""
    # patch the module object the TOOL holds: it imported material_prep under a
    # different sys.path prefix, so the two are distinct objects in sys.modules.
    from env_generator.llm_generator.tools import material_prep_tools as mpt

    async def _ok(*a, **k):
        return {"components": [], "count": 0}

    monkeypatch.setattr(mpt.mp, "decompose_reference", _ok)
    t = _tool(tmp_path)
    t.workspace = type("NoGate", (), {"root": tmp_path,
                                      "resolve": lambda self, r: tmp_path / r})()
    assert _run(t).success is True


# --- ordering, pinned ----------------------------------------------------------------------------

def test_the_gate_precedes_the_decomposition_in_source():
    import inspect
    src = inspect.getsource(DecomposeReferenceTool.execute)
    assert src.index("is_write_allowed") < src.index("mp.decompose_reference")


def test_the_measurement_is_recorded():
    import inspect
    flat = " ".join(inspect.getsource(DecomposeReferenceTool.execute).replace("#", " ").split())
    assert "12 denials in 6 runs" in flat and "12405ms" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
