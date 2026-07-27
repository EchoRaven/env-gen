# forgingground-gen Pipeline 优化 — 交接文档（2026-07-02）

> 目标读者：接手继续优化 env-gen pipeline 的工程师。
> 本文档覆盖：北极星目标、当前状态与战绩、全部 51 项修复账本、代码/仓库/基础设施地图、
> 运行与诊断手册、已知陷阱、剩余前沿与建议路线。
> 配套材料：`docs/pipeline_full_architecture.html`（全 pipeline 架构 + 每个 gate 逻辑 + mermaid 流程图）、
> `/data/common/haibotong/outlook_components/PIPELINE.md`（视觉保真方法论）。

---

## 0. TL;DR

- **北极星**：`python -m env_generator.llm_generator.main` 一条命令，从纯文本需求自主生成
  **完整、可用、无 mock** 的多里程碑 Web app（FastAPI+Postgres 后端、React/Vite/Tailwind 前端、
  OAuth2 RS256、MCP server、真实种子数据、Docker 编排），agent 自主规划 milestone 并逐个交付，
  test-user 并发多种测试并反馈闭环。**约束：所有修复必须 env-agnostic（不许偏向 outlook）。**
- **当前状态**：目标的"客观质量"部分已达成 —— 5 次完整 SUCCESS（run-30/33/35/37/38），
  run-38 所有客观信号全绿；种子数据链端到端验证（授权种子活在交付 DB、demo 登录可用）。
- **剩余主战场**：视觉保真（advisory 级 visual_mismatches 收敛）；次要：run-40 静默死亡类、
  搁置的 #35、若干装饰性问题。
- **修复账本**：#1-#51，全部在 `vaibackup/forgingground-gen` 分支 `feat/pipeline-opt-4`（HEAD `9b71f92`）。
  PR: `https://github.com/vaibackup/forgingground-gen/compare/main...feat/pipeline-opt-4?expand=1`

---

## 1. 仓库 / 基础设施地图

### 1.1 仓库
| 项 | 值 |
|---|---|
| 代码检出 | `/data/common/haibotong/forgingground-gen` |
| 规范远端 | `vaibackup` = `git@github.com:vaibackup/forgingground-gen.git`（**canonical**）|
| 死远端 | `origin` = Virtue-AI/forgingground-gen（**仓库已删除，勿用**）|
| 推送密钥 | **默认 `~/.ssh/id_ed25519`**（GitHub 账号 EchoRaven）。`id_ed25519_virtueai`（haibotong-pixel）对这个 repo 无权限 —— 与其他 Virtue-AI 仓库正好相反！repo 已 `git config core.sshCommand` 固定 |
| 工作分支 | `feat/pipeline-opt-4`，HEAD `9b71f92`，比 `vaibackup/main` 领先 77 commits |
| 提交规范 | **不要加 Claude Co-Authored-By 尾注**（用户明确要求）|

### 1.2 仓库纪律
- repo 只放**可发布代码**。开发测试（`agent/tests/`）、运行脚本（`run_*.sh`）、日志、`generated/`
  全部 gitignored —— **测试是本地资产，接手请勿删除工作区**。
- 工作区有一个**故意未提交**的改动：`heal_pipeline.py` 里 #35（param 路由排除）—— 用户两次拒绝
  提交其测试更新，按指示**搁置**。见 §6.3。

### 1.3 生成引擎入口
```
cd /data/common/haibotong/forgingground-gen
nohup bash run_outlook.sh > outlook_run<N>.log 2>&1 &     # N 递增，当前到 41
```
- `run_outlook.sh` 内部：`agent/` 下 `python -m env_generator.llm_generator.main --name outlook
  --description <完整需求文本> --output generated --reference-dir reference_images/outlook
  --provider google --model gemini-3.1-pro-preview --fresh`
