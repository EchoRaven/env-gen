# 架构评审:WorkHub task / agent plan / stage 的关系与重构方向

**Date:** 2026-06-03  **Status:** 分析 + 建议(未实现,未批准为 spec)
**方法:** 逐项对照真实代码(三轮 subagent 调查 + 对抗式核查),所有结论附 `file:line`。
**范围:** `agent/env_generator/llm_generator/multi_agent` 的任务/计划机制。**只读评审,未改任何代码。**

---

## 一句话结论

系统里"task"和"plan"各有**两套含义**、"stage"有**四个互不相同的概念**,其中:
1. **WorkHub 的 `stage` 层是 write-only —— 任何 live 的调度/门控/UI 都不读它,删掉零行为变化。**
2. **agent 的 PlanTool plan 当前是 free-floating(以 agent_id 为键,无 `task_id` 绑定),而且会向下"外溢"成共享 WorkHub 任务**,这既制造了与项目 task 的冲突,又和"plan 应隶属于某个 task"的正确直觉相反。
3. 建议的目标模型:**项目层 = milestone → 扁平 WorkHub task(depends_on DAG + priority);agent 层 = 绑定 `task_id` 的私有 per-task "structured think",不外溢。** 这把"去掉 stage"和"修复 plan↔task 冲突"合并成同一个重构。

---

## 1. 当前真实结构

把被滥用的"stage / plan / task"按层拆清:

| 层 | 是什么 | 状态 | 证据 |
|---|---|---|---|
| **milestone `M{n}`** | kickoff **轮次**身份(会议命名、M1 才要 feature_inventory、命名 doc) | 活,但只接了 **M1**(`milestone_index=1` 硬编码,无 M2+ loop) | `orchestrator.py:593`;`roadmap_validator.py:638,671`;`run_kickoff.py:493`;`authoring.py:382-520`(`MILESTONE_M{n}.md`) |
| **WorkHub task** | 被指派的**扁平工作单元**(+`depends_on` DAG +`priority`) | 活;**系统唯一真正使用的 "task"** | `service.py:203-241`(create_task,无 stage_id 形参);`run_kickoff.py:1042-1091`(kickoff 发布扁平 task) |
| **WorkHub stage** | task 上的 `stage_id` / plan 的 `stages` 字段 | **write-only,死读** | 见 §2.2 |
| **PlanTool plan / stage** | 各 agent 内存里的 `StagedPlan`(stages→tasks→acceptance + party) | 数据模型里 stage **强制**,但 live 流里**装饰性** | `reasoning_tools.py:218-256, 399-405, 1891` |
| **step pipeline stage** | `hub_pulse→planning→action→commit_gate` 执行管线 | 活,**与本话题无关,勿动** | `step_runner.py:79-101` |

**任务是怎么发布的(关键事实):** `finalize_kickoff` 遍历 `synthesize_task_tree` 产出的条目,逐条 `workhub.create_task(title, assignee, depends_on, kind, ...)` —— **不带 stage_id,也不调 `create_plan`**。`synthesize_task_tree` 产出的 dict 只有 `id/owner/kind/summary/endpoint|table/depends_on/status`,**没有 stage**(`schema_tolerance.py:243-392`)。带 `stages[]` 的 `create_plan`(`service.py:118-141`)**零 live 调用方**(只剩 def + prompt + 文档 + 5 个测试)。

**调度只看 dependency + priority:** `list_ready_tasks`(`service.py:443`)/`available_tasks_for`(`service.py:520`)只 gate `status=="pending"` + 所有 `depends_on` 已 `completed`,再按 `(priority_rank, created_at)` 排序。**不读 stage。**

**milestone 与 stage 正交:** `M{n}` 是 kickoff 轮次,不是 stage,也不是 task 上的字段;kickoff 模块里 `stage` 字样为零。每次 finalize 发一批**扁平** task。

---

## 2. 三个问题(逐一核实)

### 2.1 WorkHub task ↔ agent plan:外溢 + 冲突

