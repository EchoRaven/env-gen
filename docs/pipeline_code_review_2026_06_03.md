<!-- 评审报告 · 只读评审,未改动任何代码 · 生成于 2026-06-03 · 方法:10 个子系统并行核查 + 对每条死代码/重复声明做对抗式复核 -->

# env-gen 生成流水线代码评审与整理报告

## 一句话结论

`agent/env_generator/llm_generator` 生成流水线**结构健康、无系统性重复**,但背负三类可清理的负担:一批已验证的死代码(`team_protocols`/`personas`/`mcp_generator`/`specs` 等)、一个**半途而废的 hub facade 迁移**(`apihub`/`eventhub` 仍是顶层胖文件)、以及若干 **>1000 LOC 的巨型文件**(`live_monitor_server.py` 5722 行居首);此外仓库层面 95.4% 的被跟踪文件是 `demos/` 下的 `node_modules` 输出物,应停止跟踪。

**Scope note:** 本次评审主体 = `agent/env_generator/llm_generator` 生成流水线(10 个子系统的对抗式核查);仓库外围目录(`demos/`、`.worktrees/`、`openenv/`、`data_gen/` 等)仅做轻量覆盖。`.worktrees/`、`generated/`、`tmp-sim/`、`demos/`、`__pycache__/`、`node_modules/` 不计入生产使用判定;`tests/` 下可达的代码标记为 **test-only**,不算生产存活。

---

## 1. 执行摘要(最大的几个结构性问题)

**(A) Hub facade 迁移半途而废。** Hub 层本身是干净的——职责拆分是真正的「移动逻辑」而非复制(`apihub.py` 里 `register_table`/`register_mcp`/`list_tables` 已确认彻底移走,无双写)。问题在于迁移只做了一半:`WorkHub`/`CodeHub`/`RunHub` 已是统一的 `hubs/<hub>/{service,stores}.py` 包结构,但 `apihub.py`(926 行)和 `eventhub.py`(1024 行)仍是顶层胖文件,而 `StoryHub` 逻辑在顶层、`stores` 在 `hubs/` 下。结果 `HubRegistry` 用了**至少 4–5 种 import 风格**指向同一个概念(`hub_registry.py:53-57`),其中 `workhub.py`/`codehub.py` 两个 5 行 shim 纯粹是多余的中转层——核查确认仅 `hub_registry` 与未被任何生产模块引用的 `hubs/__init__.py` front 引用它们,删除安全。

**(B) `team_runtime` 是一座「活体但带厚死壳」的遗留岛。** 整个 Claude Code Agent Teams 子系统确实活着,但只通过 LLM 工具面活,不在 orchestrator 自身控制流里。Orchestrator 构造 5 个协议对象却几乎不读它们,纯属持有者。而在这层活路径旁,并存一批 dead-on-arrival 的类:`team_protocols.py`(re-export shim,零引用)、`StandardParallelExecutionSupport`(348 行,被 `profiled.py` 取代,`parallel_execute` 永不被调用)、整个 `PersonaCatalog`/`personas.py`(注入但从不读,且注入因无任何工具声明 `_persona_catalog` 槽位而**根本不触发**)、`TeamPracticeStore` 8 个公开方法中 6 个死。这些死壳虚增了 MRO 和公共面,让整棵树看起来比实际更大、更承重。该子系统冻结于 2026-05-27,而核心 orchestrator(06-03)、`runtime/hubs`(06-01)已前进。

**(C) 巨型文件普遍偏大,职责混杂。** `live_monitor_server.py`(5722 行,全仓最大)是一个塞了 ~8 个内聚但互不相关关注点的单文件,带手写的 if-elif/regex 路由表;`orchestrator.py`(2269 行)把 kickoff 主持、交付门、运行预算 IO 三块本可独立的子系统糅在一起;`reasoning_tools.py`(2577 行)中 81% 是单个 `PlanTool` 类;`hub_tools.py`(1806 行)塞了 74 个跨 4 个 hub 域的工具类;`messaging.py`(1629 行)、`workflow_policies.py`(1645 行)、`base.py`(1447 行)各含一块清晰可切的关注点。这些都是**可拆分而非死代码**,纯维护性收益。

**(D) 文档已追踪的「设计期规格」死代码。** 架构文档 `pipeline_post_kickoff_architecture.md` 的 Stage 1 实际**已经完成并提交**(commit `08872912`,今天 2026-06-03):`ImplementationBootstrapPolicy` 已删、属性改名为 `_kickoff_bootstrapped`、`kickoff_bootstrap_gate` 已接线、旧 yaml kind 现在会响亮报错。文档需更新为「已完成」。Stage 5 目标 `apihub.sync_from_design_spec` 已确认真死(零引用),可删;但 orchestrator 的 `design/spec.*.json` 门读取是**活的交付门代码**(由 frontend/backend 写入喂给),**不可现在删**。

**(E) 仓库膨胀。** 91,883 个被跟踪文件中,87,627 个(95.4%)是 `demos/` 下提交的 `node_modules`——是流水线**输出物**而非源码,占用 1.3G 工作集。`git rm -r --cached` 即可移除约 95% 的被跟踪文件(`.gitignore:132` 已有 `**/node_modules/` 规则,因已跟踪而失效)。

---

## 2. 优先级总表

按价值排序:已验证死代码 + 便宜的快赢在前,大重构在后。已被核查驳回的项已剔除/降级,存疑项标 **待确认**。

