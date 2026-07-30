# HANDOFF — env-gen pipeline 质量优化（UI 相似度 / test-user 完备度 / 交付 app 功能完整度）

> 交接日期 2026-07-13。前任 session（下称"监督者"）已在此 pipeline 上完成 #128-#147 共 20 个 live-caught 修复，
> 累计 24 个完整 SUCCESS run。你（新 session，下称"执行者"）接手三大**质量**方向的优化 + 日常 run 监控循环。
> 监督者初期会通过 `SUPERVISION_LOG.md`（同目录）审阅你的工作并给指引 — **协议见 §9，必须遵守**。

---

## §0 一句话使命

在 `forgingground-gen` 的多智能体 env 生成 pipeline（branch `feat/pipeline-opt-6`）上，把优化重心从
"run 能否成功交付"（已稳定）转向"**交付出来的 app 质量**"：
1. **UI 相似度**：视觉分数真正突破 0.65 门槛（现在从来不是真通过，全靠逃逸放行）；
2. **test-user 丰富度**：browser test-user 的 journey 覆盖每个页面、每个交互，而不是 3 步冒烟；
3. **功能完整度**：交付 app 的每个按钮/表单/导航都有真实功能，无死控件、无占位页、无缺失 action 端点。

---

## §1 环境与关键路径

| 项 | 值 |
|---|---|
| 仓库 | `/data/common/haibotong/forgingground-gen`（生成器框架，git repo） |
| 分支 | `feat/pipeline-opt-6`，HEAD `bfa4a39`（#147）。**用户自己 merge PR，你只 commit+push** |
| 远端 | `vaibackup`（github.com:vaibackup/forgingground-gen.git）。push 用**默认 key**：`GIT_SSH_COMMAND="ssh -i ~/.ssh/id_ed25519" git push vaibackup feat/pipeline-opt-6` |
| Python | `/home/haibotong/miniconda3/envs/dt/bin/python`（跑测试和 pipeline 都用它） |
| 框架代码 | `agent/env_generator/llm_generator/`（下面 §3 有模块地图） |
| 测试 | `agent/tests/`（**gitignored，local-only，永不 commit**；pytest 直接跑） |
| API key | `source /tmp/envgen_key.sh`（导出 GOOGLE_API_KEY；**只在启动 run 时需要**） |
| 生成产物 | `generated/instagram-core-di`（活 run）；归档 = `mv` 成 `.SUCCESS-runNN-*` 或 `.runNN-<死因>` |
| run 日志 | 仓库根 `ig_designprep_runNN.log`（当前活 run = **run-73**，PID 485281，2026-07-12 22:47 启动） |
| 磁盘 | `/data` 95%、约 203G 空闲——稳定，但**每次归档前必须 `docker compose -p docker down -v`** |
| 记忆文件 | `/home/haibotong/.claude/projects/-data-common-haibotong/memory/project_envgen_designprep_phase.md`——完整 #110-#147 修复日志和每个 run 的尸检，**开工先读一遍**（很长，重点读末尾 #138 以后） |

**用户偏好（硬性）**：commit 不加 `Co-Authored-By` trailer；中文对话；决策点用 AskUserQuestion 给选项。

---

## §2 Pipeline 是什么（30 秒版）

`python -m env_generator.llm_generator.main` 启动一个多智能体生成 run：
- **orchestrator**（LLM+框架混合）主持 kickoff（自定 3-4 个里程碑计划）→ 每个里程碑：契约综合 → backend/frontend/verifier 三条**驻留 lane**（各自 LLM agentic loop）实现 → 框架验证（docker_up→api_smoke→business_chain→视觉门→browser test-user）→ delivery gate 全绿 → cut release vX.Y.0。
- 全部里程碑交付 = SUCCESS（`run_budget.json` status=delivered，rc=0）；7 周期无进展 = STUCK-abort；75min gate 不绿 = FAIL-FAST。
- 生成目标：FastAPI+React/Vite/Tailwind+Postgres 的 Instagram 克隆（`--design-input design_inputs/instagram` 提供 11 张参考截图 + 真实资产）。

