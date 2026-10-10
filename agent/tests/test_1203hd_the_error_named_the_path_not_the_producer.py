r"""#1203hd: "Task suite not found" named what was asked for and never what makes one.

```python
        suite_file = self.workspace.resolve(suite_path)
        if not suite_file.exists():
            return ToolResult.fail(f"Task suite not found: {suite_path}")
```

★ CONDITIONAL, AND THE DENOMINATOR COMES FIRST. Time-sliced, the last
`🔧 execute_task_suite` invocation in the corpus is 2026-09-24 and there have been ZERO
since — so every figure below is HISTORICAL. The path is still reachable: the tool is
granted in four places in `agents_config` and r175 offered it in four tool deltas on
2026-10-10; agents simply stopped choosing it. These tests therefore guard a correct,
zero-risk message on a live-but-unexercised path. Not firing is not failure, and this
is not a current defect.

The sweep that found it ranks tools by ✅/❌ over the WHOLE corpus and is not
time-sliced, which is exactly how a dormant path reads like a live one — the same slice
killed a seventh patch before it was written (`codehub_get_file_content`'s
`PR not found: main`, 230 occurrences, last one 07-29, fixed by #1123 on 08-26).

MEASURED, all of it before 09-24. `execute_task_suite` was called 211 times and failed
167 of those. 155 of the failures are this exact default path, `tasks/tasks.yaml`, across 34
logs; 7 more are invented paths — `tasks/isolation.yaml`,
`validation/business_chains.yaml`, `.registry/verification_chains.yaml`,
`registry/verification_chains.yaml`, `tasks/business_chain.yaml` — which is what an agent
does when the error gives it nothing to act on.

Meanwhile `save_task_suite` — the PRODUCER, one of the five `task_definition_tools`,
granted to the verifier — has been called ZERO times, and so have its four siblings
(`define_task`, `validate_task`, `list_task_definitions`, `delete_task`: 0 each). Agents
reach for the EXECUTOR 211 times and never once for the producer. Only 3 corpus runs
(r71, r74, r92, all pre-r100) have ever had a `tasks/tasks.yaml` on disk.

★ THE FRAMEWORK ALREADY KNEW. `delivery_gate` carries the finding verbatim: "the branch
is dead by agent choice, not by a missing grant, and it is dead in 172 of 172 runs". The
knowledge existed one module over and never reached the agent standing in front of the
locked door — the same shape as #1203ha and #1203h9, and as #748 before them.

★ CONSEQUENCE, STATED NOT SLIPPED IN. Three delivery-gate checks are gated on
`task_suite_exists` and have never fired in 298 logs; with no suite,
`api_smoke_pass`/`ui_smoke_pass` are computed and enforced by nobody (#1202ze: 86
evaluations in 27 runs read `ok: true` beside a FALSE smoke, 22 at the release cut). If
suites begin to exist, that enforcement switches on. This patch makes the producer
discoverable; it does not create a suite.
"""
import asyncio
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _AGENT)
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from tools.task_suite_executor import ExecuteTaskSuiteTool  # noqa: E402


class _WS:
    def __init__(self, root):
        self.base_root = root

    def resolve(self, rel):
        return self.base_root / str(rel)


def _run(tmp_path, suite_path="tasks/tasks.yaml"):
    tool = ExecuteTaskSuiteTool(workspace=_WS(tmp_path))
    return asyncio.run(tool.execute(suite_path=suite_path))


def _msg(res):
    for attr in ("error_message", "error", "message"):
        v = getattr(res, attr, None)
        if isinstance(v, str) and v:
            return v
    return str(getattr(res, "data", "") or res)


def test_the_path_asked_for_is_still_reported(tmp_path):
    """★ The evidence leads; the explanation is additive."""
    m = _msg(_run(tmp_path))
    assert "Task suite not found" in m, m
    assert "tasks/tasks.yaml" in m, m