| 发现 | 类别 | 位置 | 工作量 | 风险 | 验证结论 | 建议 |
|------|------|------|--------|------|----------|------|
| `demos/**/node_modules` 提交了 87,627 文件(全仓 95.4%) | 死代码(输出物) | `demos/` | 快 | 低 | 已确认 | `git rm -r --cached demos/**/node_modules/`,既有 .gitignore 规则随即生效 |
| `import re` 未使用 | 死代码 | `orchestrator.py:15` | 快 | 低 | 已确认 | 直接删 |
| `_normalize_api_path` 委托方法零调用 | 死代码 | `orchestrator.py:1987-1988` | 快 | 低 | 已确认 | 删委托;保留底层 `normalize_api_path` |
| `_recent_tool_calls`(被 `_load_recent_tool_calls` 取代) | 死代码 | `live_monitor_server.py:1403-1414` | 快 | 低 | 已确认 | 直接删 |
| `_tail_lines`(被 `_read_lines` 取代) | 死代码 | `live_monitor_server.py:839-846` | 快 | 低 | 已确认 | 直接删 |
| `ServerRegistry` / `BackgroundProcessRegistry` 遗留脚手架 | 死代码 | `runtime_tools.py:2180-2212`(+孤儿注释 2237) | 快 | 低 | 已确认 | 删;保留 `__all__` 闭合 `]`(2238) |
| `code_tools.py` 向后兼容 re-export 块 | 死代码 | `code_tools.py:31-44`(+ `__all__` 640-653, 注释 657-660) | 快 | 低 | 已确认 | 删整块及对应 `__all__` 项;保留 `GrepTool`/`LintTool` |
| `team_protocols.py` re-export shim 零引用 | 死代码 | `team_protocols.py`(整文件) | 快 | 低 | 已确认 | 删整文件;顺手更新两处 README:13 目录树 |
| `mcp_generator.py`(605 行,4 个类全无消费者) | 死代码 | `multi_agent/mcp_generator.py` | 快 | 低 | 已确认 | 直接删 |
| `apihub.sync_from_design_spec` 零调用 | 死代码 | `runtime/apihub.py:837-849` | 快 | 低 | 已确认 | 删(Stage 5,文档已预决「Delete」) |
| `_distribute_design_docs` + `set_design_docs` + `_design_docs`(只写不读) | 死代码 | `orchestrator.py:883-897`;`base.py:1278-1280`,`:321` | 快 | 低 | 已确认 | 删整条 push 路径;清理 `workspace_manager.py:20` 过时 docstring |
| `projection_errors` 恒为 `{}`,3 条下游分支恒不可达(Cutover 4 残留) | 死代码 | `orchestrator.py:1567,1581-1582,1791,2094-2098,2219-2222` | 快 | 低 | 已确认 | 删局部变量、分支、报告块、建议块、gate dict 键 |
| `StandardParallelExecutionSupport`(348 行,被 profiled 取代) | 死代码 | `parallel_runtime/standard.py`;`parallel.py:12-18`;`parallel_runtime/__init__.py:6,13` | 快 | 低 | 已确认 | 从 MRO 移除 + 删文件;**保留** profiled 共享的 helper 模块 |
| `PersonaCatalog`/`personas.py`(190 行)构造+注入但从不读;注入根本不触发 | 死代码 | `team_runtime/personas.py`;`orchestrator.py:35,193` + 整条 plumbing | 中 | 低 | 已确认 | 删模块+plumbing;清理 `llm.py:469-470`、`tools.py:322` 虚假广告 |
| `_paths.py` 路径引导模块被绕过 | 死代码 | `_paths.py` | 快 | 低 | 已确认(仅 `_paths`) | 删 `_paths.py`;**注意**:同发现里的 `agents/__init__` shim 被核查**驳回**(见下) |
| `runtime_tools` 两死 registry(上面已列)+ kickoff `__init__` re-export 面 | 死代码 | `runtime/kickoff/__init__.py:18-72`(21 个名,非 24) | 快 | 低 | 已确认 | 收缩为 docstring-only 包标记;删 re-export 块 + `__all__` |
| `ready_set.py`(184 行)+ `arbitrate()` test-only,逻辑与 `roadmap_validator` 重复 | 死代码 | `kickoff/ready_set.py:80`;`arbitration_table.py:173` | 快 | 中 | 已确认(test-only) | 确认无近期接线计划后删模块+回归测试;**保留** `resolve_conflict`/`ARBITRATION_TABLE` |
| `contract.py` `endpoint_id()` / `validate_kickoff_endpoint()` test-only | 死代码 | `kickoff/contract.py:119,221` | 快 | 中 | 已确认(test-only) | 决定保留为不变量 pin 或删;**必修**:修正 `:184/:200` 误导 docstring |
| `knowledge/seed_data.py` + `cli.py` 死手动工具(70/71 行由 agent 写) | 死代码 | `knowledge/seed_data.py`,`cli.py` | 快 | 低 | 已确认 | 删两文件(~48K);必须同删 `__init__.py:53,84-85` 的 re-export |
| `knowledge/__init__.py` front + `knowledge/tools.py` shim 零引用 | 死代码 | `knowledge/__init__.py`,`knowledge/tools.py` | 快 | 低 | 已确认 | 删 shim,`__init__` 收缩为只导 `store`+`types`;同删 `cli.py` |
| `data_engine_tools` bundle 注册但零 profile 授权 | 死代码(授权) | `data_engine_tools.py`;`tool_bundles.py:144,619,674` | 中 | 中 | 已确认(grant 死;模块 test-live) | **优先重新授权给 backend**(计划文档显示原意如此);若删须同删 3 个测试 |
| 9/14 communication tools 死(`include_advanced` 永为 False) | 死代码 | `communication_tools.py:~916-1908`;`tools.py:249` | 中 | 中 | 已确认 | 折叠为 5 核心工具,删 `include_advanced` 分支;或改 opt-in bundle |
| 旧 `get_all_tools`/`get_vision_tools`/`get_tool_params` + `all` 装配模式 | 死代码 | `tools/__init__.py:344,469,474`;`multi_agent/tools.py:156,262,282` | 中 | 低 | 已确认 | 删两条 legacy「register everything」路径;同删 `get_agent_tools` + 孤儿 imports |
| `TeamPracticeStore` 6/8 方法死(仅 `record_practice` 活) | 死代码 | `team_runtime/practices.py` | 中 | 低 | 已确认 | 裁剪死方法;清理 `llm.py:471-473`、`tools.py:323-324` 虚假广告 |
| `specs/project_structure.py` + `specs/__init__.py` 功能性惰性 | 死代码/观察 | `specs/project_structure.py`;`__init__.py`;`llm_generator/__init__.py:32` | 中 | 低 | **存疑**(核查驳回「never imported」,实为 import-live 但惰性) | **待确认**:重分类为 LEGACY/STALE;删时须同删 3 处 re-export,并 smoke 一个 `run_*.sh` |
| `apihub.py`/`eventhub.py` 未迁入 `hubs/` 包约定 | 拆分 | `apihub.py`,`eventhub.py` | 大 | 中 | — | 迁入 `hubs/<hub>/{service,stores}.py`,顶层转 5 行 shim |
| `HubRegistry` 3+ 种 import 风格 + `workhub`/`codehub` 死中转 shim | 合并 | `hub_registry.py:53-57`;`workhub.py`,`codehub.py` | 快 | 低 | 已确认(实际 4-5 种,比声称更乱) | 删两 shim,改 `from .hubs.<hub> import` |
| `StoryHub` service 在顶层、stores 在 `hubs/`(与 RunHub 不对称) | 拆分 | `story_hub.py:409`;`hubs/story_hub/stores.py` | 中 | 中 | — | 把 service 移入 `hubs/story_hub/service.py` |
| 交付门 ~700 LOC 提取为 `DeliveryGate` | 拆分 | `orchestrator.py:1497-2259` | 大 | 中 | — | 提取到 `runtime/delivery_gate.py` |
| kickoff 主持 ~538 LOC 提取为 `KickoffChair` | 拆分 | `orchestrator.py:899-1436` | 大 | 中 | — | 提取到 `runtime/kickoff/chair.py`(中等置信) |
| `live_monitor_server.py`(5722 行)按关注点拆包 | 拆分 | `live_monitor_server.py` | 大 | 中 | — | 拆为 `live_monitor/` 包,顶层留 shim |
| 手写路由表 ordering footgun | 拆分 | `live_monitor_server.py:5025,5277,5562` | 中 | 中 | — | 改声明式 `(method, regex, handler)` 表 + 集中 workspaces_root guard |
| `reasoning_tools.py` `PlanTool`(2087 行)拆分 | 拆分 | `reasoning_tools.py:259-2346` | 大 | 中 | — | 拆 `plan/{acceptance,sync,crud,party}.py` |
| `hub_tools.py`(74 类)按 hub 拆分 | 拆分 | `hub_tools.py:79-1801` | 大 | 低 | — | 拆 `tools/hub/` 子包 |
| `messaging.py` 5 个 kickoff handler(~938 LOC)提取 | 拆分 | `messaging.py:658-1629` | 中 | 中 | — | 提取 `AgentKickoffHandlers` mixin |
| `workflow_policies.py` 4 个胖 policy 拆 `policies/` 包 | 拆分 | `workflow_policies.py` | 大 | 中 | — | 拆包 + 顶层保留 re-export shim(中等置信) |
| `base.py` chat mini-loop(~460 LOC)提取 | 拆分 | `base.py:582-1041` | 中 | 低 | — | 提取 `AgentChat` mixin(中等置信) |
| `runtime_tools.py` infra vs wrapper 拆分 | 拆分 | `runtime_tools.py` | 中 | 低 | — | 提取 `tools/runtime/process_manager.py` |
| `run_kickoff.py`(1307 行)三分 | 拆分 | `run_kickoff.py` | 中 | 中 | — | 拆 `synthesize/finalize/abort.py`(中等置信) |
| `schema_tolerance.py`(846 行)按 4 import 簇拆 | 拆分 | `schema_tolerance.py` | 中 | 低 | — | 拆 `shape_extractors/coverage_synthesis/facilitator_intent.py`(中等置信) |
| live_monitor 与 observability 重复解析 `.agent_logs` jsonl | 合并 | `live_monitor_server.py:206,372`;`observability/log_parser.py:17` | 中 | 低 | 已确认(重叠真,范围窄) | 抽 `agent_log_format.py` 共享低层提取;低紧迫 |
| 自动补桩缺失 verifier 谓词(`augment_drafts_for_coverage`)与 no-fallback 章程冲突 | 观察 | `schema_tolerance.py:457,511`;`run_kickoff.py:368,597` | 中 | 中 | — | 提交 charter owner 决策;`synthesize_fallback` 改名为 `abort_kickoff_on_timeout` |
| `_SSEHub.client_count` 仅测试读 | 死代码 | `live_monitor_server.py:1999-2002` | 快 | 低 | **存疑/partial**(test-only,非零引用) | **待确认**:删须同改 `test_live_monitor_sse.py:77,93` 两断言;或保留作断言面 |
| legacy `--project-dir` / `build_state` 路径(~700 LOC) | 观察 | `live_monitor_server.py:1417,5242` | 中 | 中 | — | **待确认**:先确认无 launcher 传 `--project-dir`(demo runbook 在 :4500),再走显式弃用决策 |
| `torchforge/` | ~~死代码~~ | `torchforge/` | — | — | **已驳回** | 实为被 `openenv/` GRPO 示例引用的 git submodule(gitlink b628308),**勿删** |

