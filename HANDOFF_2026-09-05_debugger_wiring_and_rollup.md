# HANDOFF 2026-09-05 — debugger lane 接线 (#1202dr) + tool-io 账本周期化 (#1202dq)

分支 `feat/netflix-generality-366-367`,基于 `31b4379c #1202cy…dd`。
本文档面向下一个 session,可直接照做。

---

## 0. 一句话状态

三个框架缺陷已定位并修好(`#1202dq`/`#1202dr`/`#1202dp`),**全套 14781 passed / 0 failed**、
端到端链路经反证验证;
**行为层面未验证**(需要一个完整 run);r44 正在跑,还有余量;
两件事等用户决定:docker 清理、是否提交。

---

## 1. 先读这段:关于 `--resume` 的一个流传中的错误结论

有一份分析称「resume 后 agent 对话不接续,靠磁盘账本恢复」。
**结论对,但三条支撑证据全是错的**,不要照抄它的方法。

### 对的部分(源码层面定死,不用推断)

- `step_runner.py:127` `messages = [Message.system(...), Message.user(...)]`
  —— **局部变量**,每次进 `run_agentic_loop` 现造,无任何磁盘恢复分支。
- 全树 `grep -rE "(json\.dump|write_text|pickle\.dump).*(messages|Message)"` → **零命中**。
- `hub_registry.py:241` 注释:`--resume` constructs a fresh Orchestrator → fresh generation_id。
- `.checkpoint` 只有 phase 级字段(`current_phase`/`resume_count`/`status`),与对话无关。

### 错的三条(别用)

| 流传的证据 | 实测 | 为什么错 |
|---|---|---|
| 「messages 从 5 重新长起」 | 原始 run `messages<=10` 出现 **259/2426 (10.7%)**;resume **263/2055 (12.8%)** | 每个新任务都会把 messages 重置到 2。拿"原始尾"对"resume 头"= 拿任务中段对任务开头 |
| 「resume 后调用特别密集」 | 各取前 3000 行:`workhub_list_tasks` 61 vs 原始 **69**;`check_inbox` 50 vs **45** | **原始 run 的开头也是冷启动** |
| 「project_brief.md 停在 kickoff 时刻证明接上了」 | debugger 的 6 个文件全停在 11:33 | 那三个是 kickoff 写一次的静态文件,没 resume 也不变 |

### 被漏掉的关键机制

`step_runner.py:133-148`:**memory-bank digest 是框架在每个任务开始时确定性注入的**,
直接 append 进 messages,不花 LLM round-trip(2026-06-09 替换掉旧的 `retrieve_context` 阶段)。
数据吻合:`read_memory_bank` 72 次 vs `update_memory_bank` 192 次,**写多于读**。

**推论**:「check_inbox 占 46.7% 上下文不能动,因为它是 resume 重建上下文的通道」——
**这个豁免理由是编的**,无数据支持。它的开销该按自身收益评估。

---

## 2. #1202dr — 整条 debugger lane 从来醒不过来 ★本轮最大发现

### 判据

`grep -c bug_found agent/env_generator/llm_generator/multi_agent/agents/runtime/messaging.py` = **0**

`bug_found` / `run_failed` 是 `DEFAULT_SUBSCRIPTIONS["debugger"]` 里它**仅有的**两个工作触发器
(订阅表第 143 行自述:"Wakes on bug_found + runhub failures")。消息被 `get_if_urgent()`
弹出(priority `high` = rank 1,在 `<=1` 排空范围内),匹配不到任何 `msg_type ==` 分支,
落到分派表末尾的裸 `return False` —— **消费掉并丢弃**,不重排队、不记日志。

### 每一层都报成功(与 SPA 静默 200 同型)

| 层 | 报告 | 真相 |
|---|---|---|
| #628 寻址 | `recipients=['debugger']` **17/18** | ✅ 真修好了 |
| bridge 投递 | inbox 38 条全 `delivered=True` | ✅ 真推上总线(`mark_delivered` 在成功分支内) |
| 常驻排空 | 两个 run 都有 `[debugger] Ready to accept tasks` | ✅ `run_loop` 真在跑 |
| **实际干活** | `run_agentic_loop ENTER` = **0** | ❌ 3.2 小时零轮 |

