# Tier B 设计 memo:plan as `task.plan` subfield + UI 展开模块

**Date:** 2026-06-03  **Status:** 设计 (未实现)
**前置:** Tier A `f2229685` 已 ship — WorkHub stage 层已退役 (zero behavior change)
**驱动:** [docs/plan_task_stage_review_2026_06_03.md](./plan_task_stage_review_2026_06_03.md) §3 提的目标模型

---

## 0. 关键决策 (已锁定)

| 决策 | 选择 | 说明 |
|---|---|---|
| **D1: plan 存哪儿** | **`WorkHub task.plan` subfield** | 不是独立 store,不是 in-memory PlanTool。task 是 canonical 单元,plan 是 task 的子属性。一个权威位置,无 dual-canonical。 |
| **D2: UI 表现** | task 列表里**点击 task → 展开 plan 面板** | live_monitor 现有 WorkHub panel 加 expand 按钮,展开后渲染 stage(过渡期保留)/step/acceptance |
| **D3: plan ↔ task 状态映射** | **单向 + 显式** | `plan.completed=True` 不自动改 `task.status`;agent 必须显式 `workhub_complete_task`。但 prompt 在 plan 完成的 step 里**应该**教 agent 调 complete_task。 |
| **D4: Step 1 closer 去留** | **保留** | APIHub→WorkHub sync 治的是 kickoff-created `impl_endpoint/impl_table` 任务(那些不走 plan 通路,plan 是 agent 拿到 task 后写的 how)。Step 1 closer 在 Tier B 之后**仍然正确**。 |
| **D5: claim 之前的 plan?** | **in-memory only,不持久** | PlanTool 在 `claim_task` 之前可以让 agent 写探索性 plan(本地状态),但**只在 claim 时**才 bind 到 `task.plan` 并 flush 到 WorkHub。这避免了"无主 plan"污染共享 store。 |
| **D6: PlanTool stage 层** | **保留(初版),作为 plan 内部结构** | PlanTool 自身 stages/PlanStage/PlanTask 数据模型不改 — 它现在描述的是"我打算如何做这一个 task",stage 在这里有意义(implement / test / deploy)。**WorkHub stage 退役 ≠ PlanTool stage 退役。** |

---

## 1. Target 数据模型

```
WorkHub task (canonical):
  id, title, assignee, depends_on, status, claimed_by, ...
  plan: {                          # NEW: subfield, optional
    title: "...",                   # 取自 PlanTool plan_name
    stages: {                       # 复用 PlanTool 的 stage 表示
      "design": {tasks: {...}, ...},
      "impl":   {tasks: {...}, ...},
    },
    stage_order: ["design", "impl"],
    acceptance: [...],              # task 的"我怎么知道做完了"
    current_stage_id: "...",
    _updated_at: ts,
    _updated_by: agent,
  }
```

**没有独立的 `stores.plans` JSON 存储了** — 整个 `apihub_plans.json` 文件会被退役(或保留为空 + 加 deprecation 注释)。

**没有 `dev:plan:...` / `plan:...` 镜像 task 行** — 这两条物化路径整段删。

**PlanTool 在内存里仍然有 `self._plan: StagedPlan`** — 那是 agent 私有的 working state。只在 bound-to-task 状态下才 flush 到 `task.plan`。

---

## 2. 流程 (claim → plan → work → complete)

```
agent loop step N:
  1. (optional) PlanTool 在内存里更新 plan          # 本地 state
  2. agent 决定要 claim task T
  3. workhub_claim_task(T)
     → WorkHub 记 claimed_by=agent, status=in_progress
     → PlanTool 自动 attach task_id=T, flush 内存 plan 到 task.plan
                                                    # 一次 atomic upsert
  4. agent 实施(写 code、call apihub_register_endpoint(implemented)、etc.)
     → PlanTool 每步 self._plan 更新 → 每隔 K step 同步到 task.plan
  5. agent 调 workhub_complete_task(T)
     → WorkHub 记 status=completed
     → task.plan.status="completed" 也一起 set
     → live_monitor UI 仍然显示 plan(只读历史)
```

**finish() 门** (`workflow_policies.py:836`):
- 仍然按 WorkHub task 检查 unclaimed/pending tasks(同今天)
- 但 `dev:plan:...` 和 `plan:...` 镜像 task **不再存在**了 → C1/C2/C3 三个冲突直接消灭
- claim-assigned-tasks 只看真实 kickoff/orchestrator-created tasks
- → 跟 Step 1 closer 配合,完全干净