---

## 3. 死代码(已验证)

仅列 confirmed / partial 项;每项含证据、是否可安全删除、对应文档 Stage。

### 3.1 一删即净的孤儿(confirmed / 真无引用)

- **`orchestrator.py:15` `import re`** — 全文件 2269 行无任何 `re.` 用法,无 re-export。**安全删。**
- **`orchestrator.py:1987-1988` `_normalize_api_path`** — 7 个 `_contract` 委托中唯一零调用者;由 commit `2f865500`(交付门提取)遗弃。底层 `delivery/contract_extract.py:normalize_api_path` 仍活,**勿动**。**安全删委托。**
- **`orchestrator.py:1567/1581-1582/1791/2094-2098/2219-2222` `projection_errors`** — `projection_errors = {}`(Cutover 4 移除 CRDT),恒不重赋值 → `semantic_projection_errors` 失败检查永不追加,报告块/建议块静态不可达。**安全删五处,无行为变化。**
- **`live_monitor_server.py:1403-1414` `_recent_tool_calls`** — 被 `build_state` 的 `_agent_tool_logs` 路径取代;活变体是 `_load_recent_tool_calls`(def 372)。**安全删。**
- **`live_monitor_server.py:839-846` `_tail_lines`** — 与活的 `_read_lines`(:849,调用于 :1422)近乎相同;tail 行为已由 `all_log_lines[-180:]`(:1423)内联。**安全删。**
- **`runtime_tools.py:2180-2212` `ServerRegistry` + `BackgroundProcessRegistry`** — 自述「Legacy compatibility - use ProcessManager instead」,不在 `__all__`,零外部引用。删时**保留** :2238 的 `]` 与活的 `__all__`;顺手删孤儿注释 :2237。