对照(r44 resume):backend 58 / orchestrator 55 / frontend 25 / verifier 12 / **debugger 0**。

**陪葬品**:`task_a40620a46a` "Docker compose startup fails: backend container missing",
`assignee=debugger`、`claimed_by=None`、**`status=cancelled`** —— 阻塞发布的任务
路由给了一条叫不醒的 lane,然后被取消。

### 同一缺陷类修过一次

`messaging.py:649-655` Round-8c 注释原话:
> the kickoff_request urgent event was being received and logged but no msg_type branch
> below dispatched into an LLM turn, so the 4 attendees just sat idle

`bug_found` 是漏网的那半。

### 改动

`messaging.py`:
1. 分派分支 `if msg_type in ("bug_found", "run_failed"):`
2. `_handle_bug_triage()` —— 三个刻意选择:
   - **忙则跳过,不排队**:排队会重建 kickoff 注释里记的 livelock;嵌套会踩 V30 再入守卫。
     WorkHub 任务是真相源(bug_tools:"the bug task is the source of truth"),丢唤醒不丢 bug。
   - **prompt 以 `bug_list_open` 开头**做批处理:一串 N 个事件只花一轮,被跳过的唤醒下轮照样看得到。
   - **保留 fallthrough**:不让分派表变成 catch-all(有测试锁这条)。

### 主动回退的一处

曾把 debugger 的 `run_completed`/`kickoff_complete` 移进 `INBOX_ONLY_SUBSCRIPTIONS`
(它们自述 informational 且无分支)。**已回退** —— `test_agent_subscriptions` 和
`test_kickoff_orchestrator_wire` 都断言它们必须在 `DEFAULT_SUBSCRIPTIONS`,
后者 docstring 记的正是同一缺陷类(`knowledge` lane 被唤醒却无 handler,最后整条 lane 被删)。
**两个测试编码的契约不该凭静态阅读翻。** 改为在绊线里显式登记为例外。
→ 如果下一个 session 想动它,先跑真 run 证明再说。

---

## 3. #1202dq — 出事的 run 不留上下文账本