**意图本来是对的**:WorkHub task = "要做什么"(被指派、有依赖门、被 claim),PlanTool plan = "我打算怎么做"。但实现把 plan **向下外溢**进了同一个 task store:

每个 step,`_auto_sync_hub_state → _sync_plan_index_to_hub`(`step_pipeline/helpers.py:100-112,159`)→ `_sync_plan_index`(`reasoning_tools.py:1501-1513`)把本地 plan 写进 WorkHub **三种形态**:
1. `upsert_plan_snapshot(agent_id)` —— 只读快照页(没问题);
2. 但它顺带把每个 plan task 物化成 `plan:{agent}:{stage}:{task}` 的 task 行(`_upsert_snapshot_task`,`service.py:177-201`,`source=legacy_plan_tool`);
3. `_sync_plan_tasks_to_dev_tasks`(`reasoning_tools.py:1515-1557`)又 `create_task` 出 `dev:plan:...` 的**真实可 claim** task 行(`source=plan`),带 plan 的 assignee,出生即 `status=pending`。

**由此产生的真实冲突:**

- **C1 — plan 把 finish 门反锁在自己身上。** `ClaimAssignedTasksPolicy`(`workflow_policies.py:927-964`)会 block `finish()`,只要存在 `assignee==我 / status==pending / 未 claim` 的 task。`dev:plan:...` 恰恰这样出生 —— agent 只是在自己 plan 里记一笔,就造出幽灵任务挡住自己的 finish(哪怕 PlanTool 里已 completed)。有 3-strike 自动 cancel 兜底(`workflow_policies.py:745-758`),但那是降级恢复,不是 reconcile。
- **C2 — plan 能给别的 agent 制造队列项。** `assign_task` 透传 assignee,sync 时落到**另一条 lane 的 finish 门**上。
- **C3 — 双 canonical / 状态分叉。** WorkHub 的 `claim/complete/fail`(`service.py:243-321`)vs PlanTool 的 `complete_task`(只改 `self._plan`,`reasoning_tools.py:1988-2010`),**无反向同步**;`dev:plan:...` 镜像是 skip-if-exists(`reasoning_tools.py:1537`),创建后状态**永不更新**。`finish()` 认 WorkHub,prompt/UI 认 plan —— 可以打架。
- **C4 — prompt 已在硬警告这个碰撞。** `orchestrator_agent.j2:203,216-227`:用 PlanTool add_task 写 kickoff 拥有的 db/api "会和 kickoff 注册的任务冲突(重复 ID、register_endpoint/register_table 的 role-gate 拒绝)"。即冲突已知,**目前靠 prompt 软约束兜着**。

**已有的弱 reconcile:** 不同 id 命名空间(`plan:` / `dev:plan:` / kickoff id)避免互相覆盖;terminal-state 跳过(`service.py:183-184`);APIHub/SchemaHub→WorkHub closer 把 `implement_endpoint/table` 任务在 code-side status 翻 `implemented` 时自动 complete(`service.py:392-445`)—— 但这是从 APIHub 侧关闭,**不经 plan**。

### 2.2 stage 层是 write-only(可删,零行为变化)

要区分**四个**"stage":

1. **WorkHub stage** —— 写入点:`create_plan` 存 `stages`、`_upsert_snapshot_task` 给 task 打 `stage_id`(`service.py:177-201`)、`_sync_plan_tasks_to_dev_tasks` 打 `stage_id`(`reasoning_tools.py:1554`)、`add_task_to_plan`(`service.py:855`)。**唯一按 stage 分组的 reader 是 `tasks_by_stage`(`service.py:602,612`),生产零调用方(只 2 个测试)。** 调度器、交付门(`orchestrator.py:1497` `_validate_delivery_gate` + `deliverability.py`)、`roadmap_validator.py`、`ready_set.py` —— **`stage` 字样全为零。**
2. **PlanTool stage** —— `reasoning_tools.py` 内存自洽:`_start_stage/_complete_stage`(`:1812,1842`)只改 `self._plan` 并返回文本;`complete_stage` 的"all tasks done"只 gate 它自己的 ToolResult,不 gate 真实执行/交付。唯一跨组件读 `current_stage_id` 的是 `sync.py:515` `_summarize_plan_gaps`,**而该方法全仓零调用方(死)**。
3. **live_monitor stage UI** —— `live_monitor_server.py:909-1038`(`_extract_plan_summary`)从 PlanTool 的 `📋 PLAN` 日志行(`PLAN_LINE_RE`,`:39`)重建 stage 树,**不读 WorkHub stage**。删 WorkHub stage 不碰 UI。
4. **step pipeline stage** —— `step_runner.py:79-101` 的执行管线,load-bearing 但**与 task stage 无关,勿动。**

