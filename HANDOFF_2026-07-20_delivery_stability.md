# HANDOFF 2026-07-20 — 交付稳定率 + ui_flow 天花板已破 + 两类 build-break 根治

> **一句话**:本 session 在 `feat/pipeline-opt-6` 上落地 **9 个 env-agnostic 框架修复 `#234`–`#242`**
> (全 TDD,HEAD `9dc7a2b`,已推 `feat/pipeline-opt-6` + PR 分支 `pipeline-opt6-tiktok-delivery-186-205`)。
> **最大成果:根治了杀死 r29/r30 的复现交付天花板 `ui_flow_failed`(#240+#241),并修掉两类
> build-break(#239 `??/||`、#242 幻觉依赖)。** r27 曾交付 M1(史上第二次)。下一战场:
> `business_chain_failing`(硬编码 id / 字符串路径参数)+ 继续跑 r33+ 验证全栈能否稳定交付。

---

## 0. 先做（新 session 启动清单）

1. **读 memory** `project_envgen_frontend_zero_fallback_findings`(本 session 全部战绩+根因的权威记录)。
2. **确认 PR 是否已 merge**:HEAD `9dc7a2b`,commits `f7b6f78..9dc7a2b`(#219–#242)。未 merge 就继续在
   `feat/pipeline-opt-6` 工作。**用户 merge PR,你不 merge。**
3. **查最近一个 run 的结局**(写这份文档时 r33 在跑,PID `891777`,log `gm_tiktok_r33.log`):
   - `ps -p <PID>`;`grep -E "create_release|NO-CONVERGENCE ABORT|CONVERGING-GRACE" gm_tiktok_r33.log | tail`
   - 交付了 → §4 runtime-verify;abort 了 → §5 尸检套路。
4. **磁盘**:`df -h /`。root 盘每天涨 30-60G(docker build cache)。`< 100G` 就
   `docker builder prune -af`(安全,不碰运行中的容器)。⚠ /home 有同事 1.2T、/data2 99%,别动。

---

## 1. 如何启动 / 运行（完整命令）

### 环境
- **生成器仓库**:`/data/common/haibotong/forgingground-gen`(git remote `vaibackup` = `git@github.com:vaibackup/forgingground-gen.git`,默认分支 `main`)。
- **Python**:`/home/haibotong/miniconda3/envs/dt/bin/python`(DecodingTrust 的 dt 环境,pytest / playwright 都用它)。
- **Key**:`source /tmp/envgen_key.sh`(含 `GOOGLE_API_KEY` + `ENVGEN_UNSPLASH_KEY` + `ENVGEN_PIXABAY_KEY`)。**key 只在这里,永不进仓库/log/handoff。**
- **push**:默认 SSH key `~/.ssh/id_ed25519` → 认证为 `vaibackup`(git push 可用)。⚠ `gh` CLI 在
  `/home/haibotong/miniconda3/envs/dt/bin/gh` 但**未认证**(无 GH_TOKEN)→ 不能用 gh 建 PR,只能 git push + 网页建 PR。

### 跑一个 run
```bash
cd /data/common/haibotong/forgingground-gen
./run_tiktok_designinput.sh <N>          # 例: ./run_tiktok_designinput.sh 34
```
脚本会:`setsid` 脱离会话(会话轮转不杀 run)、`source /tmp/envgen_key.sh`、**磁盘预检 ≥60G**、
**playwright 浏览器预检**(#234 教训:headless-shell 被清盘误删过)、启动
`python -m env_generator.llm_generator.main --name tiktok-web-r<N> --design-input design_inputs/tiktok --provider google --model gemini-3.1-pro-preview-customtools`,
输出到 `generated/tiktok-web-r<N>/`,log 到 `gm_tiktok_r<N>.log`。返回**真 PID**(python 进程,非 wrapper)。

铁律:
- **两 run 不并发**(脚本有 `pgrep` 守卫会拒绝;`kill -TERM -<PID>` 杀一个)。
- **run 活着时绝不 `docker compose up/down`**(会撞端口 + 打断 run 的 validation)。
- **每个 run 用不同端口**(compose 里随机分配!别假设 8003/8002)。r30=UI:8080/API:3001/PG:5433,
  r32 同。**读 `generated/tiktok-web-r<N>/docker/docker-compose.yml` 的 `ports:` 取真实端口。**

### 监控一个 run(Monitor 只 grep 决定性事件)
```
tail -f -n0 gm_tiktok_r<N>.log | grep -E --line-buffered \
 "CONVERGING-GRACE|create_release|NO-CONVERGENCE|ABORT|Kickoff timed out|Cannot use|_framework|api_smoke PASSED|Generation (complete|failed)"
```
排掉 `retrying` / `MALFORMED_FUNCTION_CALL`(Gemini 常态噪音)。backstop wakeup 900-1500s。

### 跑测试
```bash
cd agent && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest tests/test_XXX.py -q
```
⚠ **`agent/tests/` 是 gitignored,永不提交。** 有 ~2 个 **pre-existing** flow_coverage 失败
(`test_pages_without_critical_flag_not_required`、`test_missing_flow_does_not_block_functionally_validated_app`)
+ 一个 `test_include_template_logs_nested_import_error`(NameError),都在 baseline `2a57934` 就红,不是你弄坏的。

---

## 2. 本 session 的 9 个修复（#234–#242,file:line 级）

全在 `agent/env_generator/llm_generator/` 下。

### A. 基础设施
- **#234** `tools/browser/_bootstrap.py`(新) + `_manager.py`/`test_user_runner.py`/`test_user_validation.py`/`visual_fidelity.py`:
  playwright 浏览器二进制被清盘误删过(r24/r25 共 182 次静默 launch 失败,runtime 门禁全盲)。检测
  "Executable doesn't exist" 签名 → 进程内一次性 `playwright install` → 重试;失败则 LOUD "BROWSER INFRA DOWN"。
  4 个 launch 点全接入。run 脚本也加了 preflight。

### B. Auth / 契约
- **#235** `backend_scaffold.py`(guard 白名单泛化为 bootstrap 词尾 login/register/signup/signin/token/refresh/logout)
  + `backend_skeleton.py`(signup/signin 别名到 canonical register/login handler,fill-in only)
  + `chain_executor.py`(同义词折叠 + 铸币步骤剥离自依赖 auth)。r25 死于 `/api/auth/signup` 401 livelock(108min)。

### C. 门禁可见性 / 收敛
- **#236** `hub_registry.py:get_validation_results`:从 `validation:<kind>:<target>` 的**名字**推导
  `metadata.check`/`flow`(#193 writer/reader 归一的另一半)。r26 死因:verifier 记了 35 条 SUCCESS ui_flow
  但 evidence 裸 → 门禁全盲 → 122min abort。
- **#237** `flow_coverage.py`:`_flow_key` 后缀归一(x / x_page / x_screen 同一 journey)→ required 集去重
  (r26: 31→23)+ 记录↔要求匹配用「passed wins」。
- **#238** `frontend_audit.py:dead_nav_link_blockers` + `deliverability.py` 接线 + `delivery_gate.py` token +
  `remediation_dispatcher.py` _GATE_OWNER:**死链门**——`<Link to=X>` 指向 App.jsx 不存在的路由 → 404。
  r27 交付的 app 里 Profile + Upload 按钮都 404。保守匹配(排除 catch-all/模板/外链),`ENVGEN_DEAD_NAV_GATE=0` 逃生。

### D. Build-break(框架自伤 / 幻觉)
- **#239** `frontend_audit.py:repair_fabricated_fallbacks`:#175 修复把 `x || 'lit'` 改成 `x ?? '—'`,若前面还有
  `||` 就制造出 `a || b ?? c`(JS 禁止 `??`/`||` 混用无括号)→ esbuild 拒绝 → build 崩。**框架自己的修复引入了
  build-break。** 修:替换永远加括号 `(x ?? '—')`。r29 死因。
- **#242** `backend_scaffold.py:sanitize_pyproject_local_deps`:lane 把 `_framework` 幻觉进后端依赖 →
  PEP-503 归一成 `-framework`(非法 PyPI 名)→ `pip install` 失败 → docker build 失败 → verification_checklist → abort。
  #189 只 strip 本地模块;#242 扩展为也 drop **非法 PEP-508 名**。r32 死因。

### ★E. ui_flow 交付天花板(本 session 最大成果)
- **#240 + #241**(`test_user_runner.py` + `heal_pipeline.py`):**r29/r30/r32 都在 `ui_flow_failed` 上受阻,
  但交付的 app 完全正常**(compose up + DOM 走查:真视频、真网格、零 fallback、零 console 错误、端点全 200)。
  这是**验证可靠性假阴性**,不是 app 质量问题。
  - **根因**:ui_flow 验证靠 **verifier LLM 手动点浏览器**。登出导航调 `/api/videos/feed` → 401 →
    框架注入的 `bc_auth.js` 执行 `location.assign('/login')`,**打断进行中的 `page.goto`**
    (报 "Navigation interrupted by another navigation")→ 认证步骤抛异常 → auth_ok=False →
    每个 flow 读成登录墙 → 工作正常的 app 被全记 failure。**框架自己的认证走查也中招。**
  - **#241 `_safe_goto`**:容忍这个导航竞态错误(重定向落到真页面 → 等 DOM 继续;其他错误照抛)。
    实测 auth_ok False→True。
  - **#240 `clean_ui_flow_passes`**:认证走查后对**干净渲染**的页面记录 `validation:ui_flow:<name>=passed`
    (PASS-only,需 auth_ok,只能解锁工作正常的 app,永不误伤),靠 #237「passed wins」压过 verifier LLM 假失败
    → ui_flow 门从可靠走查确定性清除。
  - **端到端在跑着的 r30/r32 上验证**:auth_ok=True、0 重定向、6-7/7 flow 记 PASS。

---

## 3. Run 战绩线（r25–r33,尸检素材都在 `gm_tiktok_r<N>.log` + `generated/tiktok-web-r<N>/shared/hubs/`）

| run | 结局 | 死因 / 备注 | 产出 |
|-----|------|------------|------|
| r25 | abort 108min | `/api/auth/signup` 401 livelock | #234 #235 |
| r26 | abort 122min | 35 条绿 ui_flow 对门禁不可见 | #236 #237 |
| **r27** | **交付 M1 1.0.0** | 史上第二次交付;M2 abort(register→username 404) | #238(runtime-verify 挖到死链) |
| r28 | abort 112min | verification_checklist(晚期编辑破坏 build)= **正确 fail-fast** | 无(非 bug) |
| r29 | abort | build-break `cur.title \|\| cur.desc ?? '—'` | #239 |
| r30 | abort(2 grace) | ui_flow_failed(工作正常的 app 被假阴性) | #240 #241(runtime 精确复现) |
| r31 | abort at KICKOFF | backend lane 1200s Gemini 停顿 = **环境性** | 无(重跑) |
| r32 | abort 76min | verification_checklist(`_framework` 幻觉依赖)+ business_chain | #242;#241 在干净 build 上确认 OK |
| r33 | **在跑** | 全栈 #219-#242 | 验证能否稳定交付 |

**方差观察**:每个 abort 死在**不同**的 endgame 检查(auth-synonym → flow-visibility → business-chain →
build-checklist → ui_flow → 幻觉依赖)。基础设施 bug 在逐个清除,残余方差 = 「app 能否在 75min+grace deadline
前建完 + 没有 lane 引入的 build-break/幻觉」。**ui_flow_failed 这个最顽固的复现天花板已被 #240/#241 移除。**

---

## 4. 交付后 runtime-verify 怎么做（必做,别被静态门骗）

1. run 完全退出后(`pgrep -f "python -m env_generator.llm_generator.main"` 为空)才 compose up。
   ⚠ pgrep 会匹配你自己的命令行(假阳性),用 `ps -ef | grep ... | grep -v grep` 确认。
2. `docker compose -f generated/tiktok-web-r<N>/docker/docker-compose.yml up -d --build`;
   **端口从 compose 读**(每 run 不同)。
3. dt python + playwright(chromium bundled):**register → 拿 token → `add_init_script` 预注入 token
   (关键!bc_auth 会在 401 时清 token,注入晚了会被弹 /login)→ 走全路由 → PROBE**:
   - `document.querySelectorAll('[data-fallback]').length` 必须 0;
   - 主路由渲染 seed 值(feed 应有视频);三栏 aside、`<video>`、按钮可点。
   - scratchpad 有样例 `verify_r27.py` / `probe_r30.py` / `val240.py`(框架走查 + clean_ui_flow_passes)。
4. 结果写进 memory;发现新缺口 = 下一个修复类。

---

## 5. 尸检套路（省几小时）

1. `grep -E "NO-CONVERGENCE|create_release|CONVERGING-GRACE|has [0-9]+ failed check" gm_tiktok_r<N>.log | tail`
   → 失败集 + deadline。
2. `generated/tiktok-web-r<N>/shared/hubs/*.json`:
   - `registryhub_verification_chains.json` → business_chain 的 broken 步骤;
   - `codehub_checks.json` → `build:*`(docker/backend/frontend/database)+ `validation:ui_flow:*` 状态/evidence;
   - `registryhub_endpoints.json` → 端点 auth/status/deprecated。
3. **对着跑着的 app 复现**(delicate 的 app-behavior bug 必须 compose up 实测,别只凭 log 猜):
   - build-break?`docker compose build frontend/backend 2>&1 | grep -iE "error|Cannot use|Transform failed"`;
   - auth/ui_flow?跑框架走查 `run_browser_test_user` + `clean_ui_flow_passes`(见 val240.py)。
4. **先本地 exec 取证再跑 90min run**:直接调生成器函数打真 run 的 hub json(#221/#226/#239/#242 都这么秒级验证)。

---

## 6. 现有已知问题 / 下一步目标（按优先级）

### ★ P0 — 交付稳定率(run-to-run 方差是最大敌人)
1. **`business_chain_failing`(硬编码 id / 字符串路径参数)** — 现在最可能的剩余交付天花板。
   - 症状:verifier authored `GET /api/users/13`(数字 id)但端点是 `/api/users/{username}`(字符串);
     或 `POST /api/videos/299/like`(299 非种子 id)。
   - 现状:`chain_executor.py:1332` 的**字面-id 恢复阶梯**(#136/#144)只覆盖**数字 id**
     (404 + 字面 `/\d+` → 同资源捕获 id → list 恢复 → seed_ids)。**对 `{username}`/`{handle}`/`{slug}`
     字符串参数无能为力**,且 GET 集合端点常不存在无法 list 恢复。
   - 方向:扩展恢复阶梯覆盖字符串参数(从 register 响应或 list 端点捕获真实 username/slug);
     或让 register 响应含 `username` 一等字段(env-touchy)。**先本地复现再改。**
2. **verifier endgame 串行瓶颈** — #232 只提前了 ui_flow 派发。考虑把 chains + checklist 也提前派发
   (同 #232 模式);或 required-flow 集瘦身(只 critical + 参考覆盖路由)。**注意:#228 grace 不该为坏 build
   续命(r28 是正确 fail-fast),别放宽 grace。**

### P1 — 视觉/交互精修(离"一模一样"的差距)
3. **bc_auth 匿名浏览 / requires_auth:false → 公开端点全映射**:登出用户访问 `/` 被 bc_auth 弹 /login
   (真 TikTok 可匿名看 For You feed)。`design_system.json` 的 screens 标了 `requires_auth`,应映射到端点
   `auth_required:false` + bc_auth 例外。**注意:bc_auth 的激进重定向是故意用来抓 gmrun4 登录墙的(#152 gate),
   软化有风险;交付的 app 本身正常(真用户登录后一切 OK),这主要是匿名浏览的 parity。**
4. 内容卡片真素材(封面/头像)映射(#227 只覆盖 nav 素材);登录态全交互 runtime 验证(点赞/评论/关注)。

### P2 — 泛化 / 反思优化
5. **换 env(youtube/outlook)跑同栈**,确认 #219-#242 无 tiktok 特化。
6. **工具面膨胀**(每 lane 48-75 个未 pin 到 stage 的工具 / ~206 次 MALFORMED_FUNCTION_CALL/run):
   `tool_surface.py` 的 stage-pinning 系统存在但大部分工具没 pin。per-stage 工具白名单是最高天花板但改动大、风险高,
   **别在刚拿下交付的时候贸然重构。**
7. **ui_flow 失败 evidence 是裸 `{flow:name}` 无原因** — 诊断缺口(remediation 不知道为啥 failed),但那是
   verifier-LLM 行为,难强制。

---

## 7. 铁律（不变）

- **env-agnostic**;每改动 **TDD**(`agent/tests/` gitignored,**永不提交**)。
- **key 只在 `/tmp/envgen_key.sh`**;永不进仓库/log/handoff。
- **push 用默认 SSH key → vaibackup**(同时更新 `feat/pipeline-opt-6` + PR 分支 `pipeline-opt6-tiktok-delivery-186-205`);
  **不加 Co-Authored-By**;**用户 merge PR**。
- **两 run 不并发**;**run 活着不 docker up/down**;**每 run 端口不同**(读 compose)。
- **最终必须 runtime-verify 交付的 app,不能被静态门骗过**;delicate 的 app-behavior bug 必须对着跑着的 app 修。
- baseline 对比用 **worktree** 不用 stash(stash + 超时差点丢改动的教训)。

---

## 8. PR 说明(gh 未认证,需网页建 PR)

- 分支已推:`feat/pipeline-opt-6` 和 `pipeline-opt6-tiktok-delivery-186-205`(都指向 HEAD `9dc7a2b` + 本 handoff)。
- **建 PR**:`https://github.com/vaibackup/forgingground-gen/compare/main...pipeline-opt6-tiktok-delivery-186-205?expand=1`
- PR 标题:`pipeline-opt-6: delivery stability — #219-#242 (zero-fallback → 2nd delivery → ui_flow ceiling removed + 2 build-break classes)`
- **用户 merge**。

---

## 9. 下一个 session 启动指令(复制粘贴)

```
/loop 持续优化，提升整个pipeline能力，最终生成完美的app，包括视觉和功能完备，包括agent的memory啊，
整个pipeline agent的tool导致的问题啊，stage划分问题啊，之类的，agent prompt之类的，各种gate等等，
仔细在生成环境的过程中，反思，优化

先读 forgingground-gen/HANDOFF_2026-07-20_delivery_stability.md 和 memory
project_envgen_frontend_zero_fallback_findings，再查最近 run 结局(交付→runtime-verify §4;abort→尸检 §5)，
从 §6 backlog 按优先级实施，每改动 TDD+live 验证，每次 run 前 df -h /。
铁律见 §7。
```
