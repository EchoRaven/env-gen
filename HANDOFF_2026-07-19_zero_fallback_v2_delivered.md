# HANDOFF 2026-07-19(v2)— 零 Fallback 已达成 + 首次交付;下一步:交付稳定率 + 视觉/交互精修

> 上一份 handoff(HANDOFF_2026-07-19_frontend_zero_fallback.md)的任务**已完成**:
> **r21 完成了本 pipeline 史上第一次 TikTok 交付(release 1.0.0),runtime 验证零 fallback。**
> 本 session 共落地 **15 个 env-agnostic 修复 #219–#233**(全 TDD,HEAD `44c26f7`,已推
> `feat/pipeline-opt-6` + PR 分支 `pipeline-opt6-tiktok-delivery-186-205`,**用户 merge**)。
> 下一个 session 的主战场:**交付稳定率(run-to-run 方差)+ 交付物的视觉/交互精修**。

---

## 0. 先做

1. **确认 PR 是否已 merge**(HEAD 44c26f7,15 commits f7b6f78..44c26f7)。未 merge 就继续在
   `feat/pipeline-opt-6` 上工作。
2. **查 r25 结局**(写这份文档时 r25 还在跑,PID 1956868,log `gm_tiktok_r25.log`,已用
   grace #1、只剩 ui_flow_missing、35 flows 记录中——和 r21 交付前形态一致):
   - `ps -p 1956868`;`grep -E "create_release|Generation|ABORT" gm_tiktok_r25.log | tail`
   - 交付了 → 做完整 runtime-verify(§4);abort 了 → 按 §5 方法论尸检,通常又是一类新修复。
3. **磁盘**:root 已从 100% 清到 90%(docker builder prune 179G + /tmp 清理)。每次 run 前
   `df -h /`;docker build cache 每天涨 30-60G,满了就 `docker builder prune -af`(安全)。
   ⚠ /home 有同事 1.2T 在 root 盘(不能动,已报告用户);/data2 99%。

## 1. 已达成什么(不要重做)

- **r21 交付 release 1.0.0**(09:49),app 容器留在 **fe :8003 / api :8002 / pg :8004**(别 down)。
- **Runtime 验证**(playwright 无头,dt env python):8 路由 `[data-fallback]`=0;auth 发 token;
  /api/videos 39 条真数据(真 mp4);首页=暗色三栏 TikTok 壳(真 SVG 图标侧栏,截图验证)。
- r18 的"11/14 页是通用空壳"已根治:r21 最终树 20 页全 lane 真写,r20 最终树也是 20/20。
- 快速验证脚本样例:scratchpad 里写过 verify_r21.py(register→token→走 8 路由→PROBE
  fallback/asides/videos/buttons+截图)。核心 PROBE:`document.querySelectorAll('[data-fallback]')`。

## 2. 15 个修复清单(#219–#233,file:line 级)

全在 `agent/env_generator/llm_generator/multi_agent/` 下;测试在 `agent/tests/`(**gitignore,不提交**)。

**A. 地板 by-construction**
- **#219** frontend_scaffold.py `render_measured_tailwind_theme`:theme 导出去掉双层嵌套
  (`{colors:{...}}`,原来 bg-bg/text-accent 从未生效);`_apply_measured_palette` 合并 lane token。
- **#220** design_prep.py:skeleton 用 `grid_columns/row_bands` 确定性测每组件 `geometry`
  (≥2% 面积)+ screen `layout_metrics`(content_bounds);`_SCREEN_TOOL` 补 shadow_scale。
- **#221(核心)** frontend_scaffold.py `_render_reference_page`(~L1900 起):fractional region
  →bands(left/right/top/main);`_comp_kind_221` 词元计分(**词边界**,'displaying'≠'playing');
  media 面=9:16/16:9(区域纵横比)+prev/next idx;grid 用测量列数(无 geometry 时按区域宽推);
  **重复同角色卡片→测量列数网格+引号动作按钮('Follow')**;media+list→播放器+缩略条;
  测量色 inline;`_STRUCTURED_MARKER` + `data-projected="ref"`。两个入口
  (`scaffold_pages_from_contract`/`scaffold_missing_local_pages`)都传 design。
- **#225** `missing_design_screen_pages`:screens(kind=page+route)→合成 ui_page(apis_used 按
  GET 集合端点词元重叠推),scaffolder.scaffold_frontend_pages 每 tick 注册(幂等)。
- **#226/#229** `_design_screen_for_route(design, route, hints=)`:精确路由失配后按
  `_semantic_tokens_226`(camelCase 拆分+去 layout 停用词+单复数)模糊匹配;**hints=page 的
  name/id/component**(修 /@:username→profile_own);零重叠=不匹配(宁可 generic 不错嫁接)。
  `missing_design_screen_pages` 同词表防双胞胎注册。