**启动命令（必须从 agent/ 目录）**：
```bash
cd /data/common/haibotong/forgingground-gen/agent
source /tmp/envgen_key.sh
nohup /home/haibotong/miniconda3/envs/dt/bin/python -m env_generator.llm_generator.main \
  --name instagram-core-di \
  --output /data/common/haibotong/forgingground-gen/generated \
  --design-input /data/common/haibotong/forgingground-gen/design_inputs/instagram \
  --provider google --model gemini-3.1-pro-preview-customtools \
  --description "Instagram web clone: auth, home feed of posts, explore grid, post detail, profile, DMs." \
  > /data/common/haibotong/forgingground-gen/ig_designprep_runNN.log 2>&1 &
```
⚠ **PID 陷阱**：launch 后 `pgrep -f "miniconda3/envs/dt/bin/python -m env_generator.llm_generator.main"` 取**python 真 PID**，别记 wrapper bash 的。

---

## §3 模块地图（改哪个文件做什么）

全部在 `agent/env_generator/llm_generator/multi_agent/` 下：

| 文件 | 职责 | 与你使命的关系 |
|---|---|---|
| `runtime/visual_fidelity.py` | **视觉门全部**：参考图→路由映射(`map_reference_screens`)、截图(`capture_route_screenshots`，含 #141 主题仿真+#141b history)、LLM judge(`judge_screen_pair`+`_JUDGE_INSTRUCTIONS` rubric)、verdict 缓存(#142)、VisualFidelityGate(sticky-pass #129 / plateau #138 / seed 提醒 #133)、remediation_text | **方向 A 主战场** |
| `runtime/material_prep.py` | design-input 参考图确定性测量：调色板、每屏组件规格(`design/component_specs/*.json` 含 MEASURED 颜色)、theme_inversion | 方向 A（组件规格已存在但前端使用率低） |
| `runtime/design_prep.py` | `--design-input` 一次性 pre-gen：`ingest_assets` 把真实资产 stage 到 `design/assets/` + analyst 富化 design_system.json（#132 每屏 kind/requires_auth/route 分类） | 方向 A（**真实资产 stage 了但前端不用** = 已知最大杠杆） |
| `runtime/frontend_audit.py` | ui_page 静态审计：路由接线(#146 drift 容忍)、**dead controls**(`_page_dead_controls`)、占位 stub 检测、`audit_asset_usage`（资产使用 advisory）、`ui_page_delivery_blockers` | **方向 C 主战场** |
| `runtime/test_user_runner.py`（tur） | **browser test-user**：Playwright 驱动真浏览器跑 journey（现在 ~3 步 API journey + UI login），blank-retry | **方向 B 主战场** |
| `runtime/validation_runner.py` | docker_up→api_smoke 框架验证；docker_up 错误 tail 捕获(3000 字符) | 基础设施，一般不动 |
| `runtime/chain_executor.py` | business_chain 执行：`${var}` 恢复阶梯 + #136 字面 id 重试 + #144 seed 档、`synthesize_default_chain`(tier-1 CRUD 链) | 方向 B/C（链是 API 层的"test-user"） |
| `runtime/remediation_dispatcher.py` | 失败→owner 路由：`_CHECK_OWNER` 表、#143 docker_up 内容路由、GATE-CHECK 派发（verifier 需 `metadata["validation_phase"]=True`） | 方向 C（run-72 action 端点类的修复入口，见 §8） |
| `runtime/backend_skeleton.py` | 框架 owned 的 backend 骨架：database.py/seed loader(#130/#135 upsert)/`_fw_uid`/`_fw_owner_val`(#134)/cursor shim(#131) | 一般不动 |
| `runtime/route_projector.py` | 契约→FastAPI 路由投影（CRUD by construction；action 端点**不投影**，lane owned——run-72 死因） | 方向 C |
| `runtime/registryhub.py` | 端点/链注册表；`_chain_eid` #137 字面 id 折叠 | 少动 |
| `orchestrator.py` | 主循环+delivery gate+`_visual_release_decision`(#138 plateau/#145 idle/3600s anchor 逃逸)+`_final_gate_drift_waiver`(#139)+STUCK/FAIL-FAST | 逃逸参数在这 |
| `agents/runtime/messaging.py` | 驻留 lane 消息/唤醒：策略过滤、busy-defer、**#147 busy-wedge 看门狗** | 已修，别轻动 |
| `agents/runtime/step_runner.py` | agentic loop；`_last_step_activity` 戳(#147) | 少动 |
| `prompts/v3/*.j2` | 各 lane 的 prompt：`frontend_agent.j2`（含 use-real-assets 规则）、`design_analyst.j2`、`verifier_agent.j2` | 方向 A/B 的 prompt 侧杠杆 |

---

## §4 已完成修复栈速查（#128-#147，全部已 push）

只列与你使命直接相关的（完整日志在记忆文件）：

- **#128** overlay 参考图 → advisory 非阻塞；**#132** analyst 把每屏 kind/requires_auth/route 写进 design_system.json（权威分类，正则退 fallback）
- **#129/#129b** sticky per-screen pass（屏一旦某轮 ≥0.65 即 latch；remediation 跳过已 latch 屏）
- **#133** judge 报告 empty_state → 框架派 backend P1 补 seed
- **#138** plateau 早逃逸（4 轮无 all-time-best 提升 + ≥1500s deferral → 放行）——run-67/70 已两次现场触发（~41-43min vs 3600s）
- **#141** dark/light 屏名 → capture 仿真主题（emulate_media + storage keys + reload + 强制 class）；**#141b** 每 judge 轮截图存 `design/visual_gate/history/`
- **#142** (屏名, 截图 md5) verdict 缓存——相同像素恒定分数，judge ±0.3 噪声归零（这是 #138 能干净触发的前提）
- **#145** idle-source 逃逸（≥1500s deferral 且 600s 无新判定 → 放行；源冻结=分数已定）
- **#143** docker_up build 失败按错误内容直派 frontend/backend；**#146** 声明路由 vs 实现路由 drift 容忍；**#147** lane busy-wedge 看门狗（600s 无 step 活动=WEDGED，强制复位+当场接任务——run-72 已验证自愈）
- **#136/#137/#144** business_chain 字面 id 404 的三层恢复（同资源捕获 id → live list → **seed_data.json id** → global last_id）

**视觉窗现状（重要）**：逃逸三件套让最终里程碑视觉窗从 ~65min 降到 ~41-43min，**但从来没有一次真正 PASS**（所有屏同时 ≥0.65 从未发生，sticky-pass 也没集齐过）。分数天花板 ~0.5-0.55。**你的方向 A 就是把它变成真 PASS。**

---

## §5 方向 A：UI 相似度（最重）

### 现状与已知根因
1. **真实资产不被使用**：design-prep 已把 IG wordmark、手机 mockup 等真实资产 stage 到 `design/assets/`（前端构建时进 `public/assets/`），`frontend_agent.j2` 有 use-real-assets 规则，`audit_asset_usage`（frontend_audit.py）有 advisory——但历次 run 前端仍然自己画通用 UI，wordmark 不用。run-50 实证：login 参考图是 IG 两栏品牌设计（左 wordmark+手机 mockup，右表单+Meta logo），实现是通用居中卡片 → judge 0.2-0.4 **判得对**，不是 judge 过严（不要走"放水 judge"方向，已否定）。
2. **remediation 执行力**：judge 反馈（per-screen deviations/fixes/missing components + `_measured_deviations` #52 的确定性色差）已经很扎实，但前端消化不充分——改几轮就 plateau。
3. **component_specs 未被强制消费**：material-prep 为每屏生成了含实测颜色的组件规格 JSON，前端 prompt 里有引用但无 hard gate。

### 建议路径（按 ROI 排序，你可自主调整但要在 LOG 里说理由）
- **A1 资产使用从 advisory 变 blocking-with-teeth**：`audit_asset_usage` 目前只出 advisory 文本。改成：对"参考图中出现品牌资产（wordmark/logo）的屏"，若 staged 资产未在对应页面组件中被引用 → 加入视觉 remediation 的**首条** fix（点名文件+资产路径+目标位置），并考虑在 delivery gate 加软性检查。判定"参考图含品牌资产"可用 design_system.json 的 analyst 分类扩一个字段（仿 #132 模式：`_SCREEN_TOOL` schema + `_run_analyst` harvest + `_merge_enrichment` 三处联动，有现成先例）。
- **A2 remediation 结构化到组件级**：remediation_text 现在是文字清单。试验：把 component_specs 的 MEASURED 颜色/布局值直接内联进任务描述（"左栏宽 245px、背景 #FAFAFA"），减少前端再读文件的摩擦。
- **A3 每屏首轮建立"骨架对齐"**：分数 0.0→0.4 的跳变多因布局骨架错（单栏 vs 两栏）。考虑在 M1 前端首建时就把 component_specs 的布局骨架作为 scaffold 注入（projected page stub 已存在，见 route_projector 的 page stub 逻辑）。
- **验证标准**：某个 run 出现 `Visual fidelity PASSED`（真过或 sticky 集齐）即里程碑；分数天花板从 0.55 → 0.65+。用 `design/visual_gate/history/` 对比轮次演化。

### 危险清单（别踩）
- 不要改 0.65 阈值放水；不要给 judge prompt 加"宽容"指令（run-50 已否定）；不要动 #142 缓存语义（改像素才改分是 remediation 的正确契约）。
- 视觉子集回归：`pytest tests/test_visual*.py tests/test_sticky_visual_pass.py tests/test_theme_variant_capture.py tests/test_verdict_cache_by_pixels.py tests/test_screen_classifications.py`（当前 95+ 全绿）。

## §6 方向 B：test-user 丰富度

### 现状
`runtime/test_user_runner.py`：每里程碑交付前跑一次——API journey（~3 步，register/login/一两个业务端点）+ UI login（Playwright 点真按钮）+ 页面 blank/console 检查（run-64 抓过 blank profile 派 P0，工作正常但覆盖浅）。日志形如 `TEST-USER validation (v1.1.0): PASS — 3/3 API journey steps passed`。

### 建议路径
- **B1 journey 从契约生成**：kickoff 的 feature_inventory 有 entities/flows；把每个 flow 展开成 UI journey（如 "创建帖子 flow" = 登录→点 create→填 caption→提交→在 feed 断言新帖出现）。可复用 chain_executor 的链定义翻译成 Playwright 步骤（链已是 register→create→list→read 结构）。
- **B2 每页交互扫描**：对 App.jsx 每条路由：导航到页 → 枚举可见 button/form/link → 逐个点击/提交 → 断言（无 console error、无 404 网络请求、页面有状态变化）。这和方向 C 的 dead-controls 静态检查形成动静互补。
- **B3 报告结构化**：test_user_reports/ 已有产物目录；把覆盖率(页面×交互)写进报告，给 delivery gate 一个可选的丰富度下限。
- **验证标准**：journey 步数从 3 → 每 flow ≥5 步、页面覆盖 100%；抓到至少一个静态审计漏掉的真 bug 即证明价值。

## §7 方向 C：交付 app 功能完整度

### 现状
- 静态：`_page_dead_controls`（有 form/button 无 handler → block）、占位 stub 检测（#126 组合页容忍）、`deliverability_ui_page_unwired`(#146 drift 容忍)。
- 动态：business_chain 全端点冒烟；browser test-user（浅）。
- **已知洞**：**run-72 死因** = 契约注册的 ACTION 端点（`POST /api/users/{id}/unfollow`）lane 没实现，projection 又按路由所有权规则不代投影 → 永久 404，remediation 派给 verifier（错 owner，verifier 只能改链不能加路由）→ 7 周期 STUCK。**该类第 1 次出现已记录，你大概率会再遇到 = 修复许可已预授**（记忆文件里standing方向，标 #148）：
  - 方案1（轻）：仿 #143——business_chain 失败 detail 含 "action endpoint not implemented" → P0 直派 **backend** 带端点清单；
  - 方案2（重）：route_projector 对注册 action 端点合成默认 handler（unfollow=DELETE follows 行——语义推断有风险，谨慎）。
  - 建议先做方案1（确定性、低爆炸半径），观察是否够。
- CRUD-create 缺失有 #76 兜底；action 端点没有对应物。

### 建议路径
- **C1 = #148**（上述方案1），第一优先——它是当前唯一已知的 hard-STUCK 未修类。
- **C2 按钮→端点可达性矩阵**：frontend_audit 已解析每页 apis_used；反向做一遍——契约里每个端点是否被至少一个 UI 控件调用（未被调用的端点=孤儿功能，advisory→remediation）。
- **C3 与 B2 联动**：动态点击扫描发现的死按钮 → 派 frontend P0（带文件+控件名）。

---

## §8 未修 backlog（继承）

1. **#148 候选**（run-72 action 端点类）——见 §7 C1，最优先。
2. **P4 path-param 写时预防**：`path-param heal` 运行时修复 13 个 run 触发 211 次（lane 重写 custom_routes.py 就重犯 str/int 注解）。方向：lane 写入时确定性变换或 prompt 规则。中优先。
3. **DELIVER_PROJECT LLM drift 限流**：orchestrator LLM 漂移 150+ 次/13 run，守卫都拦住了只是浪费 token。低优先。
4. **跨环境验证**：所有修复只在 instagram-core-di 验证过。换一个 design-input（如 youtube/outlook 素材）跑全流程是对 env-agnostic 声称的真考验。**用户已知悉并倾向优先**——何时做听用户/监督者安排。

## §9 沟通协议（必须遵守）

- 共享文件：`/data/common/haibotong/forgingground-gen/SUPERVISION_LOG.md`（已建好，含格式模板）。
- **你每完成一个工作单元**（一个修复落地/一个 run 归档/一个方向的设计决定），向 LOG **追加**一条 `[EXEC]` 条目：做了什么、为什么、证据（文件:行/日志行号/测试结果）、下一步。**开工后第一条**：你对本 handoff 的理解摘要 + 首期计划（监督者会核对理解偏差）。
- 监督者会追加 `[SUPERVISOR]` 条目给反馈/指引/纠偏。**每次开始新工作单元前先读 LOG 尾部**有无新 `[SUPERVISOR]` 条目；有指引则优先响应。
- 重大方向决策（改 gate 语义/动阈值/大重构）：先在 LOG 写 `[EXEC-PROPOSAL]` 等监督者回复，或直接 AskUserQuestion 问用户。
- 不要修改/删除对方的条目；条目带时间戳。

## §10 日常运行纪律（从监督者继承，逐字执行）

1. **监控循环**：用 /loop 自我调度 ~20min 一 tick；每 tick 查活 run（`ps -p <PID>`、grep `cut release|STUCK|abort|WEDGED`、tail 日志）；SUCCESS→`docker compose -p docker down -v`→归档 `.SUCCESS-runNN-*`→立即启下一 run；STUCK→**趁容器活着热诊断**（活 DB psql、curl 端点、读 visual_gate/history）→定位根因→**框架侧修复**（热补生成目录不粘，#113/#130/#131 三次实证）→abort→归档 `.runNN-<死因>`→带修复重启。
2. **verify-cause**：修复前必须读实际工件（截图/DB 行/HTTP 响应/build tail），一次出现=记录，重复=修；曾两次差点为"非 bug"造修复（docker_up 截断显示、plateau 判分）。
3. **TDD**：每修复先写测试（`agent/tests/test_*.py`，参考现有测试的 sys.path 注入模式；async 用 `asyncio.run` 不用 pytest.mark.asyncio）；回归跑相关子集；失败先 `git stash` 对比 base **且警惕假基线**（收集错误会显示 base 0 failed——按文件重跑 base 确认）。
4. **commit**：单修复单 commit，message 格式看 `git log`（现象→根因→修法→测试）；**不加 Co-Authored-By**；push `vaibackup feat/pipeline-opt-6`。
5. **记忆**：每个 run 结局 + 每个修复追加到记忆文件（格式模仿现有条目：★RUN-NN = ...）。
6. 不要在用户测试环境时 docker-reset；两个 run 不并发。

## §11 首期任务（建议顺序，前两个完成前不要开新线）

1. **接管 run-73**（PID 485281，日志 `ig_designprep_run73.log`，4 里程碑计划，已过 M2）：按 §10 监控到结局、归档、重启 run-74。这是你熟悉全流程的实操课。
2. **实现 #148（§7 C1 方案1）**：TDD + 推送。小而关键。
3. 在 LOG 写方向 A 的**设计提案**（A1 优先），等监督者反馈后动工。
4. 之后按 A → B → C2/C3 推进，每个方向的验证都以真实 run 的日志/工件为准。