### 3.2 死壳与 shim(confirmed)

- **`code_tools.py:31-44` 向后兼容 re-export 块** — 重导 `PlanTool`/`FinishTool`/comm tools,所有真实消费者都从规范模块导入。删时**同删** `__all__` 640-653 与注释 657-660,否则 `import *` 报错。保留 `GrepTool`/`LintTool`。
- **`team_protocols.py`(整文件)** — 36 行纯 re-export shim;`orchestrator.py:30-37` 直接从 `.team_runtime` 导入,绕过它。由 commit `6bad8ca0` 拆分时遗弃。**安全删整文件**;顺手更新 `agent/env_generator/README.md:13`、`llm_generator/README.md:13` 的过时目录树。
- **`mcp_generator.py`(605 行)** — `MCPGenerator`/`MCPService`/`MCPTool`/`MCPParameter` 零生产/测试/动态引用;活 MCP 路径是 `tools/mcp_tools.py` + `tools/mcp_registry_tools.py`,与此模块不相交。**安全删整文件。**
- **`_paths.py`** — `main.py:83-92` 自己内联 `sys.path.insert`,无 `import _paths`;经验证不在 `sys.modules`。**安全删。**(注:同发现里的 `agents/__init__` shim 被驳回——见 §8。)
- **`knowledge/seed_data.py` + `cli.py`** — 运行时铁证:`~/.env-gen/knowledge/knowledge.db`(610K,今天 mtime)71 行中 70 agent + 1 manual,seed_data 的 38 条**一条都没加载过**;`cli.py` 无任何 `-m`/脚本调用。删时**必须同删** `__init__.py:53,84-85` 的 re-export,否则 import 报错(~48K)。
- **`knowledge/__init__.py` front + `knowledge/tools.py` shim** — 包 front 零真实 importer(唯一匹配是自身 docstring 示例 `:14`);活消费者直接导 `.store`/`.types`。`knowledge/tools.py` 唯一 importer 是死的 `__init__.py:37`。**安全删 shim,`__init__` 收缩为只导 store+types。** 同 sweep 删 `cli.py`,留 `knowledge/` = `store.py` + `types.py`。

### 3.3 test-only(生产死,删需连带改测试)