- **#227** `_asset_urls_227`+`_ref_nav_jsx(asset_urls=)`:nav 组件映射的 staged 素材直接渲染
  (logo 置顶链 '/';图标按 id 词元↔label 匹配;staged_path `public/assets/…`→`/assets/…`;仅图片)。

**B. 审计防糊弄 + 硬门禁**
- **#222** frontend_audit.py `_is_generic_fallback_page`:内容指纹(helper 星座
  `const _imgOf/_titleOf/_subOf/_metaOf` + generic 壳)+ marker/attr;structured
  (data-projected/_STRUCTURED_MARKER/inline backgroundColor)豁免;hard miss
  `"framework fallback page"` 走既有 ui_page_unwired 通道。
- **#223** `routed_fallback_page_blockers`(未注册但 App.jsx 接线的 fallback 也拦)→
  deliverability.py 折叠(`ENVGEN_FALLBACK_PAGE_GATE` 开关)+ delivery_gate token
  `deliverability_frontend_fallback_page` + remediation_dispatcher `_GATE_OWNER` frontend 条目。
- **#224** test_user_runner.py:`_PROBE` 数 `[data-fallback]`(fbEls)→`fallback_dom_pages`
  =**硬 hold**(browser_gate_decision 永不 escape);每路由 `route_seed_hit`→`dataless_pages`
  (advisory)。
- **#231d** `primary_dataless`:主路由 '/' 无 seed 渲染=硬 hold(r21 首页空 feed 靠 2 个
  tab 标签词溜过全局 real_data 的教训)。
- **#233** `bare_authed_fetch_blockers`:`headers: helper()` / `...helper()` 视为 opaque 豁免
  (r23 被 13 个**正确**调用点假阳性卡死 83 分钟;r23 真树验证 13→0)。

**C. 交付收敛**
- **#228** delivery_gate.py `convergence_grace()`(纯函数)+ orchestrator ~L2565 wire-in:
  失败集 ≤2 且 30min 内缩过 且 宽限 <2 → +900s(r20 差 36 秒被杀的直接教训;r21 靠它交付)。
- **#230** orchestrator ~L1178 里程碑重置块补 `_fwdeliver_grace_count/_prev_failed/_last_shrink_ts`。
- **#232** framework_validation.py ~L778:api_smoke 首次 PASS 即派发
  `deliverability_ui_flow_missing` remediation(once-per-run guard;r20/r22 的死因=flows 只在
  最终门禁报警时才派)。