- Python 解释器：**`/home/haibotong/miniconda3/envs/dt/bin/python`**（跑测试也用它）
- 工作区：`generated/outlook/`（git repo，`integration` 分支 + 每 lane 一个 `worktrees/<lane>` 检出）
- 端口（自动分配，通常）：API 宿主 3001、UI 8080、PG 5433；容器名 `docker-{backend,frontend,database}-1`
- Hub 状态（一切协作状态的真相源）：`generated/outlook/shared/hubs/*.json`
  （registryhub_endpoints / registryhub_verification_chains / eventhub_* / workhub_*…）

### 1.4 监控面板（用户主要看这个）
| 端口 | 是什么 |
|---|---|
| **22100** | agentsuite-red-frontend（Vite，"Virtue AgentSuite"）。环境列表 → 点 **`outlook`**（无后缀）= 当前 CLI run 实时状态。22101 是重复实例（可杀）|
| **8095** | env-forge 后端 `uvicorn app.main:app`（cwd=forgingground-gen）。**自动发现** `generated/*` 目录为环境；`/env-forge/environments/outlook/state` 返回实时 progress/agents/gates。刚修了 `_live_updated_at`（活跃 run 按 hub mtime 浮顶列表 + naive-UTC 时区坑），**改 `app/main.py` 后必须重启 uvicorn** |
| 4210 | 独立 EnvForger Monitor（`live_monitor_server.py`），与 CLI run 无关，`/api/runs` 为空属正常 |

---

## 2. 架构速览（细节见 HTML 文档）

**核心原则："by construction"** —— 契约面（endpoints/tables/auth/DDL/handlers/seed loader/构建设施）
由框架从 RegistryHub 契约**确定性投影**，LLM lane 的职责收缩为"编写契约 + 领域内容"；
LLM 写坏的东西用**确定性 repair pass** 修，而不是提示它重写。

- **多 agent**：orchestrator + backend / frontend / verifier lane（常驻，serial consumer）；
  milestone 循环：kickoff → implement → test → deliver，每个 milestone 出一个 release（v1.0.0…）。
- **门（按序）**：api_smoke/RunHub（硬前置）→ `_validate_delivery_gate`（business_chain、
  deliverability 家族、ui_page 接线）→ page-build → visual-fidelity（advisory + 修复任务）→
  test-user squad → **浏览器 test-user 门**（#14：objective-unusable 即 hold，bounded deferral
  防死锁，到点"loudly"放行）→ release cut。跑完全部 milestone 后还有**终局硬门**
  （orchestrator.py `_validate_delivery_gate`，失败=整个 run FAILED）。
- **deliver_project 守卫**（#20+#39）：deliver 只在"终局门会通过"时被接受，否则拒绝并继续收敛。
- **修复走道（heal pipeline）**：每个验证周期 + 交付前运行的确定性 repair 集
  （转义字符族、图标 import、默认导出包装、auth import、router 前奏、DDL-from-ORM、种子 json 保障等）。

---

## 3. 战绩与证据（截至 2026-07-02 17:00）

| Run | 结果 | 说明 |
|---|---|---|
| 30 | ★SUCCESS | **首个 4-milestone 完整交付**（v1.0.0→v1.3.0, rc=0），API+浏览器验证可用 |
| 31 | FAILED | M1+M2 干净收敛交付（deferral 0 逃逸）；死于终局门 ui_page_unwired+竞态 → 催生 #38/#39 |
| 32 | FAILED | 同类（过早 deliver）→ #39 |
| 33 | SUCCESS | 3/3 milestone；#39 反向验证（合法 deliver 未被误拦）|
| 34 | FAILED | 隔离探针全挂（custom_routes NameError + 未 scope 投影读）→ #44/#45 |
| 35 | ★SUCCESS | 4 releases + **种子链端到端验证**：#41 门逼 lane 创作 seed → #37 装镜像 → #36 指纹重播 → **demo@example.com 活在交付 DB，登录可用** |
| 36 | FAILED | 第三种字面 `\n`（模板表达式内）→ #48 |
| 37 | SUCCESS | 2 milestones |
| 38 | ★SUCCESS | **最干净**：所有浏览器报告全绿（auth_ok=T, blank/console/wall=∅, hollow=F），终版验证 tenants 200 / auth-me 200 / 零页面错误 |
| 39 | FAILED | 全端点 500（JWT sub 字符串 vs int owner 列）→ #51 |
| 40 | 中断 | v1.0.0-1.2.0 交付后 **16:37 进程静默死亡**（卡在一次 Gemini 调用后消失，无终止记录）→ **待查类**，见 §6.2 |
| 41 | 进行中 | 17:00 启动，完整 #25-#51 栈 |

