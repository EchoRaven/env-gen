"""#1203gq: the MCP step told the agent to run a shell line; it concluded it had no shell.

r170 confirmed the half of #1203gk that matters — the mcp test-user cited the briefing and did
NOT file a lane defect, so the chain that broke r166's stack never started. But it then
stopped: "the provided tool surface for this run exposes no shell/background execution tool to
start mcp_server/app/start.sh". That is false. The persona carries the `runtime_full` bundle.

So the step names the tool now. These tests pin BOTH halves: the copy names `run_background`,
and `run_background` is really in this persona's bundle — the mirror of #1203fz, where copy
named a tool that did not exist.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
SQUAD = (LLM_DIR / "multi_agent" / "runtime" / "test_user_squad.py").read_text(encoding="utf-8")
CONFIG = (LLM_DIR / "multi_agent" / "agents" / "agents_config.yaml").read_text(encoding="utf-8")
BUNDLES = (LLM_DIR / "multi_agent" / "tool_bundles.py").read_text(encoding="utf-8")
RUNTIME = (LLM_DIR / "tools" / "runtime_tools.py").read_text(encoding="utf-8")

NAMED = ("run_background", "execute_bash", "get_process_output", "wait_for_process",
         "list_processes")


def _mcp_goal_text():
    """The mcp_parity goal dict's goal + steps, as the planner emits them."""
    import sys
    for p in (str(ROOT), str(LLM_DIR)):
        if p not in sys.path:
            sys.path.insert(0, p)
    from multi_agent.runtime.test_user_squad import build_briefing, plan_test_user_goals
    eps = [{"method": "GET", "path": "/api/videos", "response_key": "items"},
           {"method": "POST", "path": "/api/videos", "response_key": "item"}]
    goals = plan_test_user_goals(business_eps=eps, ui_pages=[], tables={}, feature_inventory={},
                                mcp_present=True, max_goals=24)
    g = next(x for x in goals if x.get("kind") == "mcp_parity")
    return build_briefing(g, ui_base="http://localhost:3000", api_base="http://localhost:8029")


def _goal_and_steps():
    """The GOAL paragraph and the STEP HINTS block, separately — a mutation that strips the
    tool out of one must not be masked by the other still carrying it."""
    b = _mcp_goal_text()
    i, j = b.index("GOAL:"), b.index("STEP HINTS:")
    return b[i:j], b[j:]


def test_the_step_names_the_tool_it_wants_called():
    _goal, steps = _goal_and_steps()
    assert "run_background" in steps, steps


def test_the_goal_also_says_the_agent_has_them():
    goal, _steps = _goal_and_steps()
    assert "run_background" in goal, goal
    assert re.search(r"You have the tools to start it", goal), goal


def test_the_step_asserts_the_capability_rather_than_implying_it():
    """A bare shell line asks the reader to infer shell access; r170's reader inferred the
    opposite and stopped. The step must say it outright."""
    _goal, steps = _goal_and_steps()
    assert re.search(r"you HAVE it", steps), steps


def test_every_tool_THE_COPY_names_really_exists():
    """#1203fz's rule, applied to my own copy — and applied to what the copy ACTUALLY says.

    The first version of this asserted that a hardcoded list of tool names exists in
    runtime_tools.py. That validates a constant, not the briefing: a mutation replacing the
    copy's `run_background` with `spawn_server` left it green. Extract the backticked
    identifiers FROM the briefing and require each to be a real tool NAME.
    """
    real = set(re.findall(r'^\s*NAME\s*=\s*"([a-z_0-9]+)"', RUNTIME, re.M))
    assert "run_background" in real, sorted(real)          # the universe is non-empty
    b = _mcp_goal_text()
    # Backticked identifiers CARRYING AN UNDERSCORE: every runtime tool name has one, while
    # the briefing's other backticked words do not (`password`, the seeded demo password, was
    # the first false positive this caught). A fabricated `spawn_server` still matches, which
    # is what keeps this falsifiable.
    named = {m for m in re.findall(r"`([a-z][a-z0-9]*_[a-z0-9_]+)`", b)
             if not m.endswith(".sh") and "/" not in m}
    assert named, b
    unknown = sorted(n for n in named if n not in real)
    assert not unknown, ("the copy names tools that do not exist: %s" % unknown)


def test_the_named_tools_reach_this_persona():
    """And the persona must actually carry the bundle that provides them, or the copy is
    naming something the reader does not have — the defect #1203fz fixed."""
    # ★地标锚点, 不是字节窗口(#943): persona 块切到下一个同缩进的 `  <name>:` 键,
    # bundle 函数切到下一个 `def ` —— 两者都不随注释长短漂移。
    i = CONFIG.index("mcp_test_user:")
    nxt = re.search(r"\n  [a-z_][a-z_0-9]*:\n", CONFIG[i + len("mcp_test_user:"):])
    block = CONFIG[i:i + len("mcp_test_user:") + (nxt.start() if nxt else len(CONFIG))]
    assert "runtime_full" in block, block
    j = BUNDLES.index("def _bundle_runtime_full")
    k = BUNDLES.index("\ndef ", j + 1)
    body = BUNDLES[j:k]
    for cls in ("ExecuteBashTool", "RunBackgroundTool", "GetProcessOutputTool"):
        assert cls in body, (cls, body)