`tool_io_rollup()` 是"哪个工具撑大了 prompt"的权威账本(#257 建,#679 据此瞄准),
但只在 orchestrator 的 `finally` 里打**一次**。**SIGKILL 不走 finally。**

实测 netflix 语料 12 个 run 日志,**4 个零 rollup**(r41 / r43b / r44 / r44-resume)= 33%。
r44 原始 run 就是这样死的:OpenAI 额度耗尽(37 次 `no credits remaining`,13:08:57),没留下账。
**出问题最值得诊断的 run,恰恰是丢诊断的那些。**

**改动**:挂到 `_budget_ticker_1175`(每 30s 一跳,与 lane 状态无关)+ 15 分钟节流
(`ENVGEN_TOOLIO_ROLLUP_MIN`,`<=0` 关闭);退出路径改走同一 helper 加 `force=True`。
header 字符串**刻意不变**,历史语料的 `grep '[tool-io] TOTAL'` 照样匹配。

顺带把 `test_1175` 一个脆断言改硬:原本 `b.index("CancelledError") < b.index("except Exception")`,
我插入的同步 try 让它红了。**确认意图没被破坏**(`CancelledError` 继承 `BaseException`,
且新增的 try 里没有 await)后改成走 AST,只检查真的包着 `await` 的 try —— 比原来强。

---

## 4. 全 lane 订阅审计 —— 25 个死触发器,但只有 1 个致命

对 5 条 lane 做"live 订阅 vs 分派表有分支"审计:

```
orchestrator  11    inbox 559/559 已读 (100%)
frontend       5          420/420
backend        4          206/209
verifier       3          111/111
debugger       2(+已修2)     0/41    ← 唯一真受害者
```

**判据不是"有没有分支",是"这条 lane 除被唤醒之外还有没有别的激活路径"。**
有持续循环的 lane 靠 hub_pulse 全兜住,缺分支只是**唤醒延迟**,信息没丢
(`task_completed` 288 次、`task_cancelled` 57 次都被读掉了)。把 25 个都报成 bug 是灌水。

---

## 5. 方法论:三次已知答案反证,抓到我自己两个空过的检测器

**每条静态审计都要配一个"把缺陷删回去必须变红"的反证,否则绿色毫无信息量。**

1. **锚点误匹配**:`subs.index("INBOX_ONLY_SUBSCRIPTIONS")` 命中的是 **DEFAULT 块内部一句注释**
   ("moved to INBOX_ONLY_SUBSCRIPTIONS below"),把 DEFAULT 后半段整个吞成 inbox_only
   → 第一版审计报 10(实为 25),且绊线**空过**(断言循环一次没跑)。
   修:行首锚点 `re.search(rf"^{name}[^=]*=\s*\{{", src, re.M)`。
2. **子串 vs 构造**:修好锚点后反证仍不响 —— 检测用**子串**判"有没有分支",
   而我自己写的注释里 `bug_found` 出现 6 次。又是"匹到文本出现该词而非该事发生"。
   修:解析 `msg_type == "X"` / `msg_type in (...)` 构造。
3. **e2e 反证**:拆掉分支 → 2 failed / 3 passed(红的正是断言 triage 启动的两条,
   投递/队列/durable inbox 三条照常绿 = 失败定位精确),复原 → 5 passed,文件字节还原。

---

## 6. 测试

**全套:14781 passed / 105 skipped / 0 failed / 707s,零回归。**

⚠ 这个数字来之不易,**前三次全套结果全部作废**(20 / 3 / 32 failed,失败集合两两**交集为零**)
—— 因为全程有**另一个 session 的套件在同一工作树上并发跑**,争抢临时路径与测试写入的文件。
非确定性失败集合就是这个的特征。教训:**跑全套前必须确认独占**,否则任何"对照实验"都无意义。

⚠ 我用来等待独占的 `pgrep -f "pytest tests/"` **会匹到承载它自己的 bash**(wrapper 的 cmdline
含整段脚本文本),导致白等满 45 分钟。`pgrep -f "bin/python.*pytest"` 有同样问题。正确写法按
comm 过滤掉 shell:

```bash
pgrep -f pytest | while read p; do
  [ "$(ps -o comm= -p $p 2>/dev/null)" = "python" ] && echo $p
done | wc -l
```

| 文件 | 内容 | git |
|---|---|---|
| `agent/tests/test_tool_io_rollup_survives_a_kill_1202dq.py` | 13 tests,节流/force/永不抛/header 契约/接线 | **local-only** |
| `agent/tests/test_debugger_bug_found_is_dispatched_1202dr.py` | 13 tests,含自动覆盖新订阅的绊线 + 反证 | **local-only** |
| `agent/tests/test_bug_found_reaches_the_debugger_e2e_1202dr.py` | 5 tests,真 EventHub→bridge→queue→分派 | **local-only** |
| `agent/tests/test_1175_budget_record_refreshes_on_a_clock.py` | 脆断言改 AST | tracked(M) |

> ⚠ **`.gitignore:38` 忽略 `/agent/tests/`** —— 三个新测试文件**不会随代码提交**。
> 这是本仓库既定的 local-only 惯例(见 memory `project_forgingground_gen_repo_hygiene`),
> 但意味着接手的机器上没有它们。需要的话让用户决定是否 `git add -f`。

跑法(**优先用带锁的包装**,见下;裸命令见 `pyproject:35`):

```bash
scripts/suite.sh                 # 独占,别人在跑就拒绝启动
SUITE_WAIT=1 scripts/suite.sh    # 排队
```

裸命令:
```bash
cd /data/common/haibotong/forgingground-gen/agent
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest tests/ -q
```
⚠ **不要和 live run 并跑**(I/O 争用,曾出现 151s 只跑 2%)。

---

## 7. 未完成 / 待决定

1. **行为层面未验证** —— debugger 醒来之后 triage 得好不好,只有完整 run 能答。
   验证信号:新 run 的日志里应出现 `[debugger] run_agentic_loop ENTER`
   和 `[debugger] Handling bug_found — opening a triage loop`。
2. ~~全套测试未跑~~ —— **已跑,独占,0 failed**(见上)。
3. **docker 清理(等用户)**:根分区 100% 满。
   `docker system df` 显示可回收 ≈135GB(镜像 97.97GB / 卷 35.95GB / 容器 1.88GB)。
   **根分区的 1.2T 是 `/home` 下别的用户的**(huichen 231G、jingliu 110G…),不是本项目的,不该动。
   卷里是用户各 env 的持久化数据,`--volumes` 必须用户确认。
4. **是否提交(等用户)**:14 个改动文件 / +675 −16。

---

## 8. r44 结局:**没有交付**,$320.50 烧完退出 1

```
$320.50   tick 56/200   127/180 min   rc=1   passed=False  released=False
```

**死因链(15:41:41 → 15:41:46,五秒)**:

```
15:41:41  GATE-CHECK remediation dispatched to backend (task_c448404c80):
          business_response_key_noncanonical               ← 刚派出修复
15:41:42  Project phase: implement -> test
15:41:44  Final delivery gate failed on FIRST evaluation
          (['validation_ui_evidence_failed', 'business_response_key_noncanonical'])
15:41:46  [E] Generation failed: Delivery gate failed.
15:44:04  [main-exit] main() returned 1 → shutdown watchdog forcing exit
```

关键:**它不是收敛失败,是收敛到一半被打断**。
- 剩 **53/180 分钟**墙钟、**144/200** tick 未用
- 视觉分**还在上升**:中位 0.465 → **0.610**,过线屏 3 → **4/12**
  (login 0.83 / genre_category 0.78 / browse_home 0.72 / landing 0.66)
- 两个阻塞项**都有 owner 且在飞行中**:`business_response_key_noncanonical`→backend
  5 秒前刚派;`validation_ui_evidence_failed`→verifier,`task_d117dab4a9` in_progress

⚠ 关机看门狗(`main.py:600`)**不是死因** —— 它是 `finally` 里的清理保险,只在 `main()`
已返回后 ≤120s 强退。`rc=1` 说明 `main()` 自己返回了 1。

⚠ 另一个口径提醒:我一度用 `grep -c 'DELIVER\|...'` 得到 "delivered: 25",**是误报**。
判交付要看 `passed`/`released` 和是否有 release,别用宽 grep。

### → #1202dp(本轮第三个修复)

`orchestrator.py:2901` 的 `raise RuntimeError("Delivery gate failed.")` 是**无条件硬抛**。
它前面有三条逃生通道,各覆盖一个窄类别,**没有一条覆盖"阻塞项有主、刚派活、预算还剩"**:

| 通道 | 条件 | r44 为何不命中 |
|---|---|---|
| 就绪重试 | 等后端起来再读一次 | 只重读,不给修复时间 |
| #139 漂移豁免 | `_milestone_gate_cleared_at` 新鲜 | 视觉走逃生路径时从不打戳 |
| #553 收敛重跑 | 阻塞项 ⊆ {business_chain_failing, verification_checklist_not_ready} | 两项都不在集合里 |

**修法**:抛出前加**有界宽限** —— 每轮等 `ENVGEN_FINAL_GATE_GRACE_S`(默认 120s)
再重评,最多 `ENVGEN_FINAL_GATE_GRACE_ROUNDS`(默认 3)轮,三重上界:
轮数 / 墙钟余量(必须留 60s 尾) / `_grace_s > 0` 可整体关闭。

★ **判据复用 #1040 的 wedge 计数器**而不是再抄一份 owner 表:
`_gatecheck_wedged_ticks_1040 == 0` 就是"确实有东西被派出去了"这个问题的既有答案。
非零 = 没有任何失败项有主(r174 那种死端),等下去毫无意义 → 照旧立即抛。
计数器**每轮重读**,中途变成 wedge 就停。

★★ **这个改动不可能造成错误交付**:它从不给 `gate["ok"]` 赋值(有测试锁死这条)、
不碰任何逃生路径,交付仍然必须门禁**自己**通过。最坏情况只是一个注定失败的 run
多花掉本已分配给它的预算,然后以今天完全相同的方式失败。

测试 `agent/tests/test_final_gate_waits_for_inflight_remediation_1202dp.py`(14 个,
**local-only**),含反证:移除 grace → 8 红,复原 → 14 绿。

## 9. 改动文件

```
messaging.py    +76   #1202dr 分派分支 + _handle_bug_triage
tooling.py      +42   #1202dq maybe_tool_io_rollup
orchestrator.py +13   #1202dq 挂 ticker + 退出路径改走 helper
test_1175...py  +41   脆断言改 AST
```
(其余 10 个文件是本会话早先 #1202cr–dd 的未提交改动,已随 `31b4379c` 之后继续累积。)
