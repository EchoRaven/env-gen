# HANDOFF 2026-07-19 — 前端零 Fallback(下一个 session 主战场)

> 目标一句话:**彻底消除前端 fallback / 占位页 —— 每个路由页都必须是"参考结构化、已填充真实数据、功能完整"的真页,零 mock / placeholder / fallback。**

---

## 0. 先做:合并 PR

上一个 session 交付了 **12 个 env-agnostic 修复(#207–#218)**,全部 TDD + 已推:
- 分支 `pipeline-opt6-tiktok-delivery-186-205`(= `feat/pipeline-opt-6`,HEAD `a2050dc`),推到 `vaibackup`。
- **先 merge 这个 PR**,再开新 session 做前端。

这 12 个修复让 pipeline 的**基础设施层 + seed 层已稳固**(r18 live 验证:docker_up 过 / 无 500 / 无 boot bug / 交付 run 要求满足;#217 在 r18 真实数据 0/9→9/9 用户加载)。剩下的**唯一交付 + 视觉瓶颈是前端页面质量**。

---

## 1. 为什么会构建 fallback(根因,已核实)

fallback **不是设计目标,是框架的"构建保险丝"**。机制在
`agent/env_generator/llm_generator/multi_agent/runtime/frontend_scaffold.py`:
- `scaffold_missing_local_pages()`(:1830)扫描前端,发现"被 import + 路由、但页文件缺失"的组件。
- 对每个缺失文件,用 `_project_page_component()`(:1664)塞一个**通用占位页**:顶部导航 + 拉一个 endpoint 渲染成列表 / "No data yet",打标 `data-fallback="1"`(模板 :1736,硬编码浅色 `bg-zinc-50`)。

**根因链:**
1. 前端 lane 在 App.jsx 给**每个内容页都接了 import + `<Route>`**(For You / Explore / Following / Friends / Live / Messages / Activity / Profile …)。
2. 但它**只真正 author 了 3 个 auth 页文件**(Login / Signup / LoginModal),其余 **11/14 页文件根本没建**。
3. 一个"接了却没建"的页 → `npm run build` 报 `Could not resolve` → 前端容器起不来 → app 死。框架为了不让 build 挂,就用通用 fallback 补缺口。

→ **fallback = lane 路由了内容页但没 author 组件,框架把缺口补成"能编译的空壳"。** 正是要消除的 mock/placeholder。

r18 / r19 都 abort 在 `business_chain_failing` + `deliverability_ui_flow_missing` —— **前端页面前沿,不是 infra/seed**。lane 甚至会"糊弄 page-audit"(改 API 调用格式、删框架注释让 auditor 不判为 stub)而不是建真页。

---

## 2. 要做到"零 fallback"必须同时成立

- **① lane 必须真建每个路由页**(完整性),或
- **② 框架的 projection 不能是通用列表,而应 by-construction 生成真页**(消费 `design/component_specs` 的测量布局 + 该路由真实数据 endpoint)。

因为 lane 建页不可靠,**②(by-construction)是唯一能保证零 fallback 的路子** —— 像 backend skeleton 那样,把"页面结构生成"变成框架自有,lane 只做精修。

---

## 3. 调查 + 修复计划

### 3.1 调查根因(为什么 lane 只建 auth 页)
候选:(a) 里程碑预算被 infra/协调 churn 耗尽(我这轮已大幅减少 churn);(b) **fallback 当拐杖** —— 框架自动补了"能用"的页,lane 就没动力建真页;(c) 前端生成缺 per-page 布局 scaffold。
- 用 `gemini-3.1-pro-preview-customtools` 跑 tiktok:`./run_tiktok_designinput.sh <N>`(内部 setsid,rotation-safe)。
- **优先用"本地 exec 生成代码"的快速取证法**(见 §6),不必每次等 90 分钟跑。

### 3.2 by-construction 消除 fallback(核心杠杆)
让 `frontend_page_projector` / `_project_page_component` **不再产出通用列表**,而是:
- 消费 `design/component_specs/`(每屏测量的区域 / 布局 / 组件几何)+ 该路由真实数据 endpoint;
- 生成**参考结构化、已填充、功能完整**的真页。TikTok = 左侧栏 + 9:16 视频 + 右侧操作栏的**三栏布局**,不是顶部导航 + 列表。
- 目标:**即便 lane 没写,框架产出的也是真页而非空壳。**
- ⚠ `component_specs` 目前是 advisory(测了但没强消费,visual GAP 3)—— 要把它变成一等输入。
- ⚠ 上轮发现 `type_scale / radius_scale / shadow_scale` 测出来是空(`[]`/`{}`)—— 顺带查 design-prep 的测量为什么没填,影响布局保真。

### 3.3 硬门禁 + 修 audit
- 交付门 **HARD-FAIL** 任何 `data-fallback="1"` 的页(针对参考覆盖的路由)。
- 修 stub-detection audit,让它**奖励"真内容 / 真布局"**,而不是被 lane 用"改 API 调用格式"糊弄过去。

---

## 4. 下一个 session 启动指令(复制粘贴)

```
/loop 目标:彻底消除前端 fallback/占位页。基础设施+seed 层已稳固(#207-#218 已合并,app 能可靠
boot/serve/暗色/seed/填充数据),唯一剩下的交付+视觉瓶颈是前端页面质量:lane 只 author 了 auth 页,
11/14 内容页是 frontend_page_projector 生成的通用 fallback(data-fallback="1",接口拉列表/"No data yet",
不匹配参考布局)。r18/r19 都 abort 在 business_chain + ui_flow(前端页面前沿),不是 infra/seed。

先读 HANDOFF_2026-07-19_frontend_zero_fallback.md 和 memory
project_envgen_opt6_visual_delivery_207_213(整段历史+方法论),再深挖:

1) 调查根因:为什么 lane 只建 auth 页?(a)预算耗尽 (b)fallback 当拐杖 (c)缺 per-page 布局 scaffold。
   用 gemini-3.1-pro-preview-customtools 跑 tiktok(./run_tiktok_designinput.sh N,setsid),
   优先用"本地 exec 生成代码"的快速取证法。

2) by-construction 消除 fallback(核心):让 frontend_page_projector 不再产出通用列表,而是消费
   design/component_specs(每屏测量的区域/布局)+ 该路由真实数据 endpoint,生成参考结构化、已填充、
   功能完整的真页(TikTok=左侧栏+9:16 视频+右侧操作栏三栏,不是顶部导航+列表)。即便 lane 没写,
   框架产出的也是真页而非空壳。

3) 硬门禁:交付门 HARD-FAIL 任何 data-fallback="1" 的页(参考覆盖路由);修 stub-detection audit,
   奖励真内容/真布局而非被 lane 改 API 格式糊弄过。

铁律:改动必须 env-agnostic(服务多样环境,不只 tiktok);每改动 TDD;agent/tests 不提交;
key 只在 /tmp/envgen_key.sh;default key 推 vaibackup;不加 Co-Authored-By;最终 runtime-verify
交付的 app(真 DOM/真数据/真布局),不能被静态门骗过。

达到:和真 app 一模一样、无 bug、功能完备、所有 UI/API/按钮有真功能、零 mock/placeholder/fallback。
loop 间隔短一点醒来防止卡住烧 token。开始吧
```

---

## 5. 铁律 / 约束(不变)

- **env-agnostic**:pipeline 目标是 generate 多样环境,改动不能只服务 tiktok。
- **每个改动 TDD**(superpowers:test-driven-development):先写失败测试,再最小实现。
- `agent/tests/` 是 gitignore 的 —— **永不提交测试**;只提交 production code。
- Key 只在 `/tmp/envgen_key.sh`(`GOOGLE_API_KEY` + `ENVGEN_UNSPLASH_KEY` + `ENVGEN_PIXABAY_KEY`)—— 永不提交。
- 推送用 default key `~/.ssh/id_ed25519` → `vaibackup`(**不是** id_ed25519_virtueai,那个 repo 已死)。
- commit **不加** `Co-Authored-By` trailer。
- 用户 merge PR —— 我只 commit + push。
- 不要在用户测试某 live env 时 `docker down -v`;`:8080` 是常驻 gmaps demo(#207 保护对象)。
- **最终必须 runtime-verify 交付的 app**(真 DOM / 真数据 / 真布局),别被静态/token 门骗过(#172/#173 教训)。

---

## 6. 关键方法论(省时间,务必用)

- **本地 exec 取证(最快找 codegen/seed bug)**:直接 exec 生成的 `models.py` / `seed_data.py` / 组件,针对某次 run 的真实 `seed_data.json` / 合约跑,**秒级**定位 bug,不必等 90 分钟 run。#217(空 app 根因:用户缺 email/name)就是这么在几秒内抓到的。
- **跑实验**:`./run_tiktok_designinput.sh <N>`(setsid;真 PID 用 `pgrep -f miniconda3/envs/dt/bin/python -m env_generator.llm_generator.main`)。杀死锁死的 run:`kill -TERM -<PID>`(setsid=PGID leader)。
- **监控**:给 run log 挂 Monitor,只 grep 决定性事件(STUCK-LOOP / NO-CONVERGENCE / boot traceback / api_smoke PASSED / create_release / Generation Complete),别 grep 编排叙述(会 per-milestone 刷屏烧 token)。run 健康时 backstop wakeup 拉长(1200-1800s);Monitor 已覆盖 wedge。
- **两 run 不并发**(资源争抢);run 脚本已内置拒绝。
- **Python**:`/home/haibotong/miniconda3/envs/dt/bin/python`。

---

## 7. 相关文件指针

- fallback 生成:`frontend_scaffold.py` `scaffold_missing_local_pages`(:1830)、`_project_page_component`(:1664)、fallback 模板(:1736 / :1786)。
- 页面 projector:`frontend_page_projector.py`。
- 测量输入:`design_prep.py`;产物 `<output>/design/component_specs/`、`design_system.json`(palette 有 / type_scale 空)。
- 视觉门:`visual_fidelity.py`(#207 端口修复在此)。
- 交付门 / audit:`delivery_gate.py`、`frontend_audit.py`、`flow_coverage.py`、`backend_audit.py`。
- seed loader 生成器:`backend_skeleton.py`(#213/#217/#218 在此)。
- 完整历史 + 每个修复细节:memory `project_envgen_opt6_visual_delivery_207_213`(+ 上游 `project_envgen_opt6_fixes_186_194`)。
