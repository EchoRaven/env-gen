# HANDOFF — env-gen pipeline 质量门硬化（交付 app 真的可用 / 真显真实数据 / 硬不可用不逃逸）

> 上一份 `HANDOFF_2026-07-13_quality_pipeline.md` 聚焦 instagram 的视觉/test-user/功能三方向。
> 本份聚焦 **2026-07-14~15 在 Google Maps 新环境上逼出的一类"交付了却不可用/显 mock"的门缺陷**，
> 已修 #151/#152/#153，本文交接**剩余门缺陷 + 跨环境验证**。先读 §0，再读 §4（已修栈）和 §7（首期任务）。

---

## §0 一句话使命

Pipeline 现在**能稳定交付**（run 走完全里程碑），但交付出来的 app 屡屡**运行时不可用或显假数据却被放行**。
把优化重心放在**交付门的诚实性**：让"用户打不开/看不到真实数据"的 app **无法被标记为 delivered**，
并把根因**准确报给 lane** 使其真能修好。三条已修，四条待修（§6 backlog）。

**★铁律（血泪教训，务必遵守）**：**代码"看似接对"≠运行时 work**。本环境上我（前一 session）
连续两轮只读代码就下"接对真实数据了"的乐观结论，都被 playwright 运行时打脸（run-3 是 mock 双胞胎、
run-4 是裸 fetch 无 token→401）。**任何"已修好/已接对"的判断，必须 playwright 亲验运行时**
（登录进去 + 真看到数据），或用 pytest 对**真实归档**跑断言，别只读代码。

---

## §1 环境与关键路径

