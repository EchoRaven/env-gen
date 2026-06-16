# Skill 强制触发机制 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 env-gen 的 resident agent 不再漏用应当触发的 skill —— 提示层把 primary skill 升级为强制自检,gate 层对高风险 角色↔skill 绑定做 closed-by-construction 硬拦截,并产出可观测的 consult 信号。

**Architecture:** 三层,落地顺序 L3a(consult 记录)→ L1(提示)→ L2(gate)→ L3b(遥测)。consult 状态由通用工具执行点 `_execute_tool`(tooling.py)记录在 `agent._consulted_skills` 这个进程内 set 上;gate 是一个 `handle_finish` policy(照 `RetroBeforeDeliverPolicy` 形状),拦截指定工具调用直到该 skill 被 consult。

**Tech Stack:** Python 3.11,`unittest`(+ `IsolatedAsyncioTestCase`),pytest runner(`/home/haibotong/miniconda3/envs/dt/bin/python -m pytest`),YAML 配置。

---

## 对已批准 spec 的两处实现层细化(behavior 不变)

实现阶段从 verbatim 代码核对后,对 [spec](../specs/2026-06-03-skill-mandatory-trigger-design.md) 做两处简化,目标不变:

1. **gate 用 `handle_finish` 拦截具体工具,而非 `allow_task_ready`。** `RetroBeforeDeliverPolicy`([workflow_policies.py:1356](../../../agent/env_generator/llm_generator/multi_agent/workflow_policies.py#L1356))已证明这是「deliver 前必须 X」的既有 pattern,它直接拦截 `deliver_project`/`report_completion` 工具调用。这**消解了 spec 的 open point O2**:`codehub_open_pr` 同样在 `handle_finish` 被工具名拦截,无需确认它在 task_ready policy 面是否可拦。
2. **不新增 `mandatory_skills` 配置字段。** 它与「显式 `- kind: skill_consult_gate` 块(已带 `required_skill` + `trigger_tools`)」冗余。L1 统一强化**全部 primary**(无需逐 skill 标记),L2 由显式 gate 块声明,沿用每个 gate 的现有声明风格。

consult 状态为**进程内(per agent 实例)生命周期**,非 per-generation/milestone —— M2 的 deliver 会被 M1 的 consult 满足。首版接受此限制(见末尾 Follow-up),与 `RetroBeforeDeliverPolicy` 当初引入 `generation_id` 的演化路径一致。

---

## File Structure

| 文件 | 责任 | 动作 |
|------|------|------|
| `agent/env_generator/llm_generator/multi_agent/agents/runtime/skill_consult.py` | consult 记录纯函数 `record_skill_consult` | **Create** |
| `agent/env_generator/llm_generator/multi_agent/agents/runtime/tooling.py:473-501` | 在通用工具执行点调一行 `record_skill_consult` | Modify |
| `agent/env_generator/llm_generator/multi_agent/agents/base.py:367` | `__init__` 初始化 `self._consulted_skills: Set[str] = set()` | Modify |
| `agent/env_generator/llm_generator/multi_agent/skill_loader.py:329-345` | 强化 `<available_skills>` preamble + primary 段措辞 | Modify |
| `agent/env_generator/llm_generator/multi_agent/workflow_policies.py` | 新增 `SkillConsultGate` 类 + factory 分支 + STARVER 注册 | Modify |
| `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml` | orchestrator + backend 各加一个 `- kind: skill_consult_gate` 块 | Modify |
| `agent/env_generator/llm_generator/multi_agent/runtime/observability/log_parser.py:~50,~93` | `AgentStats.consult_count` + 计数 | Modify |
| `agent/tests/test_skill_consult.py` | L3a 单测 | **Create** |
| `agent/tests/test_skill_prompt_mandatory.py` | L1 prompt-content 单测 | **Create** |
| `agent/tests/test_skill_consult_gate.py` | L2 gate + factory 单测 | **Create** |
| `agent/tests/test_skill_consult_telemetry.py` | L3b 遥测单测 | **Create** |

**测试运行(从 `env-gen` 仓库根)：**
```
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/<file>.py -v
```

所有新建测试文件头部都需要这段 sys.path 引导(否则 `from multi_agent...` 无法 resolve):
```python
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))
```

---

## Task 1: L3a — 在通用工具执行点记录 skill consult

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/agents/runtime/skill_consult.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/runtime/tooling.py:497-498`
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/base.py:367-369`
- Test: `agent/tests/test_skill_consult.py`

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_skill_consult.py`:

```python
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


class _FakeResult:
    def __init__(self, success, data):
        self.success = success
        self.data = data


class _FakeEventHub:
    def __init__(self):
        self.events = []

    def publish_event(self, **kwargs):
        self.events.append(kwargs)
        return kwargs


class _FakeHubs:
    def __init__(self, eventhub):
        self.eventhub = eventhub


class _FakeLogger:
    def debug(self, *a, **k):
        pass


class _FakeAgent:
    def __init__(self):
        self.agent_id = "backend"
        self._consulted_skills = set()
        self._hubs = _FakeHubs(_FakeEventHub())
        self._logger = _FakeLogger()


class RecordSkillConsult(unittest.TestCase):
    def test_records_found_skill_and_emits_event(self):
        from multi_agent.agents.runtime.skill_consult import record_skill_consult
        agent = _FakeAgent()
        result = _FakeResult(True, {"found": True, "skill": {"name": "api-contract-guard"}})
        record_skill_consult(agent, "get_skill", {"name": "api-contract-guard"}, result)
        self.assertIn("api-contract-guard", agent._consulted_skills)
        self.assertEqual(len(agent._hubs.eventhub.events), 1)
        self.assertEqual(agent._hubs.eventhub.events[0]["event_type"], "skill_consulted")
        self.assertEqual(agent._hubs.eventhub.events[0]["payload"]["skill"], "api-contract-guard")

    def test_ignores_not_found(self):
        from multi_agent.agents.runtime.skill_consult import record_skill_consult
        agent = _FakeAgent()
        result = _FakeResult(True, {"found": False, "message": "Skill not found: x"})
        record_skill_consult(agent, "get_skill", {"name": "x"}, result)
        self.assertEqual(agent._consulted_skills, set())
        self.assertEqual(agent._hubs.eventhub.events, [])

    def test_ignores_other_tools(self):
        from multi_agent.agents.runtime.skill_consult import record_skill_consult
        agent = _FakeAgent()
        result = _FakeResult(True, {"found": True, "skill": {"name": "x"}})
        record_skill_consult(agent, "read", {"name": "x"}, result)
        self.assertEqual(agent._consulted_skills, set())
        self.assertEqual(agent._hubs.eventhub.events, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_skill_consult.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'multi_agent.agents.runtime.skill_consult'`

- [ ] **Step 3: Create the helper module**

Create `agent/env_generator/llm_generator/multi_agent/agents/runtime/skill_consult.py`:

```python
"""Record skill consults at the universal tool-execution chokepoint.

Called from ``RuntimeToolingMixin._execute_tool`` after every tool call.
When the tool was ``get_skill`` and it found the skill, the canonical
skill name is added to ``agent._consulted_skills`` (read by
``SkillConsultGate``) and a ``skill_consulted`` event is published for
observability. Best-effort: never raises into the tool path.
"""

from __future__ import annotations

from typing import Any, Dict


def record_skill_consult(agent: Any, tool_name: str, tool_args: Dict, result: Any) -> None:
    if tool_name != "get_skill":
        return
    if not getattr(result, "success", False):
        return
    data = getattr(result, "data", None) or {}
    if not data.get("found"):
        return
    skill = data.get("skill") or {}
    name = str(skill.get("name") or (tool_args or {}).get("name") or "").strip()
    if not name:
        return

    consulted = getattr(agent, "_consulted_skills", None)
    if consulted is None:
        consulted = set()
        setattr(agent, "_consulted_skills", consulted)
    consulted.add(name)

    hubs = getattr(agent, "_hubs", None)
    if hubs is None or not hasattr(hubs, "eventhub"):
        return
    try:
        hubs.eventhub.publish_event(
            source_hub=agent.agent_id,
            event_type="skill_consulted",
            payload={"agent": agent.agent_id, "skill": name},
            recipients=[],
            priority="normal",
        )
    except Exception:
        try:
            agent._logger.debug(f"[{agent.agent_id}] skill_consulted emit failed")
        except Exception:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_skill_consult.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Initialize `_consulted_skills` on the agent**

In `agent/env_generator/llm_generator/multi_agent/agents/base.py`, find (lines 367-369):

```python
        # Tool instances for LLM tool calling
        self._tool_instances: Dict[str, BaseTool] = {}
        self._register_env_gen_tools()
```

Change to (insert one line before the tool-instance map):

```python
        # Skills this agent has consulted via get_skill this run. Read by
        # SkillConsultGate; populated at the tool chokepoint (skill_consult.py).
        self._consulted_skills: Set[str] = set()
        # Tool instances for LLM tool calling
        self._tool_instances: Dict[str, BaseTool] = {}
        self._register_env_gen_tools()
```

(`Set` is already imported in base.py — it is used at line 411 `self._upstream_ready_agents: Set[str] = set()`.)

- [ ] **Step 6: Wire the recorder into the tool chokepoint**

In `agent/env_generator/llm_generator/multi_agent/agents/runtime/tooling.py`, find (lines 497-498) inside `_execute_tool`:

```python
                self.log_tool_call(tool_name, tool_args, result)
                return result
```

Change to:

```python
                self.log_tool_call(tool_name, tool_args, result)
                from .skill_consult import record_skill_consult
                record_skill_consult(self, tool_name, tool_args, result)
                return result
```

- [ ] **Step 7: Re-run test + a quick import smoke**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_skill_consult.py -v`
Expected: PASS
Run: `/home/haibotong/miniconda3/envs/dt/bin/python -c "import sys; sys.path.insert(0,'agent'); sys.path.insert(0,'agent/env_generator/llm_generator'); import multi_agent.agents.runtime.tooling"`
Expected: no error (import resolves)

- [ ] **Step 8: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/agents/runtime/skill_consult.py \
        agent/env_generator/llm_generator/multi_agent/agents/runtime/tooling.py \
        agent/env_generator/llm_generator/multi_agent/agents/base.py \
        agent/tests/test_skill_consult.py
git commit -m "feat(skills): record get_skill consults on agent._consulted_skills + emit skill_consulted event"
```

---

## Task 2: L1 — primary skill 提示升级为强制自检 + red flags

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/skill_loader.py:329-345`
- Test: `agent/tests/test_skill_prompt_mandatory.py`
- Must keep green: `agent/tests/test_skill_catalog_all_workspace.py`

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_skill_prompt_mandatory.py`:

```python
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


def _build():
    from multi_agent.skill_loader import build_available_skills_prompt, SkillDefinition
    skills = [
        SkillDefinition(name="api-contract-guard", description="d-acg",
                        file_path="p1", source="x", instructions="BODY-ACG"),
        SkillDefinition(name="ui-bootstrap", description="d-ui",
                        file_path="p2", source="x", instructions="BODY-UI"),
    ]
    return build_available_skills_prompt(skills, primary_names=["api-contract-guard"])


class PrimarySkillsMandatory(unittest.TestCase):
    def test_preamble_makes_primary_mandatory(self):
        p = _build()
        low = p.lower()
        self.assertIn("must", low)
        self.assertIn("mandatory", low)

    def test_has_anti_rationalization_red_flags(self):
        low = _build().lower()
        self.assertTrue(
            any(k in low for k in ["red flag", "do not", "rationaliz"]),
            f"expected anti-rationalization cue; got: {low!r}",
        )

    def test_still_lists_skills_and_hides_bodies(self):
        p = _build()
        self.assertIn("api-contract-guard", p)
        self.assertIn("ui-bootstrap", p)
        self.assertNotIn("BODY-ACG", p)
        self.assertNotIn("BODY-UI", p)

    def test_empty_returns_empty(self):
        from multi_agent.skill_loader import build_available_skills_prompt
        self.assertEqual(build_available_skills_prompt([], primary_names=[]), "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_skill_prompt_mandatory.py -v`
Expected: FAIL — `test_preamble_makes_primary_mandatory` / `test_has_anti_rationalization_red_flags` fail (current preamble has neither "mandatory" nor red flags)

- [ ] **Step 3: Rewrite the preamble + primary header**

In `agent/env_generator/llm_generator/multi_agent/skill_loader.py`, find (lines 329-345):

```python
    lines = [
        "<available_skills>",
        "You have access to the following skills. When one matches the task,",
        "call `get_skill(name=...)` to load its full body before applying it.",
        "If `get_skill` is not available, read the listed `SKILL.md` path with",
        "`read(file_path=...)`. Use skills as operating procedures, not as",
        "vague background lore.",
        "",
    ]
    if primary:
        lines.append("## Your primary skills (your role uses these most)")
        lines.extend(_render(primary))
        lines.append("")
    if others:
        lines.append("## Also available (load on demand if relevant)")
        lines.extend(_render(others))
    lines.append("</available_skills>")
    return "\n".join(lines)
```

Replace with:

```python
    lines = [
        "<available_skills>",
        "These skills are operating procedures, not background lore. When a",
        "task is covered by a skill, you MUST call `get_skill(name=...)` to",
        "load its full body and follow it BEFORE you act. If `get_skill` is",
        "unavailable, read the listed `SKILL.md` path with `read(file_path=...)`.",
        "",
        "Your **primary** skills below are MANDATORY for your role: consult the",
        "relevant one before acting on the work it covers. Do not rationalize",
        "skipping it — these thoughts are red flags that mean STOP and load the",
        "skill first:",
        "  - \"this is a simple change, I'll just do it\"",
        "  - \"I'll write it first and check the skill later\"",
        "  - \"I roughly remember what this skill says\"",
        "",
    ]
    if primary:
        lines.append("## Your primary skills (MANDATORY — consult before acting)")
        lines.extend(_render(primary))
        lines.append("")
    if others:
        lines.append("## Also available (load on demand if relevant)")
        lines.extend(_render(others))
    lines.append("</available_skills>")
    return "\n".join(lines)
```

- [ ] **Step 4: Run new test to verify it passes**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_skill_prompt_mandatory.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the existing catalog test to confirm no regression**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_skill_catalog_all_workspace.py -v`
Expected: PASS — the existing test only asserts skill names + descriptions appear, bodies don't, and `"primary" in lower or "your" in lower` (still true: header says "Your primary skills (MANDATORY ...)").

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/skill_loader.py \
        agent/tests/test_skill_prompt_mandatory.py
git commit -m "feat(skills): make primary skills mandatory-to-consult in available_skills preamble + red flags"
```

---

## Task 3: L2 — `SkillConsultGate` policy + factory + starver 注册

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/workflow_policies.py` (new class near line 1474; STARVER set line 1489; factory branch line ~1636)
- Test: `agent/tests/test_skill_consult_gate.py`

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_skill_consult_gate.py`. The blocked path constructs `Message.assistant/tool/user` exactly like `RetroBeforeDeliverPolicy`; if `Message.assistant(tool_calls=[...])` is strict about the tool_call shape, copy the `tool_call` fixture from `agent/tests/test_retro_before_deliver_gate.py` (same handle_finish block path). This test only asserts the return value, which is robust to message internals:

```python
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


class _FakeLogger:
    def warning(self, *a, **k):
        pass


class _FakeAgent:
    def __init__(self, consulted=None):
        self.agent_id = "backend"
        self._consulted_skills = set(consulted or [])
        self._logger = _FakeLogger()


def _finish_kwargs(tool_name):
    return dict(
        tool_name=tool_name,
        tool_args={},
        tool_call={"id": "tc1", "function": {"name": tool_name, "arguments": "{}"}},
        tool_call_id="tc1",
        messages=[],
        files_created=[],
        files_modified=[],
    )


class SkillConsultGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocks_trigger_tool_when_not_consulted(self):
        from multi_agent.workflow_policies import SkillConsultGate
        gate = SkillConsultGate(required_skill="api-contract-guard",
                                trigger_tools=["codehub_open_pr"])
        agent = _FakeAgent(consulted=[])
        out = await gate.handle_finish(agent, **_finish_kwargs("codehub_open_pr"))
        self.assertEqual(out, {"action": "continue"})

    async def test_passes_when_consulted(self):
        from multi_agent.workflow_policies import SkillConsultGate
        gate = SkillConsultGate(required_skill="api-contract-guard",
                                trigger_tools=["codehub_open_pr"])
        agent = _FakeAgent(consulted=["api-contract-guard"])
        out = await gate.handle_finish(agent, **_finish_kwargs("codehub_open_pr"))
        self.assertIsNone(out)

    async def test_ignores_non_trigger_tool(self):
        from multi_agent.workflow_policies import SkillConsultGate
        gate = SkillConsultGate(required_skill="api-contract-guard",
                                trigger_tools=["codehub_open_pr"])
        agent = _FakeAgent(consulted=[])
        out = await gate.handle_finish(agent, **_finish_kwargs("finish"))
        self.assertIsNone(out)


class FactoryWiring(unittest.TestCase):
    def test_skill_consult_gate_parsed_from_config(self):
        from multi_agent.workflow_policies import create_workflow_policies, SkillConsultGate
        cfg = {"workflow_policies": [
            {"kind": "lane_idle_circuit_breaker"},
            {"kind": "skill_consult_gate",
             "required_skill": "api-contract-guard",
             "trigger_tools": ["codehub_open_pr"]},
        ]}
        pols = create_workflow_policies(cfg)
        gates = [p for p in pols if isinstance(p, SkillConsultGate)]
        self.assertEqual(len(gates), 1)
        self.assertEqual(gates[0].required_skill, "api-contract-guard")
        self.assertIn("codehub_open_pr", gates[0]._trigger_tools)

    def test_starver_set_lists_skill_consult_gate(self):
        from multi_agent.workflow_policies import STARVER_POLICY_KINDS
        self.assertIn("skill_consult_gate", STARVER_POLICY_KINDS)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_skill_consult_gate.py -v`
Expected: FAIL — `ImportError: cannot import name 'SkillConsultGate'`

- [ ] **Step 3: Add the `SkillConsultGate` class**

In `agent/env_generator/llm_generator/multi_agent/workflow_policies.py`, immediately AFTER the end of `RetroBeforeDeliverPolicy` (after line 1474, `return {"action": "continue"}`), add:

```python
class SkillConsultGate(BaseWorkflowPolicy):
    """Hard gate: a designated tool call is blocked until the agent has
    consulted (``get_skill``) a required skill in THIS process lifetime.

    Models ``RetroBeforeDeliverPolicy`` — a ``handle_finish`` gate that
    intercepts specific tool calls and injects a continue-loop block
    instead of letting the tool run. Consult state is recorded at the
    universal tool chokepoint (``agents/runtime/skill_consult.py``) onto
    ``agent._consulted_skills``.

    Scope: process-lifetime (per agent instance), NOT per-generation. A
    consult from milestone N satisfies the gate for milestone N+1. See
    the plan's Follow-up; mirrors RetroBeforeDeliverPolicy's generation-
    scope evolution.
    """

    def __init__(self, required_skill: str, trigger_tools: List[str]):
        self.required_skill = str(required_skill or "").strip()
        self._trigger_tools = frozenset(
            str(t).strip() for t in (trigger_tools or []) if str(t).strip()
        )

    async def handle_finish(
        self,
        agent: Any,
        *,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_call: Any,
        tool_call_id: str,
        messages: List[Any],
        files_created: List[str],
        files_modified: List[str],
    ) -> Optional[Dict[str, Any]]:
        if not self.required_skill or tool_name not in self._trigger_tools:
            return None
        consulted = getattr(agent, "_consulted_skills", None) or set()
        if self.required_skill in consulted:
            return None
        block_text = (
            f"🚫 skill gate: `{tool_name}` is blocked until you consult the "
            f"`{self.required_skill}` skill for this run.\n\n"
            f"Call `get_skill(name='{self.required_skill}')` first and follow "
            f"it, then call `{tool_name}` again — the gate auto-passes once the "
            "skill has been consulted."
        )
        messages.append(Message.assistant(tool_calls=[tool_call]))
        messages.append(Message.tool(block_text, tool_call_id))
        messages.append(Message.user(
            f"Skill gate fired. Call `get_skill(name='{self.required_skill}')` "
            f"now, then `{tool_name}` again. Do not skip the skill."
        ))
        try:
            agent._logger.warning(
                f"[{agent.agent_id}] {tool_name} blocked by skill gate "
                f"(needs {self.required_skill})"
            )
        except Exception:
            pass
        return {"action": "continue"}
```

(`Message`, `Any`, `Dict`, `List`, `Optional` are already imported in this module — `RetroBeforeDeliverPolicy` above uses all of them.)

- [ ] **Step 4: Register the kind in `STARVER_POLICY_KINDS`**

In the same file, find (line 1489):

```python
STARVER_POLICY_KINDS: FrozenSet[str] = frozenset({
    "finish_continue",
    "hub_consistency_gate",
    "claim_assigned_tasks",
    "retro_before_deliver",
```

Add one line after `"retro_before_deliver",`:

```python
STARVER_POLICY_KINDS: FrozenSet[str] = frozenset({
    "finish_continue",
    "hub_consistency_gate",
    "claim_assigned_tasks",
    "retro_before_deliver",
    "skill_consult_gate",
```

- [ ] **Step 5: Add the factory branch**

In `create_workflow_policies`, find (line 1633-1636):

```python
        elif kind == "retro_before_deliver":
            policies.append(RetroBeforeDeliverPolicy())
        elif kind == "claim_assigned_tasks":
            policies.append(ClaimAssignedTasksPolicy())
```

Insert a new branch after `claim_assigned_tasks` (before the `elif kind: raise ValueError` catch-all):

```python
        elif kind == "retro_before_deliver":
            policies.append(RetroBeforeDeliverPolicy())
        elif kind == "claim_assigned_tasks":
            policies.append(ClaimAssignedTasksPolicy())
        elif kind == "skill_consult_gate":
            policies.append(
                SkillConsultGate(
                    required_skill=str(raw.get("required_skill") or "").strip(),
                    trigger_tools=list(raw.get("trigger_tools") or []),
                )
            )
```

- [ ] **Step 6: Run test to verify it passes**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_skill_consult_gate.py -v`
Expected: PASS (5 tests). If `test_blocks_trigger_tool_when_not_consulted` errors inside `Message.assistant`, copy the `tool_call` fixture shape from `agent/tests/test_retro_before_deliver_gate.py` into `_finish_kwargs` and re-run.

- [ ] **Step 7: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/workflow_policies.py \
        agent/tests/test_skill_consult_gate.py
git commit -m "feat(skills): add SkillConsultGate (handle_finish gate) + factory wiring + starver registration"
```

---

## Task 4: 把 gate 接到 orchestrator + backend 的 agents_config.yaml

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml`
- Test: `agent/tests/test_skill_consult_gate.py` (add a yaml-presence test)

绑定:orchestrator → `release-readiness` 前置于 `deliver_project`/`report_completion`;backend → `api-contract-guard` 前置于 `codehub_open_pr`。`skill_consult_gate` 是 starver,**必须列在 `lane_idle_circuit_breaker` 之后**(否则 `_check_starver_breaker_ordering` 会 WARN)。

- [ ] **Step 1: Add the yaml-presence failing test**

Append to `agent/tests/test_skill_consult_gate.py` (before `if __name__`):

```python
class YamlWiring(unittest.TestCase):
    def test_config_declares_both_gates(self):
        cfg_path = (LLM_DIR / "multi_agent" / "agents" / "agents_config.yaml")
        text = cfg_path.read_text(encoding="utf-8")
        self.assertIn("kind: skill_consult_gate", text)
        self.assertIn("required_skill: release-readiness", text)
        self.assertIn("required_skill: api-contract-guard", text)
        self.assertIn("codehub_open_pr", text)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_skill_consult_gate.py::YamlWiring -v`
Expected: FAIL — strings not yet in the yaml.

- [ ] **Step 3: Add the backend gate block**

In `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml`, in the **backend** profile's `workflow_policies:` list, find (line 239):

```yaml
      - kind: claim_assigned_tasks
```

Add directly after it (still inside backend's `workflow_policies:`, indentation matching the sibling `- kind:` entries):

```yaml
      - kind: claim_assigned_tasks
      # Skill gate (2026-06-03): backend must consult api-contract-guard
      # before opening a PR, so endpoint code can't drift from the API
      # contract. Listed after the breaker (starver ordering). Consult
      # state lives on agent._consulted_skills (skill_consult.py).
      - kind: skill_consult_gate
        required_skill: api-contract-guard
        trigger_tools: [codehub_open_pr]
```

- [ ] **Step 4: Add the orchestrator gate block**

In the same file, locate the **orchestrator** profile (the one whose `skills:` is `["release-readiness", "new-env-bootstrap"]`, near line 93). In its `workflow_policies:` list, after its last `- kind:` entry (and after any `lane_idle_circuit_breaker` entry), add:

```yaml
      # Skill gate (2026-06-03): orchestrator must consult release-readiness
      # before delivering, so the delivery checklist is actually applied.
      - kind: skill_consult_gate
        required_skill: release-readiness
        trigger_tools: [deliver_project, report_completion]
```

If the orchestrator profile has NO `workflow_policies:` key yet, add one at the profile's top level:

```yaml
    workflow_policies:
      - kind: skill_consult_gate
        required_skill: release-readiness
        trigger_tools: [deliver_project, report_completion]
```

- [ ] **Step 5: Run the yaml test + the full gate test file**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_skill_consult_gate.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Confirm config still loads (no starver-order WARN, no parse error)**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -c "import sys; sys.path.insert(0,'agent'); sys.path.insert(0,'agent/env_generator/llm_generator'); from multi_agent.agents.configurable_agent import get_agent_config; from multi_agent.workflow_policies import create_workflow_policies, SkillConsultGate; \
cfg=get_agent_config('backend'); pols=create_workflow_policies(cfg); print('backend SkillConsultGate:', any(isinstance(p,SkillConsultGate) for p in pols))"`
Expected: prints `backend SkillConsultGate: True`, no `WARNING` about starver ordering, no traceback. (If the orchestrator's config_key differs from `'backend'`'s sibling, repeat with the orchestrator key; the key is the profile name used by `get_agent_config`.)

- [ ] **Step 7: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml \
        agent/tests/test_skill_consult_gate.py
git commit -m "feat(skills): gate orchestrator deliver on release-readiness, backend PR on api-contract-guard"
```

---

## Task 5: L3b — consult 遥测在 observability 暴露

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/observability/log_parser.py`
- Test: `agent/tests/test_skill_consult_telemetry.py`

`skill_consulted` 事件(Task 1 发出)写进 `.agent_logs/<Agent>/*.jsonl` 后,会自动进入 `AgentStats.event_type_counts`。本 task 额外加一个一等 `consult_count` 字段便于读取。

- [ ] **Step 1: Read the parser to confirm field/var names**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -c "print(open('agent/env_generator/llm_generator/multi_agent/runtime/observability/log_parser.py').read())" | sed -n '40,110p'`
Confirm: the `AgentStats` dataclass fields (≈ line 50, has `event_type_counts: Dict`, `tool_call_count: int`), the loop variable that holds each event's type (the `et` used in `if et == "tool_call":`, ≈ line 93), and how the per-agent stats object is referenced in that loop. Adjust the exact names in Steps 3-4 to match what you read.

- [ ] **Step 2: Write the failing test**

Create `agent/tests/test_skill_consult_telemetry.py`:

```python
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


class ConsultTelemetry(unittest.TestCase):
    def test_skill_consulted_counted(self):
        from multi_agent.runtime.observability.log_parser import aggregate_logs
        with tempfile.TemporaryDirectory() as tmp:
            logs_dir = Path(tmp)
            agent_dir = logs_dir / "Backend"
            agent_dir.mkdir(parents=True, exist_ok=True)
            with (agent_dir / "run.jsonl").open("w", encoding="utf-8") as fh:
                fh.write(json.dumps({"event_type": "skill_consulted",
                                     "agent": "backend", "skill": "api-contract-guard"}) + "\n")
                fh.write(json.dumps({"event_type": "skill_consulted",
                                     "agent": "backend", "skill": "api-contract-guard"}) + "\n")
                fh.write(json.dumps({"event_type": "tool_call", "tool": "read"}) + "\n")
            stats = aggregate_logs(logs_dir)
            # Locate the Backend agent's stats (dict keyed by agent name or a
            # .agents collection — match aggregate_logs' actual return shape
            # confirmed in Step 1).
            backend = stats.agents["Backend"] if hasattr(stats, "agents") else stats["Backend"]
            self.assertEqual(backend.consult_count, 2)
            self.assertEqual(backend.event_type_counts.get("skill_consulted"), 2)


if __name__ == "__main__":
    unittest.main()
```

> If Step 1 shows `aggregate_logs` returns a different shape (e.g. a list, or keys by lowercased name), fix the `backend = ...` lookup line to match before running. The two assertions (consult_count + event_type_counts) are the behavioral contract.

- [ ] **Step 3: Run test to verify it fails**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_skill_consult_telemetry.py -v`
Expected: FAIL — `AttributeError: 'AgentStats' object has no attribute 'consult_count'`

- [ ] **Step 4: Add the `consult_count` field + increment**

In `agent/env_generator/llm_generator/multi_agent/runtime/observability/log_parser.py`, in the `AgentStats` dataclass (≈ line 50), add a field beside `tool_call_count`:

```python
    consult_count: int = 0
```

In the per-event aggregation loop (≈ line 93, where `et` is the event type and the agent's stats object — call it `stats`/`agent_stats` per Step 1 — is updated), add, right beside the existing `if et == "tool_call":` handling:

```python
            if et == "skill_consulted":
                agent_stats.consult_count += 1
```

(Use the exact stats-variable name confirmed in Step 1. `event_type_counts` is already incremented generically for every `et`, so no extra code is needed for that assertion.)

- [ ] **Step 5: Run test to verify it passes**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_skill_consult_telemetry.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/observability/log_parser.py \
        agent/tests/test_skill_consult_telemetry.py
git commit -m "feat(skills): surface consult_count in observability log aggregation"
```

---

## Final verification

- [ ] **Run all four new test files + the existing skill catalog test together**

Run:
```
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest \
  agent/tests/test_skill_consult.py \
  agent/tests/test_skill_prompt_mandatory.py \
  agent/tests/test_skill_consult_gate.py \
  agent/tests/test_skill_consult_telemetry.py \
  agent/tests/test_skill_catalog_all_workspace.py -v
```
Expected: all PASS.

- [ ] **Targeted regression of policy + skill suites**

Run:
```
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/ -k "skill or policy or workflow or bootstrap or retro" -q
```
Expected: no new failures vs the pre-change baseline.

---

## Self-review (against spec)

- **Spec G1 (提示层强制自检)** → Task 2. ✅
- **Spec G2 (gate 前置条件)** → Task 3 (class) + Task 4 (wiring). ✅
- **Spec G3 (consult 遥测)** → Task 1 (event emit + `_consulted_skills`) + Task 5 (count surfaced). ✅
- **Spec 落地顺序 L3a→L1→L2** → Tasks 1→2→3→4; L3b(Task 5)依赖 L3a 的事件,放最后。✅
- **Spec no-fallback** → gate 走 `handle_finish` 响亮拦截 + 注入 continue 循环,无软降级。✅

## Follow-up (out of scope, 记录)

- **consult 状态为进程内生命周期**,M_{N} 的 consult 满足 M_{N+1} 的 gate。若要 per-milestone/generation 严格,仿 `RetroBeforeDeliverPolicy` 引入 `generation_id`,把 `_consulted_skills` 改为 `Dict[generation_id, Set[str]]` 并在 milestone boundary 清空。建议待迭代层(spec D1-D5 / 架构文档 Stage 6)落地后再做。
- **`required_skill` 与 agent allowlist 的一致性**未做启动期校验(factory 无 workspace 句柄)。若误配一个不在 profile `skills:` 里的技能,gate 将永不放行(响亮卡死,符合 no-fallback)。可在 `configurable_agent` 解析处补一个 subset 断言。