**判断**：backend/auth/种子/隔离/测量类问题已连续多 run 无新增 —— 客观质量前沿收口。
新 run 的失败模式集中在前端 LLM 手误（确定性 repair 逐类吃掉）与稳定性长尾。

---

## 4. 修复账本（#1-#51）

> #1-#24 已在 commit `e143613`（详见该 commit message 与 memory 文件）；此处重点 #25-#51。
> 每项都有：live 复现 → env-agnostic 修复 → `agent/tests/` 单测。SHA 均在 `feat/pipeline-opt-4`。

### 控制面填充族（"契约声明了但投影器排除、lane 又不写"）
| # | SHA | 内容 |
|---|---|---|
| 25 | 7fdcf7d | `_custom_route_overrides_projected` 误丢 auth/oauth 前缀下的 custom `/me` → 保留 |
| 30 | ae06cb2 | `/api/auth/me`+`/auth/me` **only-if-absent 填充**（ProtectedRoute 会话恢复靠它；登录墙根因）|
| 49 | 4981604 | `/api/v1/tenants` 填充（TenantPicker 挂载即调、中间件已放行 /api/v1/*）|

### 种子数据链（"populated on first load"）
| # | SHA | 内容 |
|---|---|---|
| 36 | 919bc84 | 种子指纹：loader 只填空表 → 首启 fallback 永久遮蔽授权 seed；现指纹变更即 TRUNCATE…RESTART IDENTITY CASCADE 权威重播（`_seed_meta` 表存指纹）|
| 37 | a64fa19 | **seed_data.json 根本没进镜像**（Dockerfile 只 COPY *.py）→ `COPY *.py *.json` + 保障空 `{}` 恒存在（glob 无匹配会 fail build；only-if-absent 不覆盖授权内容）|
| 41 | dfa437a | 授权种子 deliverability 硬门（**不被 functional-validation 豁免**）：json 空/缺 → blocker，文案自带创作指令 |
| 43 | ffb1893 | 该 blocker 的 remediation owner 映射 → backend lane（确定性派单）|

### 交付可靠性（run 级成败）
| # | SHA | 内容 |
|---|---|---|
| 38 | 246f3ee | 终局门就绪重试：mid-restart 评估（sql_tables 4/11、链挂）杀死健康 run（28/31 两杀）→ `wait_backend_ready` + 重评一次 |
| 39 | 627a14a | deliver 守卫复用 `compute_deliverability` 全量聚合器 → 前端 mid-flight 时 deliver 被拒、run 继续收敛（31/32 两杀根因）|
| 29 | 7dea647 | 链 expect 全 2xx 时任意 2xx 通过（verifier 猜错成功码 201/204 永久假失败）；**含非 2xx 的期望保持精确**（隔离探针不放宽）|
| 32-34 | 7aa1d95 | 链执行器三缺口：owner-scoped 空列表 → **ensure-via-create** 恢复；URL 空格/非 ASCII → `_safe_url`；步骤漏 `auth` 引用 → 401 时用已存 token 重试一次（仅当通过期望才采纳）|

### 隔离（跨用户读保护）
| # | SHA | 内容 |
|---|---|---|
| 44+45 | 974873f | run-34 双叠加：custom_routes 用 `@router` 没定义 `router`（NameError 静默丢整个 router）→ 前奏修复；**全骨架**渲染点未合并"隔离探针⇒owner-scope"信号（此前只有缺失路由填充点合并）→ scaffolder 渲染前把 probed 表并进 metadata |
| 51 | 9b71f92 | JWT sub 字符串 vs int owner 列 → pg `integer = character varying` 全端点 500；14 处发射点统一走 `_fw_uid()`（数字→int，uuid/text 原样）|

### 前端确定性 repair 族（"构建过但页面崩/空白"）
| # | SHA | 内容 |
|---|---|---|
| 28 | 102d650 | 字面 `\n` 形态②：语句边界（`}\n\nexport function`）|
| 48 | 763ed32 | 字面 `\n` 形态③：模板字面量 `${...}` 表达式内（引号感知，`split('\n')` 保留）（形态①转义反引号=#15）|
| 40 | d5727cc | JSX 用了未 import 的图标（构建过、渲染 ReferenceError）→ 从 lucide-react 确定性补 import（safe-icon 插件保证真图标渲染/未知名降级占位，**防崩**）|
| 47 | e3de2b2 | `export default { api };` 包装对象 → 默认导入成员调用 undefined → 单标识符解包（仅当该名是顶层 export）|
| 31 | 1427acb | lane import 的三方包不在 pyproject（asyncpg）→ ModuleNotFoundError 静默丢全部 custom routes；`render_pyproject` 扫描 import 并集依赖 + 嵌套 ImportError 大声记日志 |

### 测量准确性（浏览器 test-user 门的假信号）
| # | SHA | 内容 |
|---|---|---|
| 26 | 71036a5 | 只 walk 真 SPA 路由（丢掉 route=源文件路径/组件名的垃圾 ui_page 注册）|
| 27 | eff6cc5 | 前端容器 mid-restart → 就绪轮询，起不来记 ran=False（跳过而非误判 unusable）|
| 46 | cfe00c0 | "前端起/后端未起"窗口（登录静默失败+空壳无报错）→ API-base 就绪轮询 |

### 视觉保真轴（当前主战场）
| # | SHA | 内容 |
|---|---|---|
| 50 | 0d88a2e | 视觉修复任务内嵌**实测组件 spec**（`design/component_specs/<screen>.json` 的 bg/accent hex）——此前 lane 全程只读过一次 spec、靠目测修 |
| 42 | 779a03f | prompt 规则：useEffect 不稳定对象依赖=无限拉取=页面挂死（run-33 /calendar 类）+ JSX 标识符必 import |

（其余 #1-#24 摘要：安全图标 Vite 插件、坐标分解、visual-gate、链 FK×3、种子哈希/登录、
export 漂移、custom-read、verifier 隔离、**浏览器交付门 #14**、转义反引号 #15、投影占位符丢弃 #16、
Session.cursor #17、spine FK 型 #18、coverage-by-construction #19、deliver 守卫 #20、
链 list 恢复 #21、raw-row 编码器 #22、text-PK uuid 默认 #23、**业务链绿后冻结 #24**。）

---

## 5. 运行与诊断手册（实战 SOP）

### 5.1 监控一个 run
```bash
L=outlook_run41.log
# 里程碑/终止信号
grep -E "cut release|GENERATION COMPLETE|Status:|STUCK-ABORT|NO-CONVERGENCE|shutdown watchdog" $L | tail
# 浏览器门报告（最关键的健康信号）
grep -E "BROWSER test-user \(v1|DELIVERY DEFERRED|gate RELEASED" $L | tail
# 验证循环状态
grep -E "api_smoke (PASSED|NOT passing)" $L | tail -3
```
判读：`auth_ok=True blank=∅ console=∅ wall=∅ hollow=False` = 健康;
`DELIVERY DEFERRED` = 门在正常 hold（lane 修复中）；`gate RELEASED (escape...)` = 兜底放行（要复查原因）。

### 5.2 Live 诊断三板斧（容器活着时）
```bash
BP=$(docker port docker-backend-1 | grep -oE '0.0.0.0:[0-9]+' | head -1 | cut -d: -f2)
# ① API 探针
TOK=$(curl -s -X POST http://localhost:$BP/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"probe@example.com","password":"Probe123!x","name":"P"}' | python3 -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))")
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:$BP/api/auth/me -H "Authorization: Bearer $TOK"
# ② 后端 traceback
docker logs docker-backend-1 2>&1 | grep -B2 -A12 Traceback | tail -30
# ③ 浏览器实测（playwright 在 dt env 里）——console/pageerror/network 三监听，模式见
#    /tmp/.../scratchpad/diag*.py（或自写 10 行脚本：goto → innerText 长度 + console error）
```
**种子/demo 登录**：seed 密码固定 `"password"`；真正入库的用户看 DB：
`docker exec docker-database-1 sh -c 'PGUSER=sandbox PGDATABASE=app psql -t -c "SELECT email FROM users ORDER BY id LIMIT 3"'`

### 5.3 链（business_chain）取证
真相源 `generated/outlook/shared/hubs/registryhub_verification_chains.json`：
每条链有 steps/expect/save + `last_result.broken`（含实际 status 与响应片段）。
**热解卡**：链执行器每周期**重读该文件** —— 直接改 JSON（如把全 2xx expect 拓宽）下个周期生效。

### 5.4 修生成物（hot-fix 一个活 run）的规则
- 生成物在 `generated/outlook`（integration 分支）+ **每 lane 的 `worktrees/<lane>`**。
  改文件必须**两处都改并各自 commit**，否则 lane 分支 merge 会把坏文件带回来。
- **框架代码改动对活 run 无效**（进程启动时已 import）；且骨架每周期/交付时**字节级重断言**
  pyproject/Dockerfile/main.py 等 —— 对这些文件的 hot-fix 会被抹掉（run-29 亲历）。
  结论：框架修复 → 只对下一个 run 生效；活 run 只能改"框架不重写"的文件或 hub JSON。

### 5.5 测试
```bash
cd agent && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest tests/<file>.py -q
```
- 每个修复配一个 `tests/test_*.py`（docstring 记 live 复现 run 号）。
- **有 34 个预存失败**（kickoff/prompt 一致性等历史债）—— 不是回归，别去修观感。

### 5.6 已知陷阱
- `pgrep -f "llm_generator.main"` 会**自匹配**你自己的 bash —— 用 `ps -eo args | grep "[e]nv_generator"`。
- 后台等待 grep 别用宽词（`create_release` 会匹配工具名）；用精确日志串。
- env-forge DB 时间戳是 **naive UTC**；比较时别用本地时间（刚踩过）。
- Bash 工具禁止裸 `sleep`；用 `until <cond>; do sleep N; done` 或 run_in_background。
- 一次只跑**一个** run（共享 workspace + 端口）。

---

## 6. 剩余前沿（建议路线）

### 6.1 视觉保真（主战场，通往"完美"）
现状：结构/主题已接近（暗色 Mica、文件夹栏、徽标数都对），差距按杠杆序：
1. **信息密度/状态分布**（最大）：种子行数与真实感 —— #36/37/41/43 已打通供给侧，
   下一步是 seed 质量门（行数下限/占位词检测已有 seed_audit，可升硬）。
2. **确定性颜色 diff 门**（设计好未建）：spec hex（`design/component_specs/*.json`）vs
   截图同 region 采样色 → 每组件色距超阈值 = 具名 deviation。素材齐全：material_prep.py
   有采样代码、spec 有 region+hex、浏览器门有截图。这是 #50 的下一级。
3. **zoom_compare 采纳**：Phase B 后 lane 应对每组件 2x 放大对比 —— 工具在 surface 里但零调用，
   考虑 remediation 文案里直接下达（同 #50 手法）或作为 page-build 门的一步。
4. 背景资产（真实图片 vs 模糊块）：用户明确 LATER（web-scrape 资产，注意 IP 边界：§PIPELINE.md）。

### 6.2 run-40 静默死亡类（稳定性）
进程卡在一次 Gemini 调用后消失（16:37），无异常、无终止记录、无 OOM 痕迹。
V30 时代加过 re-entrancy guard + dead-turn watchdog（`9b54ca9`），但这次是**主进程消失**。
排查方向：LLM client 的无超时等待？uncaught exception 在 nohup 下丢失？
建议：给 main 加顶层 crash 日志（sys.excepthook + faulthandler.enable 到文件）再复现。

### 6.3 #35（搁置，等用户决定）
浏览器 walk 对 param 路由（`/inbox/message/:id`）按字面导航 → 假空白。
heal_pipeline 的排除改动**在工作区未提交**（测试更新被用户两次拒绝）。
三个选项：提交现方案（跳过 param 路由）/ 回滚 / 改为解析真实 id 再 walk。**动之前问用户。**

### 6.4 小项
- lane 把组件碎片注册成 ui_page（/calendar-grid 等瘦路由）→ 注册校验或提示收紧。
- 过早 delivered 信号（orchestrator LLM drift）—— #39 已兜住后果，根因（LLM 纪律）未动。
- 22101 重复 Vite 实例可杀；8095 现由 nohup 跑（`scratchpad/envforge_8095.log`），宿主重启需拉起。

---

## 7. 关键文件索引

| 路径（相对 repo） | 作用 |
|---|---|
| `agent/env_generator/llm_generator/multi_agent/orchestrator.py` | 主循环、milestone 循环、终局门（~1640）、浏览器门（~2456）|
| `.../runtime/backend_skeleton.py` | 后端全量投影：_MAIN_HEADER、_CUSTOM_ROUTES_INCLUDE（含 me/tenants 填充、路由 dedup）、pyproject/Dockerfile、种子 loader（指纹）、`_fw_uid` |
| `.../runtime/route_projector.py` | 缺失路由投影、owner-scope 过滤器发射、参数类型 |
| `.../runtime/chain_executor.py` | 链执行：`_status_ok`（2xx 族）、id 恢复四级 fallback、auth auto-attach、`_safe_url`（在 validation_runner）|
| `.../runtime/delivery_gate.py` | 交付门聚合 + deliverability 检查 canonical 化 + coverage-by-construction |
| `.../runtime/deliverability.py` | compute_deliverability（#39/#41 的共享聚合器）|
| `.../runtime/heal_pipeline.py` | 修复走道调度 + 隔离表推导 + **#35 未提交改动在此** |
| `.../runtime/frontend_scaffold.py` | 前端 repair 族（\n×2、反引号、图标、默认导出包装、api 导出对账）|
| `.../runtime/test_user_runner.py` | 浏览器 test-user + 就绪门（前端/API）+ browser_report_unusable |
| `.../runtime/visual_fidelity.py` | 视觉门 + remediation_text（#50 spec 内嵌）+ `_seed_demo_login` |
| `.../runtime/remediation_dispatcher.py` | 门检查 → lane 派单 owner 映射（#43）|
| `.../runtime/material_prep.py` + `tools/material_prep_tools.py` | 采样/裁剪/调色板/分解 agent 工具 + 预生成 component_specs |
| `app/main.py`（repo 根）| env-forge 8095 后端（面板数据源；改后须重启 uvicorn）|
| `agent/tests/` | 全部修复的本地单测（gitignored）|

## 8. 记忆/上下文文件（Claude 侧，供后续 AI 会话）

- `~/.claude/.../memory/project_envgen_material_prep_phase.md` —— **最全的逐 fix 日志**
  （每项 live 复现、SHA、run 后验尸），接手 AI 会话先读这个。
- `~/.claude/.../memory/reference_github_ssh_virtueai_key.md` —— 推送密钥/远端演变史。

---
*编写：Claude（pipeline 优化 autonomous loop），2026-07-02。运行中的实验：run-41（#25-#51 全栈）。*

---

## 9. ADDENDUM（2026-07-02 晚，#52-#56）

接手会话按 §6 路线 + instagram/INSTAGRAM_OPTIMIZATION_GUIDE.md 方法论落了 5 个修复
（本地 commit `d5f1386` / `b848dac` / `441e1fe` / `2e4f863`，未推送）：

| # | 内容 | 备注 |
|---|---|---|
| 52 | **确定性颜色 diff 门**（§6.1-2 落地）：`material_prep.spec_color_deviations` — spec 分数 region + 实测 hex vs 门截图同 region row-mode 采样，redmean 距离（`ENVGEN_COLOR_DIFF_THRESHOLD`=40）；accent_missing=语义色丢失（仅全图缺该色相才报，滤参考图内容噪声）。remediation 内嵌精确 hex 事实 | visual_fidelity 每屏附 `measured_deviations` |
| 53 | **zoom_compare 采纳**（§6.1-3）：remediation 内嵌**可直接执行**的调用 — staged `design/references/<name>` 相对路径、必填 `save_as`、最差偏差 region、scale=2 | 30-38 run 零调用的根因=教的调用跑不起来 |
| 54 | **授权种子质量门**（§6.1-1 升硬）：行数下限（`ENVGEN_SEED_MIN_TOTAL_ROWS`=10，字符串行=0 也拦）+ 每表 ≥2 个严格占位词（词边界；**不含** test/sample/bar/tbd）。非豁免 blocker → token `deliverability_authored_seed_quality` → `_GATE_OWNER`→backend。`ENVGEN_SEED_QUALITY_GATE=0` 关 | ⚠对抗 review 杀掉了两个草案信号（sequential 名规则会误伤 `msg_1` 式 FK id / 'Room 101'）；⚠gate 级 token 路由走 `_GATE_OWNER` 而非 `_CHECK_OWNER`（#43 时代的 #41 条目也是死的，已一并补） |
| 55 | **crash 取证**（§6.2）：main.py import 时武装 — faulthandler→`envgen_crash.log`（`ENVGEN_CRASH_LOG`，=0 关）+ 链式 sys/threading excepthook + 退出标记（atexit + watchdog os._exit 路径显式 note）。解读：traceback=崩溃 / 标记=有序退出 / 只有 armed 行=外部 kill(OOM) | run-40 类下次可一读定性 |
| 56 | **种子序列同步**（run-41 活体致死原因）：授权种子显式整数 id 不推进 SERIAL 序列（且 #36 的 RESTART IDENTITY 每次重播归零）→ 种子后每个 INSERT 撞主键 → register 永 500 → api_smoke 卡死。生成 loader 新增 `_sync_sequences`（setval→MAX+1，NULL 保护，仅 pg），fresh-apply 与同指纹早退**两个路径**都调 | DB 热修无效（验证周期 down -v 重建）|

流程：4 视角 finder + 每 finding 双怀疑者对抗验证（Workflow 42 agents）：13 confirmed 全修复、
2 refuted。**硬门经验：非豁免门上线前必须过 false-block 对抗审查。**
60 个新增本地测试全绿；触及子集的其余失败均经 git-stash 基线证为预存债务。

RUN 状态：run-41 FAILED（#56 类，17:20）；run-42 已杀（launch 早于 review 修复，进程内是
会误拦的草案门）；**run-43 = 17:52 起的全栈验证 run**（观察点：种子门驱动密度且不误拦、
remediation 出现 MEASURED COLOR DIFF、zoom_compare 首次被调用、序列跨重播不再撞、
agent/envgen_crash.log 退出标记）。

### 9.1 追记（同日晚，#35 落地 + #57 + 面板提交）

用户解除两处搁置授权后：**#35 完整版**落地（`94b2c7d`）——param 路由不再一刀切跳过，而是
`resolve_param_route` 以种子 demo 用户从后端取真实行 id 再 walk（详情页获得确定性覆盖）；
**仅 id 形参数**才解析（:slug/:tab 解析成行 id = 伪路由假空白，对抗审查击杀）；解析失败退回跳过。
`test_browser_walk_skips_filepath_routes.py` 已按新契约更新。**面板修复提交**（`3ace93b`）：
`_live_updated_at` + tz-aware 归一（Postgres TIMESTAMPTZ 场景），8095 已重启生效。
**#57**（`b358d47`，run-43 活体）：空括号参数 `DELETE /api/messages/{}` → 投影出非法 Python →
backend 崩溃循环 → backend_port 永远解析不到。register_endpoint 现在拒绝非标识符 `{...}`（报错
含改法），投影器对已入库垃圾做 `{param_N}` 消毒（两个发射路径共用的 `_generate_handler` 单点）。
run-43 已杀（内存 contract 带 `{}`，热修会被回写）；**run-44 = 全栈 #25-#57 + #35 完整版验证 run**。
工作树已全清（无未提交改动）。
