r"""#702: a whole step-pipeline stage has never run, and cannot as wired.

Sweep D of the "computed but never consumed" family: class METHODS whose name appears only at
their own `def`. Sweep B did module-level functions (#699, #700); this is its completion. 113
hits, most of them false positives where a framework calls by convention rather than by name
(`do_POST`, `log_message`). One is a step-pipeline stage.

Three sibling stages live in the same mixin. Two are wired:

    _run_retrieve_context_stage   2 call sites
    _run_knowledge_sync_stage     1 call site
    _run_hub_sync_stage           0

And it is inert three ways over, not one:

  1. `step_runner.py:146` initialises `hub_sync_tool_names: set = set()` and nothing ever adds
     to it — no `.add`, no reassignment anywhere in the tree.
  2. That always-empty set is still threaded into `action.py:290`'s
     `... | knowledge_store_names | hub_sync_tool_names`, a union contributing nothing.
  3. `step_runner` never calls the stage, so even its own `executed=False, skip_reason=...`
     branch never fires. The pipeline does not know the stage exists.

No run has executed it: no call site, no `hub_sync` entry in any step trace, and the 56 log files
that look like they mention it are all matching the tail of the unrelated `registryhub_sync` —
a substring false positive caught by dumping the actual matches instead of trusting the count.

Wiring it up is a real behaviour change (hub-sync tool calls at every step boundary is a per-step
token cost, #257) and is deliberately not done here. What is fixed is that a reader could open
stages.py and reasonably conclude hub state is synchronised each step.
"""
import ast
import inspect
import re
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime.step_pipeline import stages as st


def _root() -> Path:
    root = Path(st.__file__).resolve().parents[4]   # step_pipeline/runtime/agents/multi_agent -> llm_generator
    assert root.name == "llm_generator", root
    return root


def _doc() -> str:
    return st.AgentStepStageMixin._run_hub_sync_stage.__doc__ or ""


# --- the three claims, each checked against the tree ---------------------------------------------

def test_the_stage_has_no_call_site():
    """If somebody wires it, this fails and the docstring must be corrected with it."""
    calls = 0
    for p in _root().rglob("*.py"):
        src = p.read_text(errors="ignore")
        for m in re.finditer(r"\b_run_hub_sync_stage\s*\(", src):
            ls = src.rfind("\n", 0, m.start()) + 1
            if src[ls:m.start()].strip().startswith(("def", "async def")):
                continue
            calls += 1
    assert calls == 0, f"the stage now has {calls} call site(s)"


def test_its_wired_siblings_do_have_call_sites():
    """Negative control: the probe must be able to see a wired stage."""
    for name in ("_run_retrieve_context_stage", "_run_knowledge_sync_stage"):
        calls = 0
        for p in _root().rglob("*.py"):
            src = p.read_text(errors="ignore")
            for m in re.finditer(r"\b" + name + r"\s*\(", src):
                ls = src.rfind("\n", 0, m.start()) + 1
                if src[ls:m.start()].strip().startswith(("def", "async def")):
                    continue
                calls += 1
        assert calls > 0, f"{name} should be wired"


def test_the_tool_name_set_is_never_populated():
    """An empty set makes the stage a no-op even if it were called."""
    runner = _root() / "multi_agent" / "agents" / "runtime" / "step_runner.py"
    src = runner.read_text(errors="ignore")
    assert "hub_sync_tool_names: set = set()" in src
    assert not re.search(r"hub_sync_tool_names\s*\.\s*(add|update)\s*\(", src)
    # AST, not regex. `hub_sync_tool_names=hub_sync_tool_names,` on its own line is a KEYWORD
    # ARGUMENT and matches every text-level "assignment" pattern I tried, anchored or not.
    # Only the parser can tell an Assign target from a call keyword.
    tree = ast.parse(src)
    assigns = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            for t in targets:
                if isinstance(t, ast.Name) and t.id == "hub_sync_tool_names":
                    assigns.append(ast.dump(n.value) if n.value is not None else "None")
    assert len(assigns) == 1, assigns
    assert "set" in assigns[0] and "Constant" not in assigns[0], assigns[0]


def test_the_empty_set_is_still_threaded_into_the_union():
    action = _root() / "multi_agent" / "agents" / "runtime" / "step_pipeline" / "action.py"
    assert "hub_sync_tool_names" in action.read_text(errors="ignore")


# --- the stage itself is untouched ------------------------------------------------------------------

def test_the_stage_still_exists_and_is_async():
    fn = st.AgentStepStageMixin._run_hub_sync_stage
    assert inspect.iscoroutinefunction(fn)


def test_its_skip_branch_is_unchanged():
    src = inspect.getsource(st.AgentStepStageMixin._run_hub_sync_stage)
    assert "if not enabled or not hub_sync_tool_names:" in src
    assert 'skip_reason="disabled_by_config" if not enabled else "tools_unavailable"' in src


def test_nothing_was_deleted():
    src = inspect.getsource(st.AgentStepStageMixin._run_hub_sync_stage)
    assert "do_hub_sync" in src


def test_the_module_still_parses():
    ast.parse(Path(st.__file__).read_text())


# --- provenance ---------------------------------------------------------------------------------------

def test_the_three_way_inertness_is_recorded():
    d = " ".join(_doc().split())
    assert "inert three ways over" in d
    assert "NOTHING ever adds to it" in d
    assert "does not know the stage exists" in d


def test_the_sibling_comparison_is_recorded():
    d = _doc()
    assert "_run_retrieve_context_stage" in d and "_run_knowledge_sync_stage" in d


def test_the_substring_false_positive_is_recorded():
    d = " ".join(_doc().split())
    assert "registryhub_sync" in d


def test_the_behaviour_change_is_explicitly_deferred():
    d = " ".join(_doc().split())
    assert "deliberately NOT done here" in d
    assert "257" in d


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