def test_every_tool_the_copy_names_is_on_this_persona_turns_MENU():
    """#1203gs: the POOL is not the MENU, and the test above only checked the pool.

    `test_the_named_tools_reach_this_persona` asserts the persona carries the BUNDLE that
    provides the tools. That is necessary and not sufficient: what the model sees in a turn is
    `stage_tool_allowlist[stage]` (step_pipeline/tooling.py: stage_allow -> candidate_names ->
    rank_tool_names). r171 read `tools=15` on every request for this persona -- exactly the
    allowlist's length -- and the agent answered that the start tool was "not in this session's
    tool namespace", which was true. So the copy's promise has to be checked against the menu.

    If the persona has no allowlist its whole pool is offered and there is nothing to check.
    """
    import yaml
    cfg = yaml.safe_load(CONFIG)
    prof = cfg["profiles"]["mcp_test_user"]
    allow = prof.get("stage_tool_allowlist")
    if not allow:
        pytest.skip("mcp_test_user has no stage_tool_allowlist; the full pool is offered")
    real = set(re.findall(r'^\s*NAME\s*=\s*"([a-z_0-9]+)"', RUNTIME, re.M))
    b = _mcp_goal_text()
    named = {m for m in re.findall(r"`([a-z][a-z0-9]*_[a-z0-9_]+)`", b)
             if not m.endswith(".sh") and "/" not in m}
    # Only the RUNTIME tools are this ticket's subject; the copy also backticks hub tools that
    # other bundles provide and that the allowlist lists under their own names.
    runtime_named = sorted(n for n in named if n in real)
    assert runtime_named, "the copy names no runtime tool at all: %s" % sorted(named)
    for stage, tools in allow.items():
        missing = [n for n in runtime_named if n not in tools]
        assert not missing, (
            "the copy promises %s but stage %r offers only %d tools and not those -- the agent "
            "will correctly answer that it does not have them" % (missing, stage, len(tools)))


def test_the_copy_names_nothing_this_persona_DENIES():
    """#1203gs, second half: the stronger predicate, found by being caught.

    The first draft of gs allowlisted `wait_for_process` and the briefing promised it. The
    allowlist cross-validator rejected it: `mcp_test_user.deny_tools` lists `wait` AND
    `wait_for_process`, so a detect-only test-user is forbidden to block on a wait. An
    allowlist entry for a denied tool is dead, and copy that names it is #1203fz again.

    This assertion is more general than the menu check above -- a denied tool can never reach
    any stage -- so it is the one to extend when another persona gets a briefing.
    """
    import yaml
    cfg = yaml.safe_load(CONFIG)
    prof = cfg["profiles"]["mcp_test_user"]
    denied = set(prof.get("deny_tools") or ())
    assert "wait_for_process" in denied, (
        "this test's premise is that the persona denies some tool; if deny_tools no longer "
        "lists wait_for_process, re-derive what it denies before relaxing the copy")
    b = _mcp_goal_text()
    named = {m for m in re.findall(r"`([a-z][a-z0-9]*_[a-z0-9_]+)`", b)
             if not m.endswith(".sh") and "/" not in m}
    promised = sorted(n for n in named if n in denied)
    assert not promised, (
        "the briefing names tools this persona's deny_tools forbids: %s" % promised)


def test_the_copy_does_not_promise_a_foreground_shell():
    """`execute_bash` blocks, so starting a long-lived server with it wedges the turn.

    Deliberately kept off both the allowlist and the copy (#1203gs). The GOAL and STEP text are
    checked, not the module, because the module's comment explains the exclusion in prose.
    """
    goal, steps = _goal_and_steps()
    assert "execute_bash" not in goal, goal
    assert "execute_bash" not in steps, steps


def test_the_menu_stays_under_the_sticky_cap():
    """18 tools must stay well under _STICKY_STAGE_TOOL_CAP_1202ZC, or gs trades one defect
    for a truncated menu."""
    import yaml
    cfg = yaml.safe_load(CONFIG)
    allow = cfg["profiles"]["mcp_test_user"].get("stage_tool_allowlist") or {}
    for stage, tools in allow.items():
        assert len(tools) <= 32, (stage, len(tools))


def test_the_prohibition_and_the_expected_refusal_survive():
    """#1203gk's two load-bearing sentences must not be lost while rewording the step."""
    b = _mcp_goal_text()
    assert "NEVER edit docker-compose" in b
    assert "not a defect in any lane" in b
    assert "NOT EXERCISED" in b


def test_the_api_base_warning_survives():
    b = _mcp_goal_text()
    assert "127.0.0.1:8080" in b
    assert "http://localhost:8029" in b