---

## 3. 子 PR 序列 (B1 → B4)

### **B1 — 停止 plan→task 外溢** (核心,先 ship)
**最小可独立 ship 的 change,直接消灭 C1/C2/C3 冲突。**

操作:
1. 删 `reasoning_tools.py:1515-1557` `_sync_plan_tasks_to_dev_tasks` 整个方法
2. 删调用方 `step_pipeline/helpers.py:100-112` 的 `_sync_plan_index_to_hub`(或者只保留 plan→`task.plan` 那条,不再触发 dev:plan 创建)
3. 删 `service.py:_upsert_snapshot_task` (此时还没接 `task.plan`,先单纯不 mirror)
4. 删 `upsert_plan_snapshot` 里的 stage 迭代部分(`for stage_id, stage in ...`)
5. 现有 `dev:plan:*` 和 `plan:*` 任务行在 in-flight workspace 里会变 stale → workflow_policies 的 3-strike auto-cancel 会兜底 (`workflow_policies.py:745-758`)

测试 update:
- `test_workhub_plan_migration.py` 大部分要重写或删 — 因为它们 pin "upsert_plan_snapshot → creates WorkHub task" 的旧行为,新行为是不 create task
- `test_finish_policy_composition.py` 中跟 dev:plan/plan: 镜像相关的 assertion 要 update

LOC 估计: -200/+50, 8 个文件。

### **B2 — `task.plan` subfield + claim 时 attach**
**给 task 加 plan 子结构,在 claim 时关联。**

操作:
1. `WorkHub.claim_task` 接受可选 `plan: dict` 参数,写到 `task.plan`
2. PlanTool 加 `self._task_id` (绑定的 WorkHub task)
3. PlanTool 加 `attach_to_task(task_id, hubs)` 方法 — 在 agent claim 后调
4. PlanTool 加 `_flush_to_task_plan()` 内部方法,每 N step 调一次
5. PlanTool 的 `complete_task` (本地 PlanTask 的 complete,不要跟 WorkHub.complete_task 混) flush 到 task.plan

新测试:
- `test_workhub_task_plan_subfield.py`:claim_task 接受 plan; task.plan 字段持久化;再读还能拿到
- `test_plantool_task_binding.py`:attach_to_task 后 PlanTool._task_id 设置;flush 写到正确的 task.plan

LOC 估计: +200, 6 个文件。

### **B3 — 退役 WorkHub plans store**
**整个 `apihub_plans.json` + plan-related 方法退役。**

操作:
1. 删 `WorkHub.upsert_plan_snapshot`, `get_plan`, `list_plans`, `update_plan_metadata` (整个 plan 子 API 退役)
2. 删 `stores.plans` (JsonStore handle + ensure_documents 列表)
3. 删 `apihub_plans.json` 写入路径(自然成为 stale file,可手动清理)
4. live_monitor: `_extract_plan_summary` 改成从 task.plan 重建(而不是从 `apihub_plans.json` + log 解析)

测试 update:
- `test_workhub_completeness.py` 的 TestGetPlan/TestListPlans/TestUpdatePlanMetadata **全删**
- live_monitor 的 plan 测试改成从 task.plan 读

LOC 估计: -300, 5 个文件。

### **B4 — PlanTool 瘦身** (跟主流程解耦,可后做)
**砍 PlanTool 内部不用的部分(reviewer 在 `pipeline_code_review_2026_06_03.md` 标了 2087 LOC 拆分候选)。**

操作:
1. 删 PlanTool 的 **party-sync 会话**(`_start_party`/`_complete_party`等,完全死代码)
2. 删 PlanTool 的 **跨 agent plan 共享**(workers 几乎不用)
3. 评估是否值得**去掉 stage 层** — D6 决定保留,所以这步可能 noop

LOC 估计: -500-1000, 1 个文件。

---

## 4. UI design (live_monitor `WorkHub panel`)

### 当前
- WorkHub panel 列出所有 page (kind=design/spec/etc) + 所有 task
- task 显示:id, title, status, assignee, claimed_by, depends_on
- 点击 page 进入详情;**点击 task 无详情**

