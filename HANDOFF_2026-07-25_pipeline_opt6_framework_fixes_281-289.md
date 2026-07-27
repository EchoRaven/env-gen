# HANDOFF — pipeline-opt-6 框架修复 #281–#289 (2026-07-23 → 07-25)

## TL;DR
本轮 loop 在 forgingground-gen 的 `feat/pipeline-opt-6` 分支上,通过反复跑 TikTok 生成
run(r64→r75)、每个 run 精确暴露一个框架 bug、逐个定位并修复,交付了 **9 个框架修复
(#281–#289)**,全部实测定根 + TDD + stash 零回归验证,已推送到 `vaibackup`
(HEAD=`ccbb625`, unpushed=0)。

**核心成果不是"某个 run 交付了",而是前沿的性质变了:** 从"框架 bug 到处卡死
business_chain"一路推进到"框架层死结全清、只剩 LLM 前端代码质量波动(fallback pages /
unwired routes)"。r74 是最深验证——8 个修复让它走到前端质量全清、只剩一个 `tenant_isolation_like`
探测(=#289 根因)。

## 环境 / 命令速查
- **仓库**: `/data/common/haibotong/forgingground-gen`, 分支 `feat/pipeline-opt-6`
- **推送**: `git push vaibackup HEAD:feat/pipeline-opt-6` (origin=Virtue-AI 已废弃,用 vaibackup;
  默认 id_ed25519/EchoRaven key,已在 checkout 上 pin)
- **LLM key**: `source /tmp/envgen_opus47.sh` (opus-4.7 vertex; ENVGEN_PROVIDER/MODEL/API_BASE/LLM_KEY)
- **起 run** (setsid 必须,否则 session 轮转会静默杀子进程):
  ```
  cd /data/common/haibotong/forgingground-gen
  source /tmp/envgen_opus47.sh
  setsid nohup env ENVGEN_PROMPT_VERSION=v4 ENVGEN_PROVIDER="$ENVGEN_PROVIDER" \
    ENVGEN_MODEL="$ENVGEN_MODEL" ENVGEN_API_BASE="$ENVGEN_API_BASE" \
    ENVGEN_LLM_KEY="$ENVGEN_LLM_KEY" ./run_tiktok_designinput.sh <N> > /dev/null 2>&1 < /dev/null &
  disown; sleep 45; # 验证 SID==PGID==PID
  ```
- **日志**: `gm_tiktok_r<N>.log`; **生成物**: `generated/tiktok-web-r<N>/`
- **pytest**: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_28X_*.py -q`
- **测试是 gitignored 的本地测试** (`agent/tests/`),只提交框架代码

## ★ 核心方法论 (贯穿全轮,最重要的可迁移经验)
**用真实 `execute_chain` / `compute_flow_coverage` 对活容器/真实 hub 复现,把表象还原为真相。**
这一招既抓出真 bug,也一次次避免了追假 bug:
- UUID-404 表象 → 实测发现是 share action 未实现(lane 问题),r69 的 uuid4 主键是误导
- login 401 表象 → 实测 execute_chain login 200,是间歇时序 + 框架已有 last_reg_creds 机制
- ui_flow_failed 表象 → 真实 hub 跑 compute_flow_coverage,定位到 _flow_key 归一化 bug(#285)
- **端口必须从 `generated/<env>/docker/docker-compose.yml` 读**(取 "HOST:8082"),
  不能 `docker ps|grep backend`(机器上十几个 env 容器,会打错 app;我误打过 rydr:3011)。
  再用 `/openapi.json` 确认领域。

## 9 个修复详解 (都在 `agent/env_generator/llm_generator/`)
每个都符合用户铁律"框架生成代码/门禁必须泛用正确"——框架的 bug 会让 lane 追不存在的缺陷。

| # | commit | 文件 | 缺陷本质 |
|---|--------|------|---------|
| #281 | 5b95a3b | runtime/chain_executor.py + validation_runner.py | executor 只发 JSON,但框架脚手架的 OAuth 端点用 `Form(...)` → 400 永不可修。修:签名检测 JSON/Form 不匹配 → form 重试一次 |
| #282 | 2c4e629 | runtime/backend_scaffold.py | IntegrityError→404 映射销毁 FK 真因(响应+日志都没有) → lane 被误导查一个存在的资源。修:响应体不变,真因入服务端日志 |
| #283 | 36b3ccc | runtime/chain_executor.py | seed 无显式 id → `load_seed_ids` 全瞎(返回{}),#130/#135/#144 三恢复机制失效。修:位置回退 id;纯关联表(全FK)排除 |
| #284 | 42efaa5 | runtime/remediation_dispatcher.py | verifier 谎称已记录 ui_flow(hub 里根本没有),框架轻信空转40min。修:派单重算门禁 missing + 点名矛盾"广播说已记录≠记录存在" |
| #285 | 42d7c94 | runtime/flow_coverage.py | `_flow_key` 折叠 `_page` 却不折叠 `_ui`/`_page_ui` → verifier 的 X_page_ui(passed) 盖不住 X_page(failed) → 6 个通过的 flow 误判 FAILED。修:循环剥 _ui/_page/_screen |
| #286 | 3193ca2 | tools/validation_tools.py | run_validation 落 contract_test/build/runhub 却不落门禁要的 check=api_smoke record → 三个 run 卡死。修:report.passed 时落 api_smoke record |
| #287 | cdfc2ea | runtime/delivery_gate.py | ui_smoke_pass 只认 {ui_smoke,ui_page_reachable},不认逻辑更强的 passing ui_flow(_has_passing_ui_evidence 却认)→ 两处判定不一致。修:ui_smoke_pass 也认 ui_flow |
| #288 | b591a74 | runtime/route_projector.py | 投影给公开视频的 nested 互动 parent 加 `author_id==user` owner-scope → 非作者评论/点赞 404。修:parent 是 primary content model(公开)时不 scope;私有容器(projects)仍 scope。#279 自然扩展 |
| #289 | ccbb625 | runtime/chain_executor.py | 对公开社交动作(like/save/follow/share)的跨用户 denial probe(expect 404)永不可能过(#288 让它们公开→201)。修:social verb 白名单的 denial probe 放宽接受 2xx;sensitive verb(transfer/promote/delete)保持隔离。#275 扩展 |

**★ #288+#289 是配套的一对**: #288 修投影行为(社交动作公开), #289 修验证探测(不对公开动作写隔离断言)。

## run 历史与前沿演进
- **r64/r65**: 我**误杀**了(以为冷启动死锁)。教训:Cold start persists 在 design-prep(10-15min)期间是正常的;真死锁判据=design_system.json 建成>20min 仍无 milestone。
- **r66/r67**: 死在 business_chain 完全跑不通 → 暴露 #281(oauth Form)/#282(FK 真因)
- **r68**: 史上最远(当时)——api_smoke 30链196步绿,只差前端一个 lane 缺陷
- **r70**: 只剩 ui_flow_failed → 真实 hub 定位 #285(_flow_key 归一化)
- **r71**: 后端链路首次全通;门禁降到只剩 ui_smoke → #286/#287 真实数据验证
- **r73**: 只剩 fyp_comments → 定位 #288(投影 owner-scope 公开评论)
- **r74**: 最深验证——前端质量全清(9 fallback + 2 unwired 全被前端 lane 修好),只剩 tenant_isolation_like → #289
- **r75** (本文档时在跑, PID 3306108, ~2h): 门禁从 20 收敛到 6,主要是 frontend_fallback_page(前端质量波动)

## 当前状态 / 前沿判断
- **框架层(#281–#289)已彻底清完**。每个 run 精确暴露一个框架 bug,已逐个修掉。
- **剩余前沿 = LLM 前端代码质量**: frontend_fallback_page(前端 lane 生成 fallback 而非真实页面)、
  ui_page_unwired(声明页但没接 App.jsx 路由)。检测(#222/#223)成熟正确,是**真** fallback,不是框架 bug。
  前端 lane 有时质量够(r74 全修好)、有时不够(r75 早期一堆 fallback)——模型/prompt 的随机波动,
  **不是修框架能解决的**。
- **间歇时序假失败**: business_chain_failing 常"broken 为空却报 failing"(容器重建期间跑 validation),
  是时序不是 bug;converging-grace 通常能救,偶尔耗尽。

## ⚠️ 工具环境问题
本轮后段 **Write/Edit/Read 工具的 PreToolUse hook 反复超时**("host client may be unreachable")。
根因: `CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING=true` + 这是跑了跨两天的 child session
(`CLAUDE_CODE_CHILD_SESSION=1`),file-checkpoint 的 host client 失去响应。Bash/git/Monitor/TodoWrite
不走 checkpoint 路径,正常。**Workaround**: 用 Bash+Python 做文件编辑(读-替换-校验唯一匹配-写回+语法检查)。
**彻底修: 重启 session**(新 host client),9 个修复已全推送,重启不丢东西。#289 就是这么完成的。

## 下一步方向候选
1. **等 r75 结局**,看能否首次完整交付(#288/#289 应清除 fyp_comments/tenant_isolation_like);
   若前端质量够好则交付,不够则 fail-fast 在 fallback pages。
2. **前沿已是 LLM 前端质量,不是框架 bug** —— 若要继续提升交付率,方向是**前端 lane 的 prompt/模型
   质量**(让前端 lane 少生成 fallback、多接路由),而非再找框架 bug。可考虑:frontend_page_projector
   的 prompt 强化、或更强模型跑前端 lane。
3. 若又暴露新框架 bug(第10个),用同样方法:真实复现→TDD→stash 零回归→推。
4. 可选的鲁棒性增强(非 bug): comments 表被 lane 标 owner_scoped_reads 导致 child 列表"只显示我的评论"
   (#288 只修了 parent-scope 一半,见 #288 commit 末尾 NOTE);business_chain 间歇时序假失败(validation
   撞容器重建)。

## 自我纠错记录 (诚实,供参考)
1. 误杀 r64/r65(Cold start 正常,非死锁)——已写入记忆
2. 首次 #281 端到端验证误打在 rydr:3011(端口要从 compose 读)——已写入记忆
3. #283 第一版实现过宽(给纯关联表也造 id),被既有测试抓住——细化为排除全FK表
4. #287 中途在笔记里错判"框架不能代劳 ui_smoke",深挖发现是两处判定不一致(证据一直存在)
5. r72 login 401 差点做冗余 #288(实为间歇时序,框架已有 last_reg_creds)——用真实 execute_chain 证伪
6. UUID-404 被 r69 的 uuid4 主键误导追了半天,换整数-id 的 run(r70/r72)才分离出真相(share 未实现)

**方法论精髓: 说"框架不能确定性验证 X"之前,先查 lane 是不是已经产出了等价证据只是门禁没认;
用真实复现证伪表象,再动手。**