**D. 交付物真 bug(#231,r21 /api/feed 404 split-brain 尸检产物)**
- frontend_audit `_registered_paths` + heal_pipeline `_reg_paths`:**deprecated 不算已注册**。
- `reconcile_frontend_api_paths`:版本段无关重写(/api/feed↔/api/v1/feed 双向,唯一匹配才改)。
- registryhub `deprecate_endpoint` **级联**:行为元数据(auth_required/response_key)带到
  replacement + 重写 ui_pages.apis_used(旧声明曾把 lane 引回死路——弃用 29 秒后 lane
  "纠正"回 /api/feed)。

## 3. 五个 run 的战绩线(方差样本,尸检素材都在)

- **r20**(#219-#225):史上最佳未遂——全 20 页 lane 写、15/15 flows 绿,**差 36 秒**被 75min
  fail-fast 杀 → #226/#227/#228。
- **r21**(+#226-#228):**交付 1.0.0**(两次 grace 兜住)→ M2 阶段 abort(grace 没按里程碑
  重置→#230;/api/feed split-brain→#231)。
- **r22**:endgame 过载 abort(13 flows 注册 0 记录;lane signup 空 body 500 被 chain 正确抓)
  → #232。
- **r23**:**#233 假阳性门禁冤杀**(13 个正确调用点)——★硬门禁上线前必查 FALSE-BLOCK(opt-5 老教训)。
- **r24**:磁盘满环境性失败(verifier 自己诊断出 ENOSPC)→ 清盘 →
- **r25**:完整栈+净盘,写文时在交付收敛末段。

## 4. 交付后 runtime-verify 怎么做(必做,别被静态门骗)

1. run 结束(进程退出)后:`docker compose -f generated/tiktok-web-rNN/docker/docker-compose.yml
   up -d --build`(**run 活着时绝不 up/down**);端口看 compose(run-specific)。
2. dt env python + playwright(chromium bundled;MCP playwright 缺 chrome 用不了):
   register→拿 token→注入 localStorage→走全路由→PROBE:
   - `[data-fallback]` 必须 0;主路由必须渲染 seed 值(**#231 后 feed 应有视频**——r21 的
     残留缺口就是 feed 空);
   - 三栏布局(aside 存在)、<video>、按钮可点、截图肉眼比对参考。
3. 结果写进 memory;发现新缺口=下一个修复类。

## 5. 方法论(省几小时的)

- **先本地 exec 取证再跑 90 分钟 run**:直接调用生成器函数打真 run 的 design_system.json/
  ui_pages(#221/#226/#227/#229/#233 都这么秒级验证)。
- **尸检套路**:log grep 决定性事件 → shared/hubs/*.json(registryhub_endpoints/ui_pages/
  verification_chains/codehub_checks/workhub_tasks)还原时间线 → 跑真门禁函数对最终树。
- **Monitor 只 grep 决定性事件**(ABORT/GRACE/api_smoke/create_release/#232),排掉
  retrying/re-roll(Gemini MALFORMED_FUNCTION_CALL 是常态噪音);backstop wakeup 720-1500s。
- **baseline 用 worktree 别用 stash**(本 session 一次 stash+超时差点丢改动)。
- 跑 run:`./run_tiktok_designinput.sh <N>`(setsid;两 run 不并发;杀死锁:`kill -TERM -<PID>`)。
- suite 有 **13 个 pre-existing failures**(deliver/retro/flow_coverage/visual-mint 族,
  worktree 在 a2050dc 验证过)——不是你弄坏的。

## 6. 下一步 backlog(按优先级)

1. **交付稳定率**(run-to-run 方差是现在最大的敌人):
   - verifier endgame 仍是单 lane 串行瓶颈,#232 只提前了 flows;考虑把 chains 和 checklist
     也提前派发(同 #232 模式);或 required-flow 集瘦身(#225 扩了页面集→35 flows 有点多,
     考虑只 critical + 参考覆盖路由)。
   - #231 尸检 rank-3:contract_alignment 的 frontend-drift 错误类在 functionally_validated
     后被抑制(delivery_gate.py:1076)——要求 passing run 比 endpoints registry 的
     last_modified 新,或该错误类不豁免。
   - rank-6:#180 版本变体合并改成**框架侧确定性执行**(保留前端在调的那个,弃用另一个,
     级联重写),不再靠两个 lane 竞速;合并任务在飞时不 cut release。
2. **视觉/交互精修**(交付物离"一模一样"的差距):
   - requires_auth:false 的 screen → 对应 GET 端点 auth_required:false **全映射**
     (#231 级联只救了丢失场景;登出态 feed 应像参考一样有内容);
   - 视觉门分数拉高:#227 只覆盖 nav 素材,内容卡片的真素材(封面/头像)映射还靠 lane;
   - 登录态全交互 runtime 验证(点赞/评论/关注真按钮真效果)。
3. **泛化验证**:换一个 env(youtube/outlook 素材现成)跑同栈,确认 #219-#233 无 tiktok 特化。

## 7. 铁律(不变)

env-agnostic;每改动 TDD(tests 本地不提交);key 只在 /tmp/envgen_key.sh;push 用默认 key
`~/.ssh/id_ed25519` → **vaibackup**(同时更新 PR 分支);不加 Co-Authored-By;用户 merge PR;
最终必须 runtime-verify 交付物;r21 的 :8003/:8002 容器留着;别在用户测试时 docker down。

## 8. 下一个 session 启动指令(复制粘贴)

```
/loop 目标:让 pipeline 生成的 app 和真 app 一模一样、功能完备、零 mock/placeholder/fallback,
env-agnostic。零fallback+首次交付已达成(r21 release 1.0.0,runtime 验证 8 路由 [data-fallback]=0),
本阶段主攻:①交付稳定率(run-to-run 方差:verifier endgame 串行瓶颈、required-flow 集瘦身、
contract_alignment 反抑制 rank-3、#180 框架侧合并 rank-6)②交付物视觉/交互精修(requires_auth
全映射、内容卡片真素材、登录态交互验证)③换 env(youtube/outlook)验证泛化。

先读 forgingground-gen/HANDOFF_2026-07-19_zero_fallback_v2_delivered.md 和 memory
project_envgen_frontend_zero_fallback_findings(15 个修复 #219-#233 的完整清单+5 个 run 战绩+
方法论),再:1)查 r25 结局(交付→按 §4 runtime-verify 重点验 feed 有视频+主路由硬门禁;
abort→按 §5 尸检,通常又是一类新修复);2)从 backlog §6 按优先级实施,每改动 TDD+live 验证;
3)每次 run 前 df -h /(docker build cache 涨得快,builder prune 安全)。

铁律:env-agnostic;agent/tests 不提交;key 只在 /tmp/envgen_key.sh;默认 key 推 vaibackup
(feat/pipeline-opt-6 + PR 分支都推);不加 Co-Authored-By;用户 merge PR;两 run 不并发;
r21 的 :8003/:8002 容器留着;最终必须 runtime-verify 交付的 app,不能被静态门骗过。
loop 间隔短一点醒来防止卡住烧 token。开始吧
```