### Tier B 后
- task 行加一个 ▶ 展开按钮 (chevron right)
- 点击展开 → 内嵌面板显示 `task.plan`:
  ```
  ┌─ task: impl.endpoint.post._api_auth_register ─────────────┐
  │ status: in_progress · claimed_by: backend                  │
  │ depends_on: impl.table.users                               │
  │                                                            │
  │ ▼ PLAN: "Implement POST /api/auth/register"                │
  │   acceptance:                                              │
  │     ✓ POST returns 200 + non-empty token                   │
  │     ✓ Duplicate email returns 409                          │
  │   stages:                                                  │
  │     ▼ design [completed]                                   │
  │         · choose bcrypt rounds                             │
  │         · spec validation rules                            │
  │     ▼ implement [in_progress] ← current                    │
  │         · write auth route handler                         │
  │         · wire bcrypt hash                                 │
  │     ▷ test [pending]                                       │
  │         · happy path test                                  │
  │         · 409 path test                                    │
  │                                                            │
  │ updated_at: 12s ago by backend                             │
  └────────────────────────────────────────────────────────────┘
  ```

### 实现要点
- 复用现有 `hub_panels.jsx` 的 task list 渲染逻辑
- 加 `<TaskRow expandable>` 组件,展开后 fetch `task.plan` 子结构(已经在 task dict 里,**不需要额外 API call**)
- stage/step tree 用现成 jsx 树渲染 pattern
- 点击 task ID 仍跳详情页(不变);展开 ▶ 只展开 plan 那一层

LOC 估计 (jsx): +150, 2-3 个文件 (`hub_panels.jsx` + 新组件 + 可能小幅改 CSS)。

---

## 5. 风险 / 边界

| 风险 | 缓解 |
|---|---|
| in-flight smoke 用了旧 `dev:plan:*` 任务路径 | B1 落地时:auto-cancel 兜底 + 旧 workspace 自然 rot;新 workspace 不会创建 |
| PlanTool 内存 plan 在 agent crash 时丢失 (claim 前未 flush) | 这是 by design (D5) — claim 前的 plan 是 exploratory,不持久;crash 后 agent restart 重新规划成本可接受 |
| `task.plan` blob 可能很大 (deep nested stages) | WorkHub task 已经用 JsonStore + atomic write,大 JSON 没问题;但要 cap 单 task.plan 大小(比如 100KB)以防 prompt 注入式膨胀 |
| live_monitor UI 不兼容旧 workspace (没有 task.plan) | UI fallback:task.plan 为空时不显示展开按钮;旧 workspace 自然降级 |
| 多 agent 共写一个 task.plan? | task 只允许 1 个 claimed_by;只有 claimer 能 flush 自己的 plan → 单写者,无并发 |

---

## 6. Step 1 closer 跟 Tier B 的关系 (复述)

Step 1 (commits `386666ad` + `6cfa0d26`):APIHub.register_endpoint(implemented) 自动 complete 匹配的 WorkHub `impl_endpoint` task。

- 这条 closer 跟 plan/task 关系**正交** — 它处理 kickoff-created 任务(那些是 orchestrator 在 finalize 时通过 `workhub.create_task` 直接写的,**不走 plan 通路**)。
- Tier B 删除 plan→task 外溢后:这条 closer **不变,保留**。
- 一句话:Tier B 是 plan 那一侧的清理;Step 1 是 kickoff impl 任务那一侧的 closer。两条独立。

---

## 7. 顺序建议

```
今天:  [DONE] Tier A
        [DONE] Tier B 设计 memo (本文)

下一步: B1 (停止 plan→task 外溢) ← 一个 PR, 最高 leverage 也最小风险
        smoke 验证 (claim-assigned-tasks 6 unclaimed 还出现吗?)

之后:   B2 (task.plan + claim attach)
        smoke 验证 (UI 渲染对吗?)

之后:   B3 (退役 WorkHub plans store)
        UI 改造

可选:   B4 (PlanTool 瘦身)
```

每步独立可 ship + 独立可回滚。

---

## 附录:跟 review doc §6 的 D1/D2/D3 对照

| review doc 的 open decision | 本 memo 决策 |
|---|---|
| **D1**: acceptance criteria 去留 | ✓ 保留,绑定到 task.plan.acceptance (D1 in this memo) |
| **D2**: 只读 plan 快照 (observability) 留不留 | task.plan 子字段就是 observability surface,live_monitor 直接读 (D2 in this memo) |
| **D3**: create_plan / tasks_by_stage 删除 | ✓ Tier A 已 ship |
