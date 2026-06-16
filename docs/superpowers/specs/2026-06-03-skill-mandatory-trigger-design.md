# Skill 强制触发机制 — 设计 spec

**Date:** 2026-06-03  **Status:** Approved design, pre-implementation
**Author:** brainstorming session (Claude)
**Driver:** 实际观察到 resident agent 漏用了应当触发的 skill(非提前防患)。

---

## 1. 背景与问题

env-gen 的 skill 系统([skill_loader.py](../../../agent/env_generator/llm_generator/multi_agent/skill_loader.py))是 Claude Code / OpenClaw「Agent Skills」血统的 Python 复刻:`SKILL.md` + frontmatter,系统提示注入一个 `<available_skills>` catalog(name+description+path),完整正文由 agent 按需 `get_skill(name=...)` 加载。每个 agent profile 在 [agents_config.yaml](../../../agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml) 用 `skills: [...]` 拿到一个 per-role allowlist,该 allowlist 当前即被当作「primary skills」渲染([configurable_agent.py:340](../../../agent/env_generator/llm_generator/multi_agent/agents/configurable_agent.py#L340))。

**问题:** catalog 的触发指令是**软的**(「when one matches, call get_skill」),agent 会漏用——例如 backend 不查 `api-contract-guard` 就写 endpoint,产生 spec drift,而这正是流水线下游 gate 本来就在打的故障类。

**关键澄清(纠正一个常见误解):** Claude Code 的「哪怕 1% 相关也必须触发」**不是**一个算出来的相似度阈值,而是一个**提示层行为先验**(会话启动注入的 using-superpowers + Red-Flags 表)。因此本设计**不做字面的相似度数值门**——per-role allowlist 本身已是「检索」,每个角色 2–4 个精选 skill,「primary = mandatory」比任何余弦阈值都更确定、更可测。

**env-gen 相对 Claude Code 的结构优势:** Claude Code 是交互式单 agent,下游无 verifier,提示纪律是它唯一的安全网。env-gen 的 agent 受 gate/policy 验证,且遵循 closed-by-construction / no-fallback 纪律,因此可以多用一根 Claude Code 结构上没有的杠杆:把「是否查阅过某 skill」做成**前置条件 gate**——结构强制,而非求 LLM 自律。

## 2. 目标 / 非目标

**目标**
- G1 提示层:把 primary skill 从「建议」升级为「强制自检」,措辞对标 Claude Code 硬条件 + Red-Flags。
- G2 gate 层:对少数高风险 角色↔skill 绑定,做 closed-by-construction 的硬前置条件(漏查则响亮拒绝)。
- G3 遥测:产出可观测的 consult 信号,用于(a)量化漏用、(b)验证 G1 是否生效、(c)喂给 G2 的 gate 判定。

**非目标 / YAGNI**
- 不做字面相似度阈值触发。
- 不 gate 每一次文件写(只 gate 粗粒度、低频的动作)。
- 不引入兜底/软降级路径(no-fallback)。
- 不改 skill 文件格式、scope、allowlist 解析这些已工作的部分。

## 3. 架构与依赖关系

三层有依赖,**落地顺序 = L3a substrate → L1 → L2**:

```
L1 提示纪律      ── 改 build_available_skills_prompt preamble(独立,不依赖谁)
L3 consult 信号  ── GetSkillTool 成功执行时记 agent._consulted_skills + 发 skill_consulted 事件
L2 gate          ── 读 agent._consulted_skills,在 deliver / open_pr 等粗动作前返回 (False, reason)
```

## 4. L1 — 提示层强制自检

- **改点:** [skill_loader.py:329-346](../../../agent/env_generator/llm_generator/multi_agent/skill_loader.py#L329) 的 `build_available_skills_prompt`,即 `<available_skills>` 的 preamble 与「primary skills」段。
- **改法:** preamble 由软句改为硬纪律 + env-gen 版 Red-Flags,大意:
  > Your **primary** skills are mandatory operating procedures. Before you act on a task they cover, you MUST `get_skill` first and follow it. Do not rationalize skipping it. Red flags that mean STOP: 「这只是个简单改动」「我先写了再说」「我大概记得这个 skill 讲什么」。
- **生效面:** 对该 agent 的全部 primary(= profile `skills:`)生效。纯提示改动,零 runtime 成本。
- **不变量:** primary 语义沿用 [configurable_agent.py:340](../../../agent/env_generator/llm_generator/multi_agent/agents/configurable_agent.py#L340) 现有的 `primary_names`,不新增渲染概念。

## 5. L2 — gate 前置条件

- **复用现成 pattern:** 照 [`RetroBeforeDeliverPolicy`](../../../agent/env_generator/llm_generator/multi_agent/workflow_policies.py#L1356)(已实现「deliver 前必须做 X」)的形状,新增 `SkillConsultGate(BaseWorkflowPolicy)`,实现 `allow_task_ready(agent, message) -> Optional[Tuple[bool, str]]`,未满足时返回 `(False, "must consult <skill> before <action>")`。policy 的 deny 协议见 [workflow_policies.py:49](../../../agent/env_generator/llm_generator/multi_agent/workflow_policies.py#L49)(`allow_task_ready` 返回 `(bool, reason)`)。
- **gate 落在哪个动作(关键判断,已与用户确认):** 只 gate 粗粒度、低频、漏了就触发下游故障的动作,**不下沉到每次文件写**:
  - `release-readiness` → gate 在 **deliver / validation-phase task_ready**(与 RetroBeforeDeliver 同 seam,最稳)。
  - `api-contract-guard` → gate 在 **`open_pull_request` / 标记 endpoint_implemented** 这类粗动作上(避免动 step_pipeline 的每写一文件 gate,降低卡死 lane 风险)。
- **配置:** 每个 profile 新增 `mandatory_skills: [...]`,必须是 `skills:` 的子集;默认 `[]` 表示「该角色无硬性必查 skill」(是真实表达,不是 back-compat 兜底)。
  - L1 对**全部 primary** 生效;L2 只对 **`mandatory_skills`** 生效。
  - 加载/校验时:`mandatory_skills` 若含不在 `skills:` 里的项 → 启动期响亮报错(closed-by-construction,沿用 [skill_loader.py:288](../../../agent/env_generator/llm_generator/multi_agent/skill_loader.py#L288) 现有「configured skills not found」抛错风格)。
- **判定依据:** gate 读 `agent._consulted_skills`(由 L3a 维护),仿照 [`KickoffBootstrapGate`](../../../agent/env_generator/llm_generator/multi_agent/workflow_policies.py#L116) 读 agent/hub 状态的做法。

## 6. L3 — consult 遥测

- **L3a substrate(gate 依赖):** `GetSkillTool` 成功执行([knowledge_tools.py:503](../../../agent/env_generator/llm_generator/tools/knowledge_tools.py#L503))时:
  - `agent._consulted_skills.add(name)`(新属性,初始化为空 set);
  - 发一个 `skill_consulted` 事件(agent_id + skill name + 时间)。
  - 当前 `GetSkillTool` 只持有 `self.workspace`,需在构造时多传 agent_id + event/consult sink;**优先评估**复用已有的 skill 观察层 [observer_handlers.py](../../../agent/env_generator/llm_generator/multi_agent/observer_handlers.py)(已 wrap `get_skill_tool`)以避免给 tool 增加耦合。
- **L3b measure(验证 G1):** 在 live_monitor / observability 暴露「某 agent 在把 X 列为 primary 的阶段,是否实际 load 了 X」。最省版本可从现有 tool-call 日志派生(无需动 tool);但 gate 需结构化信号,故 L3a 仍须实现。

## 7. 数据流

1. agent 构建系统提示 → 注入强化后的 `<available_skills>`(L1)。
2. agent 运行中调用 `get_skill(name=X)` → GetSkillTool 返回正文 + 记 `_consulted_skills.add(X)` + 发 `skill_consulted`(L3a)。
3. agent 走到受 gate 的粗动作(deliver / open_pr) → `SkillConsultGate.allow_task_ready` 检查 `mandatory_skills ⊆ _consulted_skills`;缺则 `(False, reason)` 响亮拒绝(L2)。
4. live_monitor/observability 聚合 `skill_consulted` 事件 → consult 率指标(L3b)。

## 8. 测试(closed-by-construction)

- **L1:** prompt-content 测试钉死 preamble 含 mandatory 子句 + red-flags 关键词(沿用现有 prompt-content 测试模式)。
- **L2:** `SkillConsultGate` 单测——`mandatory_skills` 未 consult 时 `allow_task_ready` 返回 `(False, ...)`;consult 后放行;`mandatory_skills` 非 `skills:` 子集 → 启动期抛错。对标 KickoffBootstrapGate / RetroBeforeDeliver 的既有测试。
- **L3:** GetSkillTool 执行后 `agent._consulted_skills` 含该 skill 且发了 `skill_consulted` 事件。

## 9. 风险

- **gate 调过头卡 lane** — 响亮卡符合 no-fallback;靠「只 gate 粗动作 + `mandatory_skills` 显式声明」收窄面;首批只给 `release-readiness`(deliver)与 `api-contract-guard`(open_pr)。
- **L1 仍是 LLM 自律** — 与 Claude Code 同弱点;故配 L3b 量化、并对最贵的绑定上 L2 兜底。
- **GetSkillTool 增构造参数** — 触及 tool 装配([tool_bundles.py:209](../../../agent/env_generator/llm_generator/multi_agent/tool_bundles.py#L209))与可能的 observer 层;倾向走 observer 以减少 tool 耦合(实现计划阶段定夺)。

## 10. 待实现计划阶段定夺的开放点

- O1 L3a 的 consult 记录走 GetSkillTool 直接发事件,还是走 observer_handlers 层?(倾向 observer)
- O2 `api-contract-guard` 的 gate seam 具体绑到哪个事件/工具(`open_pull_request` vs `endpoint_implemented` 标记)?需确认该动作在 task_ready policy 面可拦截,否则需另寻粗动作 seam。
- O3 首批 `mandatory_skills` 配置:orchestrator=`[release-readiness]`、backend=`[api-contract-guard]`,其余 `[]` — 待确认。

## 11. 落地顺序

L3a(consult substrate)→ L1(提示纪律 + 测试)→ L3b(遥测暴露,验证 L1)→ L2(gate,先 deliver 后 open_pr)。