**结论:WorkHub `stage_id` 流入(写)即死路;唯一 reader 是 test-only。删除它对调度/门控/UI 零影响。**

### 2.3 plan 当前是 free-floating,不是 subordinate

PlanTool plan 以 `agent_id` 为键(`plan_id == self.agent_id`,`reasoning_tools.py:1507,1553`),`StagedPlan/PlanStage/PlanTask` 数据模型里**没有任何 `task_id` / parent 字段**(`reasoning_tools.py:218-256`)。方向是**反的**:plan → fan-out 成 task,从无 task → plan 的归属。所以"plan 隶属于某个 company task"今天**不存在**,要新建。

**stage 在 PlanTool 里是强制的**:`_add_task` 没 stage_id 直接 `_stage_not_found`(`reasoning_tools.py:1891`),task 只存在于 `PlanStage.tasks`(无 plan 级 task 容器)。所以"从 PlanTool 去掉 stage"**不是改名级别,是真重构**。

---

## 3. 建议的目标模型

> **项目层** = milestone(`M{n}` 轮次) → **扁平 WorkHub task**(depends_on DAG + priority)。这是系统**唯一**的 "task",kickoff 在这里规划。**去掉 stage。**
>
> **agent 层** = 当一条 lane **claim 了 task T** 后,它的 plan 变成**绑定 `task_id=T` 的、私有的、per-task "structured think"**(我打算怎么实现 T / 怎么写这段代码)—— 一个更高级、结构化的 think。**不外溢到共享 task store。**

收益:"task"只剩一个含义(WorkHub),"plan"只剩一个含义(某 task 的私有 think),隶属清晰:**plan ⊂ task ⊂ milestone**;stage 这层冗余消失(顺序靠 depends_on、紧急靠 priority、分组靠 milestone 轮次,stage 不承担任何独立职责)。

---

## 4. 修改方向(分两个量级)

### Tier A — trivial(零行为变化,可独立先做)
1. **删 WorkHub stage**:task 去 `stage_id`,plan 去 `stages`,删 test-only 的 `tasks_by_stage`;`create_plan` 本就死,可一并删。

### Tier B — 真重构(把 2.1 的冲突和 2.3 的归属一起解决)
2. **停止 plan→task 外溢**:删 `_sync_plan_tasks_to_dev_tasks`(`dev:plan:...`)和 `_upsert_snapshot_task`(`plan:...`)两条物化路径。**保留**只读快照 `upsert_plan_snapshot` 供 observability(或改为不落 task 行)。—— 这一步直接消灭 C1/C2/C3。
3. **重定义 PlanTool 为 per-task structured-think**(顺带瘦身 2087 行):
   - 加 `task_id` 绑定:plan 以"正在做的 WorkHub task"为根,而非 agent_id。
   - 砍掉 **stage 层**(改成 task 下直接挂步骤/think 项)、**party 同步会话**、**跨 agent plan 共享**(workers 几乎不用:backend/frontend 的 `plan()` 只是"一行 direct-vs-team 模式",debugger 完全不用)。
   - **保留** acceptance("我怎么知道 T 做完了"),但绑定到 task。