def _sentence_with(text, phrase):
    """The sentence carrying `phrase`, so an assertion is pinned to its own clause.

    ★ Two of these tests first asserted a bare substring and stayed GREEN under mutation:
    `save_task_suite` appears TWICE in the hint, so deleting the clause that INTRODUCES it
    left the other mention standing, and a `nothing has saved ... or none of those has
    been called` disjunction survived deleting either half. A substring present somewhere
    in a blob proves nothing about the clause that was supposed to carry it.
    """
    low = text.lower()
    at = low.find(phrase.lower())
    if at < 0:
        return ""
    starts = [low.rfind(sep, 0, at) for sep in (". ", "— ", "\n")]
    begin = max(starts) if max(starts) >= 0 else 0
    ends = [low.find(sep, at) for sep in (". ", "; ", "\n")]
    ends = [e for e in ends if e > at]
    return text[begin:(min(ends) if ends else len(text))]


def test_it_names_the_tool_that_creates_one(tmp_path):
    """★ THE defect: 211 calls to the executor, 0 to the producer. Anchored to the clause
    that INTRODUCES the producer, not to any mention of its name."""
    m = _msg(_run(tmp_path))
    created = _sentence_with(m, "is CREATED by")
    assert created, m
    assert "save_task_suite" in created, created


def test_it_names_the_producers_siblings_too(tmp_path):
    """`save_task_suite` alone is half the workflow: a suite has to be DEFINED before it
    can be saved, and all five tools sit unused at 0 calls each."""
    m = _msg(_run(tmp_path))
    created = _sentence_with(m, "is CREATED by")
    assert "define_task" in created, created


def test_it_says_nobody_has_saved_one_at_that_path(tmp_path):
    """"Not found" reads as "you typed the wrong path". One of the two facts the agent
    needs; `test_it_says_the_producer_was_never_called` asserts the other, separately,
    because a disjunction over the two survived deleting either."""
    m = _msg(_run(tmp_path)).lower()
    assert "nothing has saved a suite" in m, m


def test_it_says_the_producer_was_never_called(tmp_path):
    """The second fact: not merely that the file is absent, but that no step in this run
    was ever going to create it."""
    m = _msg(_run(tmp_path)).lower()
    assert "none of those has been called" in m, m


def test_it_offers_the_other_way_out(tmp_path):
    """A prohibition without an alternative leaves the agent looping. Saying the matrix
    was not exercised is a legitimate outcome — staying silent is how 2379 tools came to
    be marked implemented without one ever being invoked."""
    m = _msg(_run(tmp_path)).lower()
    assert "not exercised" in m, m


def test_it_tells_the_agent_to_stop_guessing_paths(tmp_path):
    """7 of the 167 failures are invented paths. There is exactly one writer."""
    m = _msg(_run(tmp_path)).lower()
    assert "do not guess" in m, m


def test_a_custom_path_gets_the_same_help(tmp_path):
    """The 7 invented paths must reach the same answer as the default, or the hint helps
    only the agents that happened to guess nothing."""
    m = _msg(_run(tmp_path, suite_path=".registry/verification_chains.yaml"))
    assert ".registry/verification_chains.yaml" in m, m
    assert "save_task_suite" in m, m


def test_a_suite_that_exists_gets_no_hint(tmp_path):
    """★ The hint belongs to the missing-file path only. A suite that is present must not
    be editorialised — and this also proves the branch is reachable both ways."""
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "tasks.yaml").write_text("tasks: []\n")
    res = _run(tmp_path)
    blob = _msg(res) + str(getattr(res, "data", "") or "")
    assert "save_task_suite" not in blob, blob


def test_it_adds_no_retry_or_fallback():
    """★ The user's standing rule: the call still fails, with the same cause. No search
    over candidate paths, no suite invented on the fly."""
    import ast
    import inspect

    src = inspect.getsource(ExecuteTaskSuiteTool.execute)
    tree = ast.parse(src.lstrip())
    found = None
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            seg = ast.get_source_segment(src.lstrip(), node) or ""
            if "Task suite not found" in seg:
                found = node
                break
    assert found is not None, "the not-found branch is gone"
    for node in ast.walk(found):
        assert not isinstance(node, (ast.For, ast.While)), "a path search appeared"