| 项 | 值 |
|---|---|
| 仓库 | `/data/common/haibotong/forgingground-gen`（生成器框架，git repo） |
| 分支 | `feat/pipeline-opt-6`，HEAD `083e011`（#153）。**用户自己 merge PR，你只 commit+push** |
| 远端 | `vaibackup`（github.com:vaibackup/forgingground-gen.git）。push 用**默认 key**（repo 已配 `core.sshCommand=ssh -i ~/.ssh/id_ed25519`）：`git push vaibackup HEAD:feat/pipeline-opt-6`。⚠ **别用 id_ed25519_virtueai**（Virtue-AI repo 已 DEAD，会报 Repository not found） |
| Python | `/home/haibotong/miniconda3/envs/dt/bin/python`（跑测试、pipeline、playwright 都用它） |
| 框架代码 | `agent/env_generator/llm_generator/`（§3 模块地图） |
| 测试 | `agent/tests/`（**gitignored，local-only，永不 commit**；`cd agent && …/python -m pytest tests/xxx.py -q`） |
| API key | run 需要 GOOGLE_API_KEY。**本 AFK session 无 key**（无法启动真 run）；有 key 时 `source /tmp/envgen_key.sh` 或用户提供 |
| Design-input | `design_inputs/google_maps/`（29 参考图 + ~70 资产含 63 Material Symbols SVG + docs + **dataset/**：places 171/reviews 248(含 3 injection 槽)/transit_stops 188/transit_lines 170/routes 8/saved_lists 4，**整数 id**） |
| 生成产物 | `generated/googlemaps-core-di.*`：4 个归档（gmrun1 死于 id 类型、gmrun2 kickoff timeout、**gmrun3 = 首个真实数据全交付但前端 mock**、**gmrun4 = 4 里程碑全交付但前端裸 fetch 401**） |
| 启动脚本 | `./run_googlemaps_designinput.sh <N>`（含防双跑 + 自动停旧 `-p gmaps` demo；**两 run 不并发**） |
| 记忆文件 | `~/.claude/projects/-data-common-haibotong/memory/`，本环境相关：`project_envgen_designprep_phase.md`（design-prep + F1-F3 dataset 通道）、`project_envgen_material_prep_phase.md`（#1-#77 修复日志，读末尾）。**开工先读**。 |

**用户偏好（硬性）**：commit **不加** `Co-Authored-By` trailer；中文对话；决策点用 AskUserQuestion 给选项；
**沟通走 `SUPERVISION_LOG.md`**（append `[EXEC]`/`[EXEC-PROPOSAL]` 条目，见 §9）。

---

## §2 Pipeline 是什么（30 秒版）

`cd agent && python -m env_generator.llm_generator.main --name … --design-input … --provider google --model gemini-3.1-pro-preview-customtools`
启动多智能体 run：

- **orchestrator**（LLM+框架混合）主持 kickoff（自定 3-4 里程碑）→ 每里程碑：契约综合 →
  backend/frontend/verifier 三条**驻留 lane**（各自 LLM agentic loop）实现 → **框架验证链**
  （docker_up → api_smoke → business_chain → 视觉门 → **browser test-user 门**）→ delivery gate 全绿 → cut release vX.Y.0。
- 全里程碑交付 = SUCCESS（`run_budget.json` status=delivered, rc=0）；连续无进展 = STUCK-abort；75min gate 不绿 = FAIL-FAST。
- **Design-prep（`--design-input`）一次性 pre-gen**：确定性测量（调色板 + `ingest_assets` 真实资产→`design/assets/`
  + **F1 `ingest_dataset` 真实 dataset→`design/dataset/`**）+ analyst 富化 design_system。
  **F2 双源 seed loader**：框架 owned `seed_dataset.json` 合并覆盖 lane `seed_data.json`。
  **F3 Leaflet+OSM 地图**：tile URL 免 localizer + `<map_surface_template>`（`{% raw %}` 包裹防 Jinja 破坏 JSX）。

---

## §3 模块地图（改哪个文件做什么）

全部在 `agent/env_generator/llm_generator/multi_agent/` 下：

| 文件 | 职责 | 与本使命的关系 |
|---|---|---|
| `runtime/test_user_runner.py` | **browser test-user 门**：Playwright 驱动真浏览器（`run_browser_test_user`）；`_finalize_walkthrough`（滚 auth_ok/blank_pages/hollow_frontend/**no_real_data**）；`browser_report_unusable`（**HOLD 交付谓词**）；`browser_gate_decision`（**#152 硬不可用不逃逸**）；**#153 `salient_seed_values`/`real_data_verdict`/`extract_seed_display_values`（真实数据断言，纯函数）** | **本使命主战场** |
| `runtime/frontend_audit.py` | ui_page 静态审计：路由接线、dead controls、占位 stub、**#151 mock-twin 检测**（`audit_ui_page` 里路由接了 mock 双胞胎→flag "STATIC MOCK"）、`ui_page_delivery_blockers`（`_HARD_MISS_MARKERS` 含 "STATIC MOCK"→硬阻塞） | **生成时拦截层** |
| `runtime/heal_pipeline.py` | `_run_browser_test_user`（组装 pages + 调 `run_browser_test_user`，**#153 在此 `extract_seed_display_values(proj)` 传 seed_values**）；repair_frontend_api 等 | test-user 调用点 |
| `orchestrator.py` | 交付流：`_run_test_user_validation`→heal_pipeline；**browser 门 escape 逻辑在 ~2813-2866**（`browser_report_unusable`→bounded defer→`browser_gate_decision`→cut/hold）；DEFERRED 日志（#153 加 no_real_data） | 门的编排 |
| `runtime/visual_fidelity.py` | 视觉门全部：`map_reference_screens`、`capture_route_screenshots`、`judge_screen_pair`、VisualFidelityGate（plateau/idle/anchor 逃逸）、`_seed_demo_login`/`_mint_token` | 方向 A（视觉，本份未主攻） |
| `runtime/material_prep.py` | design-input 确定性测量 + **F1 `ingest_dataset`/F2 `assemble_seed_dataset`（file stem **原样**做表名，无 _slug）/F2b `_dataset_columns`** | dataset 通道 |
| `runtime/design_prep.py` | `--design-input` pre-gen：**F1 `resolve_design_input` 加 dataset_dir + F2b `design_system_summary_for_requirements` 的 BINDING REAL DATASET 块**（backend 据此建 schema） | dataset 通道 |
| `runtime/backend_skeleton.py` | 框架 owned backend 骨架 + **F2 双源 `_load_rows()`（seed_dataset 覆盖 seed_data）+ `_ensure_seed_dataset()`** | 一般不动 |
| `runtime/frontend_scaffold.py` | 前端脚手架 + **F3 `_is_map_tile_url()` 免 localizer + leaflet/react-leaflet 入 `_COMMON_FRONTEND_LIBS`** | 地图 |
| `runtime/remediation_dispatcher.py` | 失败→owner 路由；**#148 `action_unimplemented_broken()`/`_chain_action_404s()`（action 端点 404 链失败→backend）** | 方向 C |
| `runtime/chain_executor.py` | business_chain 执行；`synthesize_default_chain` | 方向 B/C（链=API 层 test-user） |

---

## §4 已修栈速查（本使命，全部已 push feat/pipeline-opt-6）

**核心洞见**：run-3 和 run-4 都**全里程碑交付**、后端真实数据完全打通（psql 验证 places=171 等 + 3 injection 载荷入库），
但**前端两个 run 都不显真实数据**，失败方式不同，且都逃过了旧门：

| # | commit | 修什么 | 抓哪个 run |
|---|---|---|---|
| **#148** | (opt-6 早) | action 端点 404 链失败→P0 直派 backend（内容路由，仿 #143） | gmrun action-GET 类 |
| **F1/F2/F2b/F3** | (opt-6) | dataset 通道：ingest→双源 seed loader→requirements binding→Leaflet 地图。**整数 id dataset**（gmrun1 死于 slug-vs-int） | Google Maps 真实数据落地 |
| **#151/#151b** | `ea1058c`/`ec3b4d1` | **mock-twin 静态检测**：前端建了 mock 双胞胎（`SearchResults` 硬编码 + `SearchPage` 接 API），App.jsx 路由接 mock 版，接 API 版孤儿。`audit_ui_page`：page 声明非空 apis + wired element≠声明 component + wired 无 api call → flag "STATIC MOCK"→硬阻塞交付 | **gmrun3（mock）生成时** |
| **#152** | `5d5d6eb` | **硬不可用不逃逸**：`browser_gate_decision`——auth_ok=False 或 hollow_frontend **永不 escape-release**（→FAIL-FAST STUCK 比交付死 app 诚实）；SOFT 保留 bounded escape；`ENVGEN_TESTUSER_HARD_GATE=0` 关 | **gmrun4（裸 fetch 401→login wall）** |
| **#153** | `083e011` | **B 真实数据断言**：browser test-user 收每页 innerText，断言至少一个 seed 真实值（地名/作者/地址）渲染在任一页→抓 mock/占位/裸fetch。`no_real_data`→`browser_report_unusable` HOLD 交付（SOFT，保 bounded escape）；`format_feedback` 报根因 | **gmrun3（mock）运行时兜底** |

**#151（生成时静态）与 #153（运行时）互补**覆盖 run-3 mock 类；**#152** 覆盖 run-4 硬不可用类。

**#153 关键设计（复用/别破坏）**：
- `salient_seed_values`：跨列 **round-robin** 防冗长列（描述/地址）挤占地名；**name/title/label 列保留行序 + 排最前**，
  使**首屏 first-by-id 地名**被覆盖（默认列表渲染的是前几行，不是最长的）。
- `real_data_verdict`：**全局断言**（任一页任一值命中即过，容忍需 query 才填充的页）；
  **checked=False（无 seed 值/无页面文本）→自跳过**，绝不误报纯静态 app；大小写不敏感**全值**子串匹配（防偶合）。
- `no_real_data` 走 **SOFT**（bounded escape 仍适用），**不同于 #152 的硬 defer**——防罕见"全页 query-gated"的正确 app 被误报死锁。

---

## §5 已知门缺陷全景（run-3/run-4 尸检结论）

| 失败方式 | run | 旧门为何漏 | 已修? |
|---|---|---|---|
| 前端 mock 双胞胎（路由接硬编码假数据版，接 API 真版孤儿） | run-3 | ui_page 门只验"声明组件被 wired"，不验 wired 组件真调 api；无孤儿检测；视觉门/test-user 见 mock 有文本不报 | ✅ #151（静态）+ #153（运行时） |
| 裸 fetch 无 token 调 authed /api/→401→login wall | run-4 | test-user **抓到**（auth_ok=False）但**逃逸放行**（9614s/7 attempts）；lane 修 7 次没中因诊断只报 blank 没报根因 | ✅ #152（不逃逸）+ #153 报根因；⚠ **静态检测裸 fetch 缺 token 未做**（见 §6-1） |
| backend cold-start crash（custom_routes.py 坏 middleware，import 时 `await None()`→每请求 500） | run-3 | delivery 复用里程碑中途的旧 api_smoke（05:15），backend 在最后 smoke 之后、交付之前又改了代码（05:34），门没重跑 smoke | ❌ **未修**（见 §6-2） |
| 地图 Leaflet 渲染 0 tile（有网时也空白，容器 size/init bug） | run-3 | 视觉门看空白判低分但逃逸；test-user 验 blank/console 不验富组件（瓦片是否真渲染） | ❌ **未修**（见 §6-3） |
| routes 表 0 行（`steps` 是嵌套 list-of-dict，backend 建成 String 单列，插入失败） | run-3 | 次要（8 条合成路线，非核心） | ❌ **未修**（见 §6-4） |

---

## §6 未修 backlog（按 ROI 排序；每条含根因 + 建议 + 危险清单）

### 6-1. 【中高】静态检测：组件对 authed `/api/` 的裸 `fetch()`（run-4 的直接死因）
- **根因**：`SearchResultsList.jsx:13` 用裸 `fetch('/api/places/search?q=…')` **不带 Authorization token**（不走 api.js 的 authed 封装）→ 后端要 auth→401→空。`api_smoke` 用框架 token 测端点 200，测不到前端组件的 token 接线；#151 的 `_has_real_api_call` 见 `fetch(` 就算数，不查带没带 auth。
- **建议**：在 `frontend_audit.py` 加检测——组件源码里对 `/api/`（非 `/auth/login` 等公开端点）的**裸 `fetch(`（同一调用点无 `Authorization` header 且不经 `api`/`apiClient` service）→ flag。TDD：mock 组件源码字符串，断言裸 fetch 被 flag、走 api service 的不 flag、对公开端点的裸 fetch 不 flag。
- **危险**：别误伤合法的公开端点裸 fetch（登录/注册/健康检查）；别误伤 `fetch` 在 api service **定义内部**（那才是正确封装处）。

### 6-2. 【中】交付门无"最终代码态 fresh smoke"（run-3 cold-start crash 的类）
- **根因（精确时序实锤）**：最后 api_smoke PASSED @05:15 → 视觉窗逃逸 RELEASED @05:33 → **backend EDIT custom_routes @05:34-35（引入坏 middleware）→ cut release @05:37**。delivery 复用里程碑中途记录的旧 smoke，视觉门只验前端像素不重跑后端 smoke → late backend edit 直达交付。
- **建议**：交付前（cut release 那步）若 backend 源在最后一次 api_smoke **之后**有改动（比对 mtime/git hash），**强制重跑一次 fresh api_smoke**，失败则 hold。入口在 `orchestrator._maybe_framework_deliver` / delivery gate。TDD：合成"smoke 时间戳 < backend 源改动时间戳"→断言门要求重验。
- **危险**：别每 tick 都重跑（贵）；只在"有 post-smoke 后端改动"时触发。

### 6-3. 【中】富交互组件是否真渲染（地图/图表）——run-3 地图 0 tile
- **根因**：MapCanvas Leaflet 渲染 0 tile（tiles count=0，非网络——宿主 + cartocdn tile 都 200），容器 size/init 时机 bug。视觉门看空白判低分但逃逸；browser test-user 验 blank/console 不验"主交互组件是否真渲染内容"。
- **建议**：test-user 走查时对**声明含地图/图表/canvas 的页**，用 playwright 断言关键子元素真渲染（如 `.leaflet-tile` 数 > 0，或 canvas 有非空绘制）。可做成 domain-agnostic 的"富组件渲染断言"：从 ui_page 声明或组件源推断该页应有地图/图表，然后 DOM 探针验证。
- **危险**：别硬编码 `.leaflet-tile`——用可配置/推断的选择器集；地图瓦片**离线确会空**，务必先确认宿主有网再判（run-3 的坑：离线会空但有网时空白根因是 lane bug）。

### 6-4. 【低】routes 表 0 行（嵌套 list-of-dict 落 String 列）
- **根因**：`routes.json` 的 `steps` 是嵌套 list-of-dict，backend 建成 `steps Column(String)` 单列 → loader 插入嵌套结构失败（对比 `saved_lists.place_ids`=list of int 能 str 化故进）。
- **建议（择一，框架 loader 最通用）**：F2 双源 loader 在 `backend_skeleton._load_rows()` 把 list/dict 值对 String 列 **JSON-序列化**（惠及所有嵌套字段 dataset）。TDD：合成含嵌套 list-of-dict 的行 + String 列 → 断言序列化后可插入。
- **危险**：只在目标列是 String/Text 时序列化；别动本就该是 JSON/ARRAY 列的。

### 6-5. 【验证】跨环境 keyed run 验证本使命全部修复
- 本 AFK session **无 API key**，#151/#152/#153 全靠**对真实归档跑 pytest 断言**验证（run-3 mock 已实证 rendered=False；run-4 shape 已单测）。
- **有 key 后**：跑一次 `./run_googlemaps_designinput.sh <N>` 看 #153 是否在生成时真的 HOLD 住 mock/裸fetch 前端并逼 lane 修好 → 看能否产出**首个前端真显真实数据**的 gmaps run。同时确认 #152 不误 STUCK 正常 run。也可跑一次 instagram 确认这些 domain-agnostic 门在其它环境零回归。

---

## §7 首期任务（建议顺序）

1. **开工先读**：`SUPERVISION_LOG.md` 尾部（#152/#153 条 + 05:40 起的 gmrun3/4 尸检）+ 本文 §4/§5/§6 + 两个 memory 文件。
2. **验证现状（别信我，自己验）**：`cd agent && …/python -m pytest tests/test_real_data_assertion.py tests/test_browser_hard_unusable_no_escape.py tests/test_wired_mock_twin_gate.py -q`（应 28 绿）。若想复现实证：对 `generated/googlemaps-core-di.SUCCESS-gmrun3-*` 归档跑 §4 里的 extract+verdict（mock→rendered=False）。
3. **做 §6-1（裸 fetch 无 token 静态检测）**——run-4 直接死因、ROI 最高、纯静态可 TDD、无 STUCK 风险。TDD 严格 RED→GREEN。
4. **做 §6-2（fresh smoke）或 §6-3（富组件渲染）**——按你判断的 ROI，先在 LOG 里说理由。
5. 每条修复：TDD（`agent/tests/` local-only）→ 编译检查 → 回归子集 → commit（**不加 Co-Authored-By**）→ push vaibackup → append `[EXEC]` 到 SUPERVISION_LOG.md。
6. **有 key 时**做 §6-5 keyed 验证。

**做完前两个门修复前不要开新线**（保持每次一个可验证的门缺陷）。

---

## §8 沟通协议（必须遵守）

- 所有进展/决策 append 到仓库根 `SUPERVISION_LOG.md`，用 `[EXEC]`（已做）/`[EXEC-PROPOSAL]`（提议待定）前缀 + 时间戳。
- 监督者/用户会读 LOG。需要用户定优先级/权衡时用 AskUserQuestion 给选项（首选项标"(推荐)"）。
- **诚实汇报**：门修复务必区分"代码写了"vs"运行时验证过"。用真实归档 pytest 或 playwright 亲验，别下代码乐观结论（这是本环境最大教训）。

## §9 日常运行纪律（逐字执行）

- **TDD 不可跳**：任何生产代码前先写失败测试、看它以正确理由失败、再写最小实现。违反字面即违反精神。
- **测试 local-only**：`agent/tests/` gitignored，`git add` **只加**框架源文件（`git status --short` 里 `??` 的 handoff/测试/工具**别 commit**）。
- **push**：`git push vaibackup HEAD:feat/pipeline-opt-6`（默认 key，repo 已配 core.sshCommand）。**用户自己 merge PR**。
- **归档 run**：`docker compose -p <proj> down -v` 后再 `mv generated/<name> generated/<name>.<SUCCESS-runNN-…|runNN-死因>`。
- **两 run 不并发**；启动新 run 前停旧 `-p gmaps` demo（`run_googlemaps_designinput.sh` 已含防双跑）。
- **磁盘**：`/data` 有余量但归档前务必 `down -v` 释放容器/卷。

## §10 当前状态快照（交接时刻）

- 分支 `feat/pipeline-opt-6` HEAD `083e011`，已 push vaibackup。工作树干净（源文件已 commit；未追踪的 handoff/工具/测试按纪律不 commit）。
- **无活跃 run**（本 AFK session 无 key）。**gmaps demo 容器 `-p gmaps` 可能仍在**（`gmaps-frontend-1` localhost:8080 / `gmaps-backend-1` :3001 / `gmaps-database-1` :5433）——若不用，`docker compose -p gmaps down -v` 停掉。
- 已修：#148、F1/F2/F2b/F3、#151/#151b、#152、#153。待修：§6 的 6-1~6-5。