4. **单向收口**:plan 做完 → 标记**那个 WorkHub task** complete(task 权威,plan 是私有 how);删除任何 plan↔task 的双向/last-writer-wins 路径。
5. **gate 收口**(若不立刻做 #2,过渡方案):finish 门 / assignee 门按 `metadata.source` 过滤,让 `source in {plan, legacy_plan_tool}` 的镜像任务**不参与门控** —— 这是不动 PlanTool 也能先止血 C1 的最小改动。

### Tier C — 治理 / 后续
6. M2+ 迭代 loop(当前 `milestone_index=1` 硬编码)是另一条线,见 `pipeline_post_kickoff_architecture.md` 的迭代层;本重构应让 milestone 仍是 task 之上的轮次层,不被 stage 干扰。

---

## 5. 与已有工作的关系

- **统一了两处发现**:上一轮的"WorkHub task ↔ agent plan 冲突"和本轮的"stage 没用"其实是**同一个重构**的两面 —— 核心动作是"plan 变成绑定 task 的私有 think + 停止外溢 + 删 stage"。
- **呼应评审报告**:`docs/pipeline_code_review_2026_06_03.md` 把 `reasoning_tools.py` 的 `PlanTool`(2087 行)列为拆分候选 —— 本重构比"拆分"更进一步:其中 stage/party/跨 agent 共享可**直接删**,而非搬家。
- 与 `skill-mandatory-trigger` 那个 PR **独立**,可分开走。

---

## 6. 开放决策 / 风险 / 不在范围

- **D1**:acceptance criteria 去留 —— 建议保留并绑定 task(它是"task 完成定义",有价值),但从 stage 解耦。
- **D2**:只读 plan 快照(observability)留不留 —— 建议留(live_monitor 的 plan 视图依赖 `📋 PLAN` 日志而非 WorkHub stage,所以删 task 行不影响 UI;但若想保留跨 agent 可见性,留快照页即可)。
- **D3**:`create_plan` / `tasks_by_stage` 删除会动到 5 个测试 —— 按 closed-by-construction 同步更新测试为"无 stage"不变量。
- **风险**:PlanTool 的 stage 是数据模型强制项(`_add_task` 依赖 stage),重构需迁移 task 容器到 plan/task 级;workers 用得少(降低风险),但 orchestrator 的固定 phase plan 是装饰性 legacy(`orchestrator_agent.j2:695` 自注"legacy fallthrough shape for clarity only"),可一并清理。
- **不在范围**:step pipeline 的执行 stage(`step_runner.py`)、milestone M2+ loop 的实现。

---

## 附录:关键证据索引

| 主题 | file:line |
|---|---|
| kickoff 发布扁平 task | `runtime/kickoff/run_kickoff.py:1042-1091`;`schema_tolerance.py:243-392` |
| create_task 无 stage 形参 | `runtime/hubs/workhub/service.py:203-241` |
| create_plan 零 live 调用 | `service.py:118-141`(+ prompts/docs/5 tests) |
| 调度只看 deps+priority | `service.py:443`(list_ready_tasks)、`:520`(available_tasks_for) |
| tasks_by_stage test-only | `service.py:602,612` |
| 交付门/deliverability/roadmap/ready_set 无 stage | `orchestrator.py:1497`;`deliverability.py`;`roadmap_validator.py`;`ready_set.py` |
| plan 外溢 task | `reasoning_tools.py:1501-1557`;`service.py:177-201` |
| finish 门 | `workflow_policies.py:927-964`(+ 3-strike `:745-758`) |
| APIHub→task closer | `service.py:392-445` |
| PlanTool 模型/单例/强制 stage | `reasoning_tools.py:218-256, 399-405, 1891, 1507/1553` |
| live_monitor stage 来自 PlanTool 日志 | `live_monitor_server.py:39, 909-1038` |
| milestone 是轮次 | `orchestrator.py:593`;`roadmap_validator.py:638,671`;`authoring.py:382-520` |
| orchestrator prompt 警告碰撞 | `multi_agent/agents/prompts/v3/orchestrator_agent.j2:203,216-227,695` |