- **`kickoff/ready_set.py:80` `ready_set` + `arbitration_table.py:173` `arbitrate()`** — 零生产调用;活路径用 `resolve_conflict`(run_kickoff.py:610)做仲裁、`roadmap_validator` 自己的 `_dfs` 做环检测(注释明言「mirrors ready_set._dfs ... 但 COLLECTS cycles」)。删须同删 `__init__.py` re-export 行 + `__all__` 项 + 两个回归测试;**勿动** `resolve_conflict`/`ARBITRATION_TABLE`/`tiebreak_by_alphabetical_agent_id`(活)。建议先与维护者确认无近期接线计划(charter delete-don't-skip)。
- **`kickoff/contract.py:119 endpoint_id` / `:221 validate_kickoff_endpoint`** — 仅 `normalize_to_apihub_endpoint` 生产活(run_kickoff.py:977,且不调用 `endpoint_id`)。删须连带改 `test_kickoff_contract.py`、`test_kickoff_cross_check_suite.py`(后者 :242 用 `endpoint_id` 构 fixture)。**无论删否,必修** `:184/:200` 误导 docstring(指示「Call validate_kickoff_endpoint() before normalizing」,无生产者照做)。
- **`team_runtime/personas.py`(190 行)** — 构造+注入但 9 个公开方法全零调用;**注入本身根本不触发**(无任何工具声明 `_persona_catalog` 槽位,`collection.py:67` 的 `hasattr` guard 恒 False)。删模块 + plumbing;清理虚假广告 `tools.py:322`、`docs/*`、`llm.py:469-470`。
- **`team_runtime/practices.py` 6/8 方法** — 仅 `record_practice` 活(经 `ParallelReasoningProtocol.run_parallel_reasoning`,reasoning.py:147);`get_statistics` 比声称更死(其 `standard.py:346` 调用点的 `file_coordinator` 恒为 None)。裁剪死方法,清理 `llm.py:471-473`、`tools.py:323-324` 虚假广告。
- **`parallel_runtime/standard.py`(348 行)`StandardParallelExecutionSupport`** — `parallel_execute` 零调用;LLM 工具 `parallel_execute` 实际路由到 `parallel_execute_profiled`。从 `parallel.py:12-18` MRO 移除 + 删文件。**注意**:`standard.py` 用到的多个 helper(`_validate_subtask_contract` 等)与 `profiled.py` 共享,**仅删 standard.py 本身**,勿删 metrics/contracts/coordination。
- **`data_engine_tools` bundle** — 注册于 registry 但零 profile 授权(`agents_config.yaml` 零 `data_engine` 命中);模块被测试覆盖(production-unreachable, test-live)。计划文档 `docs/plan_kickoff_refactor.md:192` 显示原意是授权给 backend——**重新授权给 backend profile 比删除更可能正确**。若删须同删 3 个测试 + `tools/__init__.py` 块;**勿删** repo-root `data_engine/` 包(独立活的 HuggingFace seeding CLI)。
- **`communication_tools.py` 9/14 工具(~916-1908,~990 LOC)** — `include_advanced` 在活路径(`tools.py:249`)永为 False,唯一 True 调用者是死的 `tools/__init__.py:get_all_tools`。折叠为 5 核心工具并删 `include_advanced` 分支,或改 opt-in bundle。
- **`tools/__init__.py:344/469/474` + `multi_agent/tools.py:156/262/282` legacy 装配** — `get_all_tools`/`get_vision_tools`/`get_tool_params` + `get_agent_tools` + `_assemble_full_tool_pool` + `assembly_mode=='all'` 全死;活路径只用 `assembly_mode='agent'`。删时连带清理 `multi_agent/tools.py:52-69` 的 `_assemble_full_tool_pool` 专用 imports。

### 3.4 文档 Stage 5 死代码

- **`apihub.sync_from_design_spec`(apihub.py:837-849)** — 全仓仅 3 处命中(def + 2 处文档),零生产/测试/yaml/动态引用;不在静态 hub tool 面,非 LLM-callable;默认参 `agent="design"` 指向已退役的 design agent。文档 Q B 已预决「Delete」。**安全删**,顺带裁剪 1024 行 legacy 顶层 `apihub.py` 表面。

### 3.5 仓库层面

- **`demos/**/node_modules`(87,627 文件,95.4%)** — 流水线输出物(`run_github_clone_generation.sh:7` 的 `OUTPUT_BASE`),无生产 import。`git rm -r --cached demos/**/node_modules/`;`.gitignore:132` 已有 `**/node_modules/` 规则(因已跟踪而失效),`rm --cached` 后即生效,**无需新增 gitignore 行**。若整体 ignore `demos/`,须保留/迁移 2826 个非 node_modules 文件(设计规格/README/seed SQL)。
- **`data_gen/`、`tmp-sim/`、`test/analyze_training_logs.py`** — 独立实验/烟测残留,流水线零引用(见 §7)。

---

## 4. 重复 / facade 迁移未完成(hub 层)

**核心判定:无逻辑重复——职责拆分是干净的「移动」。** `hub_registry.py:117-123` 按引用把 `apihub` 的 `JsonStore` 句柄传入 `SchemaHub`,`apihub._mcp_registry` 传入 `MCPRegistry`,`GateRegistry` 共享 `workhub.stores.pages`;`apihub.py` 已无 `register_table`/`register_mcp`/`list_tables` 方法面(grep 返回 NONE)。这是正确的提取,**记录为目标终态模式**。

**真正的问题是 facade 迁移只做了一半,产生 4–5 种并存约定**(核查发现比原声称的「3 种」更乱):

| Hub | 当前形态 | 目标形态 |
|-----|---------|---------|
| `WorkHub` / `CodeHub` | `hubs/<hub>/{service,stores}.py` + **顶层 5 行 shim** | 删 shim,直接 `from .hubs.<hub> import` |
| `RunHub` | `hubs/runhub/{service,stores}.py`(无 shim,直接导) | ✅ 已是目标态(参照样板) |
| `APIHub` | **顶层胖文件 926 行**,16 个 `JsonStore` 内联 | `hubs/apihub/{service.py(~840),stores.py(~90)}` + 顶层转 shim |
| `EventHub` | **顶层胖类 1024 行** + `hubs/eventhub/bridge.py`(仅 bridge 拆出) | `hubs/eventhub/{service.py(~880),stores.py(~80)}`,保留 bridge |
| `StoryHub` | **顶层胖模块 463 行**(逻辑)+ `hubs/story_hub/stores.py`(仅 stores 拆出) | service 移入 `hubs/story_hub/service.py`,`__init__` 同时导 `StoryHub`+`StoryHubStores` |

**建议的一致布局:** 把全部 5 个 hub 收敛到 `runtime/hubs/<hub>/{service,stores}.py` + `__init__.py` re-export,`runtime/<hub>.py` 一律为 5 行 shim(或直接删 shim,`hub_registry` 用 `.hubs.<hub>` 形式)。迁移 `apihub`/`eventhub` 时,**务必原样保留** `hub_registry.py:112-123` 的按引用 store 共享,以保 snapshot 文件路径(`apihub_*.json`)稳定。

**便宜的快赢(可独立于大迁移先做):**
1. 删 `runtime/workhub.py`、`runtime/codehub.py` 两个 shim,改 `hub_registry.py:54,57` 为 `from .hubs.codehub/.workhub import ...`(对齐 runhub :56)。核查确认唯一 module-level importer 是 `hub_registry` + 未被任何生产模块引用的 `hubs/__init__.py:9,10`;`coverage_audit.py:416`/`facilitate.py:663` 走的是 registry **属性**而非 module,删除安全。
2. 修正 `hubs/__init__.py:1` 过时 docstring(声称只含 CodeHub/WorkHub,且引用不存在的 `hub_workspace.py`;实际还含 runhub/story_hub/eventhub,实例化在 `hub_registry.py:53-91`)。

---

## 5. 可拆分的大文件

### >1000 LOC 文件清单(评审覆盖到的)

| 文件 | LOC | 主要可切关注点 |
|------|-----|---------------|
| `live_monitor_server.py` | 5722 | ~8 个内聚簇 + 950 行手写路由 |
| `reasoning_tools.py` | 2577 | 81% 是单个 `PlanTool` 类(2087 行) |
| `orchestrator.py` | 2269 | kickoff 主持 / 交付门 / 运行预算 IO |
| `runtime_tools.py` | 2238 | ProcessManager infra vs BaseTool wrapper |
| `hub_tools.py` | 1806 | 74 个工具类跨 4 个 hub 域 |
| `workflow_policies.py` | 1645 | 4 个胖 policy 占 >75% |
| `messaging.py` | 1629 | core inbox vs 5 个 kickoff handler(~938 LOC) |
| `base.py` | 1447 | lifecycle vs chat mini-loop(~460 LOC) |
| `run_kickoff.py` | 1307 | synthesis / finalize(390 行) / 超时熔断 |
| `eventhub.py` | 1024 | (见 §4 hub 迁移) |
| `schema_tolerance.py` | 846 | 4 个 drift-recovery 关注点 |

### Top 文件分解建议

**`live_monitor_server.py` → `live_monitor/` 包(高置信):** 按注释横幅与 `*_call` 命名拆为 `state.py`(~1400)、`projects.py`(~450)、`sse.py`(~400)、`runs.py`(~500)、`hub_calls/{workhub,codehub,apihub,eventhub_runhub}.py`(~750)、`code_browser.py`(~350)、`gates_references.py`(~320)、`knowledge_skills.py`(~230)、`auth.py`(~120)、`handler.py`(~950)、`server.py`(~110)。40 个 `*_call` 委托都经 `_resolve_hubs`,移动干净。顶层 `live_monitor_server.py` 留 shim 导 main 保入口。**同时**把手写路由表改成声明式 `(method, compiled-regex, handler_fn)` 元组列表,消除多处「MUST be matched before」ordering footgun,把 ~25 份重复的 `workspaces_root` None-guard 集中成一个 decorator。

**`orchestrator.py`(高/中置信):**
- 交付门 `_validate_delivery_gate` + 子验证器 + `_extract_*` + 报告/建议(~700 LOC,~31%)→ `runtime/delivery_gate.py` 的 `class DeliveryGate(output_dir, hubs, logger)`;状态依赖扫描确认只触 `self.output_dir`/`self.hubs`/`self._logger`,seam 干净。orchestrator 净降 ~760 LOC。**(高置信)**
- kickoff 主持 `_drive_kickoff_to_completion` + 卫星(~538 LOC)→ `runtime/kickoff/chair.py`,与已有 `runtime/kickoff/` 协作者同居。**(中置信——silent-lane nudge 耦合了 `self._agents`/`self.message_bus`,可留在 orchestrator。)**
- 端口/preflight + 运行预算 IO → `runtime/preflight.py` + `runtime/run_budget.py`(~140 LOC,机械低风险)。**(中置信)**

**`reasoning_tools.py` `PlanTool`(高置信):** 拆 `plan/{acceptance(~550),sync(~150),crud(~500),party(~350)}.py`,`PlanTool` 经 mixin/委托组合。**务必保留** `PlanTool.get_instance` 单例契约(tool_bundles.py:588 依赖)。

**`hub_tools.py`(高置信、低风险):** 拆 `tools/hub/{workhub_tools,codehub_tools,apihub_tools,eventhub_tools}.py` + `base.py`(HubTool + FocusHubTool + `create_hub_tools` 工厂);各 hub 工具已在注册层经 `include_names` 分到独立 bundle,文件是唯一耦合物。从 `hub_tools.py` 或 `hub/__init__.py` re-export `create_hub_tools`/`FocusHubTool` 保 import 不变。

**`messaging.py`(高置信):** 提取 5 个 `_handle_kickoff_*` + `_ensure_*`(~938 LOC)为 `agents/runtime/kickoff_handlers.py` 的 `AgentKickoffHandlers` mixin,加到 `base.py:106` 基类列表;dispatch 表留在 `messaging.py`(经 MRO 解析)。`messaging.py` 降到 ~690 行。

**其余(中置信):** `workflow_policies.py` → `policies/` 包 + 顶层 re-export shim;`base.py` chat 块 → `AgentChat` mixin;`run_kickoff.py` → `synthesize/finalize/abort.py` + 顶层 facade;`schema_tolerance.py` 沿自身 4 个 import 簇拆 + re-export facade;`runtime_tools.py` 提取 `tools/runtime/process_manager.py`。

---

## 6. team_runtime / 遗留子系统

**定性:活体但带厚死壳。** 该子系统**只经 LLM 工具面活**,不在 orchestrator 控制流。Orchestrator 构造 5 个协议对象纯属持有者(`agent_spawn_service.py:269` 经 `self._orchestrator.<attr>` 取用并注入工具);自身 spawn 用 `self.spawn_service.spawn` 而非 `agent_manager.spawn_worker`。`parallel_runtime` **不是死岛**——`profiled/metrics/contracts/coordination` + `lifecycle/runtime_control/registry/reasoning/plan_decision` 经 `parallel_execute_profiled` 与 managed-team 工具活着,且 `runtime_control` 委托回规范的 `orchestrator.spawn_service.spawn`。

**删除/隔离建议:不要整树隔离,精确裁死壳:**

| 死项 | 处置 |
|------|------|
| `team_protocols.py` | 删整文件(零引用) |
| `parallel_runtime/standard.py`(348 行) | 从 MRO 移除 + 删;保留共享 helper |
| `personas.py`(190 行)+ 全 plumbing | 删(注入根本不触发) |
| `TeamPracticeStore` 6/8 方法 | 裁剪,留 `record_practice` + 持久化 |

裁完后剩 ~14 个模块是一个连贯、活的 tool-capability 层。整树冻结于 2026-05-27(核心已到 06-03)是**陈旧信号而非死亡证明**——删前再确认 `agent/tests/` 无覆盖被裁符号。`synthesize_fallback`(run_kickoff.py:1206)**不是** fallback,是响亮的 `kickoff_failed` 熔断器,名字误导,建议改名 `abort_kickoff_on_timeout`。

---

## 7. 仓库层面可分离项

- **`demos/`** — 见 §3.5,流水线输出物,`git rm -r --cached` 移除 95% 被跟踪文件。
- **`.worktrees/`** — gitignored 草稿,持 44 个活 worktree,**非提交膨胀**,out-of-scope;清理用 `git worktree prune/remove`(操作性,非代码问题)。
- **`data_gen/`(34M,2025-12-21)** — 流水线零 import,与活的 `data_engine/` 不同(后者经 `tool_bundles.py:16`/`data_engine_tools.py:143` 活)。内含独立 playground 资产 + 自带 `test_data_sources.py`(命名 test_* 但不在 tests/ 下、不被 pytest 收集)。**归档或移出仓库**,保留则加 README 注明是独立实验。
- **`openenv/`(399 文件,3.7M,2025-12-29)** — 扁平化的 vendored 外部项目(Meta OpenEnv,自带 pyproject/LICENSE/rfcs),流水线零 import。**重分类为 vendored/out-of-scope**;若需依赖,优选 pinned package 或 submodule 而非内嵌副本。
- **`tmp-sim/`(16 文件)+ `test/analyze_training_logs.py`** — 手动烟测残留 + 无关训练日志分析器(env-gen 测试套在 `agent/tests/`)。**un-track 删除**,`tmp-sim/` 加入 .gitignore。
- **保留(活依赖,勿误删):** `data_engine/`(tool 面运行时依赖)、`reference_images/`(`main.py:249-258` 直读,run_*.sh 引用)。

---

## 8. 架构观察(知道即可,非立即行动)

- **责任拆分是干净委托而非重复**(positive)——记录为目标终态模式;hub 层无死模块,9 个 hub/registry 全部 wired。
- **`AutoCommitOnFinishPolicy` 是薄委托**到 `runtime/auto_commit.py`,**非重复 git 逻辑**(policy = when,runtime = how)。
- **10 个 workflow policy 类全活**,零死 policy 类;新增 policy 须同时注册类 + `create_workflow_policies` 的 elif,否则静默死。
- **Stage 1 已完成**(commit `08872912`):`ImplementationBootstrapPolicy` 类/`_required_files_ready`/`_has_implementation_bootstrap_policy` 已删,`_implementation_bootstrapped` 改名 `_kickoff_bootstrapped`(语义保留、hub 喂),`kickoff_bootstrap_gate` 接线于 backend+frontend,旧 yaml kind 响亮报错(closed-by-construction)。
- **MCP 三模块非重复**——`mcp_tools`(server codegen)/`mcp_client_tools`(runtime client)/`mcp_registry_tools`(hub registry)是一个特性的三层,NAME 命名空间不重叠,全活。可选地共置 `tools/mcp/` 子包提升可发现性。
- **两个截屏比较工具**(`compare_screenshots` SSIM vs `compare_with_screenshot` LLM)意图重叠、机制不同,非合并目标;建议澄清 DESCRIPTION,避免同 profile 同时授予。
- **两套 knowledge 系统合法共存**——per-agent `GeneratorMemory._knowledge`(jsonl 临时工作记忆)vs 共享 `KnowledgeStore`(SQLite 跨 run KB,71 行 agent 写入活跃);建议把 `GeneratorMemory._knowledge` 改名 `_working_knowledge` 防误合并。
- **`context_management.py` + `delivery/contract_extract.py` 健康活跃**,非死非拆分候选;记录以防被误扫。
- **observability/ 是独立活子系统**(LLM 工具面,经 `observability_tools` bundle + `agents_config.yaml:122`),与 live_monitor 完全分离,**勿折入** live_monitor 拆包;包 `__init__` 零 inbound 是良性(消费者直接导 `.dashboard`/`.log_parser`)。

**核查驳回的「发现」(已从总表剔除/降级):**
- **`torchforge/` 不是空死目录**——是被 `openenv/` GRPO 示例引用并 pin 的 git submodule(gitlink `b628308`);删除会破坏 openenv 训练设置。唯一缺陷是缺 `.gitmodules` 条目。
- **`agents/__init__` shim + `llm_generator/__init__.py:26` re-export 不是死代码**——经 `env_generator/__init__.py:14` 的相对 import 在 `-m env_generator.llm_generator.main` 启动路径上活着(已在 sys.modules 实证)。原评审 grep 只匹配了 `from llm_generator import`,漏了相对 import。**只有 `_paths.py` 这一半成立。**

---

## 9. 建议的执行顺序

把发现映射到 quick-wins、文档既有 Stage 1/Stage 5,以及本评审新增项,使本报告**插入** `pipeline_post_kickoff_architecture.md` 而非与之竞争。

### 第 1 波:Quick-wins(单行/单块删除,零风险,可立即做)
本评审**新增**,文档未追踪:
- `orchestrator.py` 四删:`import re`、`_normalize_api_path`、`projection_errors` 死分支、`_distribute_design_docs`(+ `base.py` `set_design_docs`/`_design_docs`)
- `live_monitor_server.py` 三删:`_recent_tool_calls`、`_tail_lines`、(`client_count` **待确认**,见 §10)
- `runtime_tools.py` 两死 registry;`code_tools.py` re-export 块
- `team_protocols.py`、`mcp_generator.py`、`_paths.py` 整文件删
- `kickoff/__init__.py` re-export 面收缩
- **仓库:`git rm -r --cached demos/**/node_modules/`**(单笔移除 95% 被跟踪文件,最高 ROI)

### 第 2 波:文档已追踪的 Stage 1 / Stage 5
- **Stage 1(`ImplementationBootstrapPolicy`):已完成**,只需把 `pipeline_post_kickoff_architecture.md:154` 等条目标记为 DONE(commit `08872912`,2026-06-03),并注明属性是**改名**非删除、loud-raise guard(workflow_policies.py:1578)保留。**无代码动作。**
- **Stage 5(design-spec 清理):** 删 `apihub.sync_from_design_spec`(文档 Q B 已预决);**勿删** orchestrator 的 `design/spec.*.json` 交付门读取(活,frontend/backend 喂)与 `flow_coverage`/`deliverability`(活)。

### 第 3 波:本评审新增的中等死代码(需连带改测试/确认)
- `knowledge/{seed_data,cli,tools}.py` + `__init__` 收缩
- `team_runtime` 死壳:`personas.py`、`standard.py`、`TeamPracticeStore` 6 方法
- `data_engine_tools`(**优先重新授权给 backend** 而非删)、9 个 advanced communication tools、legacy `get_all_tools` 路径
- `ready_set`/`arbitrate`、`contract.py` test-only 函数(先与维护者确认)

### 第 4 波:Hub facade 收敛(本评审新增,可作为 Stage 5 的伴生整理)
- 快赢:删 `workhub.py`/`codehub.py` shim + 修 `hubs/__init__.py` docstring
- 大迁移:`apihub`/`eventhub`/`story_hub` 迁入 `hubs/<hub>/{service,stores}.py`,5 个 hub import 风格收敛

### 第 5 波:大文件拆分(本评审新增,纯维护性,与重命名/death-cleanup 解耦)
按 ROI:`hub_tools.py`(低风险)→ `messaging.py` → `DeliveryGate` 提取 → `reasoning_tools.py` PlanTool → `live_monitor/` 包 + 路由表 → 其余中置信拆分。

**文档已追踪 vs 新增对照:**
| | 文档 (`pipeline_post_kickoff_architecture.md`) 已追踪 | 本评审新增 |
|---|---|---|
| Stage 1 | `ImplementationBootstrapPolicy` 退役(**实际已完成**) | — |
| Stage 5 | `sync_from_design_spec` 删、design_dir 读取「remove」标注、`PROJECT_STRUCTURE['design']` 「deprecate」 | hub facade 收敛、`specs/` 重分类(存疑) |
| 其余 | — | 全部 quick-win 死代码、`team_runtime` 死壳、`knowledge`/`tools` 死面、所有大文件拆分、`demos/` un-track |

---

## 10. 附录:存疑 / 待确认项

- **`specs/project_structure.py` + `specs/__init__.py`(存疑——核查驳回部分声称)。** 原评审称「DEAD package, never imported」被**驳回**:它经 `llm_generator/__init__.py:32` 在 `python -m env_generator.llm_generator.main` 启动路径上**确实被 import**(run_facebook/plane/github_clone_generation.sh 都用此形式,已实证 sys.modules)。但内容**功能性惰性**(无生产代码读 `PROJECT_STRUCTURE`/`PHASES` 或调那些函数)。**重分类为 LEGACY/STALE 而非 import-dead。** 删除可行但**必须同删** `llm_generator/__init__.py:32,51-53` 与 `specs/__init__.py` 三处 re-export,否则破坏 `-m` 入口;删后须 smoke 一次 `run_*_generation.sh`。优先级低于 `sync_from_design_spec`。

- **`live_monitor_server.py:1999-2002` `client_count`(partial)。** 生产死(无生产读),但**非零引用**——`test_live_monitor_sse.py:77,93` 两断言读它,cutover-31 plan doc 也提及。原评审证据句「finds no other reference」**事实有误**。删须同改两测试(改断言 `len(hub._clients)`),或**保留**作为 register/unregister 测试的唯一可观测断言面。

- **`live_monitor_server.py:1417,5242` legacy `--project-dir` / `build_state` 路径(中置信,待确认)。** `build_state` + ~700 LOC log-scraping helper 簇被新的 workspaces-root 模式(`build_project_state` + `_hub_snapshots`)取代,注释 :1474 承认「crdt key kept for back-compat」。**勿现在删**——demo runbook 在 :4500 运行 live_monitor,须先确认无 launcher 传 `--project-dir`,再走显式弃用决策(经文档化 CLI flag 可达,非静默死)。

- **`auto_coverage` 软降级(高置信,需 charter 决策而非删除)。** `ensure_critical_flow_coverage`(schema_tolerance.py:457)在活合成路径自动补桩缺失 verifier 谓词(`source:'auto_coverage'`),与 pinned no-fallback 章程冲突。建议提交 charter owner:或发可见 warning/event,或改为 hard `validation_failed`。这是设计冲突观察,不是死代码。

- **低置信拆分项(中等置信):** `KickoffChair` 提取、`workflow_policies.py` policies/ 包拆分、`base.py` `AgentChat` 提取、`run_kickoff.py` 三分、`schema_tolerance.py` 簇拆分、`runtime_tools.py` infra/wrapper 拆分、`port-budget-io` 提取——均为纯维护性,无功能风险,但 seam 不如 `DeliveryGate`/`hub_tools`/`messaging` 那么干净,建议落地前逐个验证 import 面。

- **`jsonl` 解析重复合并(中置信,低紧迫):** live_monitor 与 observability 各自重实现 `.agent_logs` tool_call 解析,无共享代码,但两提取器机制不同(observability regex vs live_monitor `str.split("(")` + endswith guard)。仅低层 `iter_jsonl`/`is_tool_call`/`extract_tool_name` 真正可共享;高层形态(aggregate stats vs live JSON records)合法不同,应分开。注意**不存在** `live_monitor/state.py`(`live_monitor/` 目录是 JS 前端),共享层应被 `live_monitor_server.py` 本体消费。