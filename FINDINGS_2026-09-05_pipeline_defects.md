# FINDINGS 2026-09-05 — 本轮查出的问题清单

分支 `feat/netflix-generality-366-367`,基于 `31b4379c`。证据全部来自 netflix **r44**
(原始 run 11:33–13:08,resume 13:34–15:44,共 $320.50)。

配套的实施细节见 `HANDOFF_2026-09-05_debugger_wiring_and_rollup.md`。
本文只回答一件事:**发现了什么问题,现在是什么状态。**

---

## 速查表

| # | 问题 | 严重度 | 状态 |
|---|---|---|---|
| 1 | debugger lane 三小时零轮,17 份 bug 报告落地即丢 | ★★★ | 已修 `#1202dr`,**行为层已在 resume2 验证** |
| 2 | 最终门禁在修复飞行中硬抛,烧掉 r44 | ★★★ | 已修 `#1202dp`,**行为层未验** |
| 3 | 出事的 run 不留上下文账本(33% 的 run) | ★★ | 已修 `#1202dq` |
| 4 | 票号 `#1202de`/`#1202df` 被我重复占用 | ★ | 已修(重编为 dn/do) |
| 5 | 25 个死触发器(订阅了但分派表无分支) | ☆ | 已量化,**24 个是延迟非丢失,故意不修** |
| 6 | debugger 两个 live 订阅无分支,但两个测试锁着契约 | ☆ | **未修,故意**;绊线里显式登记为例外 |
| 7 | `check_inbox` 豁免理由是编的,但成本已降 98% | ☆ | **降级**:很可能已不值得动 |
| — | 三条被证伪的怀疑(见 §8) | — | 无需动作 |
| 8b | 两个 session 共用工作树 → 全套结果全部作废 | ★★ | 已定位,**建议加锁需人拍板** |

---

## 1. ★★★ debugger lane 从来醒不过来 → `#1202dr`

**判据一行**:`grep -c bug_found messaging.py` = **0**

`bug_found` / `run_failed` 是 `DEFAULT_SUBSCRIPTIONS["debugger"]` 里它**仅有的**两个工作
触发器(订阅表自述 "Wakes on bug_found + runhub failures")。消息被 `get_if_urgent()` 弹出
(priority `high` = rank 1,在 `<=1` 排空范围内),匹配不到任何 `msg_type ==` 分支,落到分派表
末尾的裸 `return False` —— **消费掉并丢弃**,不重排队、不记日志。

**每一层都报成功**(和 SPA 静默返回 200 同型):

| 层 | 报告 | 真相 |
|---|---|---|
| #628 寻址 | `recipients=['debugger']` 17/18 | ✅ 真修好了 |
| bridge 投递 | inbox 38 条全 `delivered=True` | ✅ 真推上总线 |
| 常驻排空 | 两个 run 都有 `Ready to accept tasks` | ✅ `run_loop` 真在跑 |
| **实际干活** | `run_agentic_loop ENTER` = **0** | ❌ 3.2 小时零轮 |

对照:backend 58 / orchestrator 55 / frontend 25 / verifier 12 / **debugger 0**。

**陪葬品**:`task_a40620a46a` "Docker compose startup fails: backend container missing",
`assignee=debugger`、`claimed_by=None`、**`status=cancelled`**。

**同类缺陷 Round-8c 为 `kickoff_request` 修过一次**(注释:"received and logged but no
msg_type branch dispatched into an LLM turn, so the 4 attendees just sat idle")。

**修法**:加分派分支 + `_handle_bug_triage`。忙则跳过不排队(排队会重建 kickoff 注释记录的
livelock,嵌套会踩 V30 再入守卫);prompt 以 `bug_list_open` 开头做批处理,N 个事件只花一轮
且跳过的唤醒不丢 bug;保留 fallthrough 不让分派表变 catch-all。

**验证状态**:13 单测 + 5 个端到端(真 EventHub→bridge→PriorityQueue→分派),反证有效
(拆掉分支 → 2 红)。**行为层未验** —— 需要新 run,信号是日志出现
`[debugger] Handling bug_found — opening a triage loop`。

---

## 2. ★★★ 最终门禁在修复飞行中硬抛 → `#1202dp`

**r44 的死因链,总共 5 秒**:

```
15:41:41  GATE-CHECK remediation dispatched to backend (task_c448404c80):
          business_response_key_noncanonical              ← 刚派出修复
15:41:42  Project phase: implement -> test
15:41:44  Final delivery gate failed on FIRST evaluation
          (['validation_ui_evidence_failed', 'business_response_key_noncanonical'])
15:41:46  [E] Generation failed: Delivery gate failed.
15:44:04  [main-exit] main() returned 1
```

**它不是收敛失败,是收敛到一半被打断**:

- 剩 **53/180 分钟**墙钟、**144/200** tick 未用,$320.50 已花
- 视觉分**还在上升**:中位 0.465 → **0.610**,过线屏 3 → **4/12**
  (login 0.83 / genre_category 0.78 / browse_home 0.72 / landing 0.66)
- 两个阻塞项**都有 owner 且在飞行中**:backend 5 秒前刚接活;
  verifier 的 `task_d117dab4a9` 还 `in_progress`

`orchestrator.py:2901` 是**无条件硬抛**。前面三条逃生通道各覆盖一个窄类别,
**没有一条覆盖"有主 + 刚派活 + 还有预算"**:

| 通道 | 条件 | r44 为何不命中 |
|---|---|---|
| 就绪重试 | 等后端起来重读一次 | 只重读,不给修复时间 |
| #139 漂移豁免 | `_milestone_gate_cleared_at` 新鲜 | 视觉走逃生路径时从不打戳 |
| #553 收敛重跑 | 阻塞项 ⊆ {business_chain_failing, verification_checklist_not_ready} | 两项都不在集合里 |

**修法**:抛出前加有界宽限,三重上界(轮数默认 3 / 墙钟须留 60s 尾 / `_grace_s>0` 可整体关闭)。
判据**复用 #1040 的 wedge 计数器**而非再抄一份 owner 表 —— `_gatecheck_wedged_ticks_1040 == 0`
本就是"到底有没有东西被派出去"的既有答案;非零 = r174 那种无主死端,等下去无意义,照旧立即抛。
计数器**每轮重读**,中途变 wedge 就停。

★★ **该改动不可能造成错误交付**:从不给 `gate["ok"]` 赋值(有测试锁死)、不碰任何逃生路径,
交付仍必须门禁自己通过。最坏情况只是注定失败的 run 多花掉本已分配的预算,然后以今天完全
相同的方式失败。

**验证状态**:14 测试,反证有效(移除 grace → 8 红)。**行为层未验**。

⚠ **关机看门狗不是死因** —— `main.py:600` 那个是 `finally` 里的清理保险,只在 `main()`
已返回后 ≤120s 强退;`rc=1` 说明 `main()` 自己返回了 1。别顺着看门狗查。

---

## 3. ★★ 出事的 run 不留上下文账本 → `#1202dq`

`tool_io_rollup()` 是"哪个工具撑大了 prompt"的权威账本(#257 建,#679 据此瞄准),
只在 orchestrator 的 `finally` 里打**一次**。**SIGKILL 不走 finally。**

实测 12 个 netflix run 日志,**4 个零 rollup**(r41 / r43b / r44 / r44-resume)= **33%**。
r44 原始 run 就是这么死的:OpenAI 额度耗尽(37 次 `no credits remaining`,13:08:57)。
**出问题最值得诊断的 run,恰恰是丢诊断的那些。**

**修法**:挂 `_budget_ticker_1175`(30s 一跳,与 lane 状态无关)+ 15 分钟节流
(`ENVGEN_TOOLIO_ROLLUP_MIN`,`<=0` 关闭);退出路径改走同一 helper 加 `force=True`。
header 字符串**刻意不变**,历史语料的 `grep '[tool-io] TOTAL'` 照样匹配。

---

## 4. ★ 票号冲突,**撞了两次**(我造成的)

上下文重置后我挑号,连续两次撞上本会话早段已占用的号 —— 两次都是**检测器只匹配了一种表示**:

| 轮次 | 我挑的 | 已被谁占 | 我的检测器漏在哪 |
|---|---|---|---|
| 第一次 | `#1202de` / `#1202df` | de="host fault is not an app verdict";df="the remediation that lived past the cap" | 只查了 `git log -S`,而这批号**全部只存在于工作区**,历史里查不到 |
| 第二次 | `#1202dn` / `#1202dr`(原 do) | dn=`delivery_gate.py`+`test_1202dn_a_js_fragment_is_not_an_endpoint.py`;do=`frontend_scaffold.py`+`test_1202do_the_401_guard_must_not_hand_back_a_body.py` | 只 grep 了**文件内容里带井号的** `#1202d[a-z]`,漏了**编码在文件名里**的票号 |

**最终落位**:`#1202dq`(rollup 周期化)/ `#1202dr`(debugger 接线)/ `#1202dp`(最终门禁宽限,
只有我一个,无冲突)。

**下一个 session 挑号前跑这个** —— 必须同时覆盖文件名和内容,且不能依赖 git 历史:

```bash
{ grep -rhoE "1202[a-z]{1,3}" --include='*.py' agent/
  ls agent/tests/ | grep -ohE "1202[a-z]{1,3}"
  grep -rhoE "1202[a-z]{1,3}" *.md 2>/dev/null
} | sort -u | tail -20
```
当前 d 段已用到 `dr`,下一个空号是 `ds`。

## 5. ☆ 25 个死触发器 —— 但只有 1 个致命,其余**故意不修**

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

## 6. ☆ debugger 的 `run_completed` / `kickoff_complete`:**未修,故意**

两者是 live 订阅但分派表无分支。它们的源码注释自述 informational
(`kickoff_complete` 原话就是 "is informational"),按理该进 `INBOX_ONLY_SUBSCRIPTIONS`。

**我改了又回退了**:`test_agent_subscriptions` 和 `test_kickoff_orchestrator_wire`
都断言它们**必须**在 `DEFAULT_SUBSCRIPTIONS`,后者 docstring 记录的正是同一缺陷类
(`knowledge` lane 被唤醒却无 handler,最后整条 lane 被 #1202ch 删掉)。

**两个测试编码的契约不该凭一次静态阅读翻。** 想动它先跑真 run 证明。
成本很低:r44 全程 `run_completed` 4 次、`kickoff_complete` 1 次。
绊线里已显式登记为例外,新增订阅照样会被抓。

---

## 7. ☆ `check_inbox` —— 豁免理由确实是编的,但成本本身已经塌了(**降级**)

**两件事要分开说。**

### (a) 那条豁免理由是编的 —— 这点成立

流传的说法是「inbox 是 `--resume` 后重建上下文的主通道,截断风险大」。**没有数据支持**:
resume 后的调用密度和冷启动一样(前 3000 行:`check_inbox` 50 次 vs 原始 run 开头的 45 次)。
真正确定性重建上下文的是 `step_runner.py:133-148` —— **框架在每个任务开始时强制注入
memory-bank digest**,不花 LLM round-trip,agent 没得选。调用数吻合:`read_memory_bank` 72 次
vs `update_memory_bank` 192 次,**写多于读**,因为读是自动的。

### (b) 但 46.7% 这个数字已经过期 —— **成本降了 98%**

★ **不需要跑 run 就能测**:拿 r44 的真实 eventhub 台账 + 当前代码路径直接算返回体大小
(每 lane 取最大的 10 条,即默认 `limit=10`):

```
lane            items   已读%      全量返回     #302生效后    省下
orchestrator      500   100%       24,576        2,400     91%
backend           277    87%      144,650        6,800     96%
frontend          440    96%      407,404        2,400    100%
verifier          177    93%      151,095        2,400     99%
debugger           50   100%        2,730        2,360     14%
──────────────────────────────────────────────────────────────
合计(单次调用)             732,781       18,686     98%
```

原因:`#302` 把已读消息截到 `_INBOX_PREVIEW_LEN = 240`,而 **`#604` 修好了那个一直读错位置的
`read` 标志**(它读 event 而非 per-agent 指针,12910/12910 个事件都没有顶层 `read` 键,所以
预览从未对 durable 消息生效过)。现在活跃 lane 的 inbox **87%–100% 是已读**,预览分支几乎全程命中。

**因此第 7 条从「★★ 高危未修」降级为「☆ 很可能已不值得动」。** 46.7% 是 `#604` **之前**测的;
#679 当时算的"还剩 ~129M 没碰"几乎肯定失效。剩下的量级不足以支撑碰 `#274` 那条红线
(省必须来自**发送端**摘要 + hub 指针,绝不许读时截断——曾有 `[:500]` 让接收方看不到
task_ready 契约、也问不到剩下部分,直接卡死流水线)。

**下最终结论仍需一份当代 tool-io 表**确认真实占比 —— 那正是 §3 (`#1202dq`) 修好的东西。

★ 附带一个信号:`debugger` 那行只省 14%,因为它的 50 条消息**全是短通知**(2730 字符 / 50 条)
—— 它从来没干过活。修好 `#1202dr` 之后它开始 triage,inbox 才会装进真正的工作上下文。

## 8. 三条**被证伪**的怀疑(记下来免得下一个 session 重查)

| 怀疑 | 实测 | 结论 |
|---|---|---|
| `filtered[:limit]` 无排序会埋掉未读消息 | 活跃 lane **0 条被埋**;`list_inbox` 是 newest-first | 否 |
| `deliverability_ui_page_unwired` 是无出口终态 | 15:03→15:13 **自愈清除**;`#1040 WEDGED` 开火 0 次 | 否 |
| `validation_ui_evidence_failed` 无主(r174 同款) | 有 owner,15:18:35 实时派给 verifier,`#794` 去重也在工作 | 否 |

另外 `unreachable_refunds` 也**不是**缺陷:两次退款都在**原始 r44**(12:50),
原因是 compose race;`#1202dm` 的专用预算是**未提交的工作区代码**,原始 run 起跑时还没有,
resume 段就是 0。**查这类问题必须做时间切片。**

---

## 8b. ★★ 两个 session 共用一个工作树 —— 今天最大的时间浪费

**症状**:全套测试跑了三次,`20 / 3 / 32` failed,**失败集合两两交集为零**,三次都失败的为 0。

**真因**:全程有另一个 session 的 `pytest tests/` 在**同一个工作树**上并发跑
(PID 1954079,shell snapshot `1788624151380`,不是本 session 的),争抢临时路径、
测试写入的仓库文件和 CPU。等它跑完再独占跑一次:**14781 passed / 0 failed**。

**代价**:我基于这三个污染数字做了 4 轮错误归因(先说"18 个与我无关",再说"20 个全是我的
测试文件造成的"),两条都撤回了。★ **验证的范围必须覆盖变化的范围** —— 我 40 分钟前就发现
了那个并发套件、还写进了报告,却没把它当成实验变量控制住。

**同源的第二笔代价**:两个 session 从同一个票号序列取号,造成三次撞号(见 §4)。

**已落地的工具(2026-09-05,可直接用)**:

```bash
scripts/suite.sh                 # 独占跑套件;别人持锁时拒绝启动并报出 pid/session/起始时间
SUITE_WAIT=1 scripts/suite.sh    # 排队等锁
scripts/next_ticket.sh           # 已用票号 + 下一个空号(查文件名 + 内容,不依赖 git 历史)
scripts/next_ticket.sh --all     # 列出全部已用
```

`.suite.lock` / `.suite.lock.info` 已加进 `.gitignore`。取号**按号段**而不是单个号,并写进交接文档。

★ **撞号是双向的,不是我单方面的疏忽**:`delivery_gate.py:1970` 留着另一个 session 的注释
——`# #1202ds (renumbered from #1202dp: a concurrent session shipped a different …`
它原本也用 `#1202dp`,发现被我占了才让开。**两边都在盲取同一个序列。**

**仍需人拍板的部分**:锁只有两边都用才有意义,得有人去同步另一个 session。

**建议(需要人拍板,因为锁只有两边都用才有意义)**:
- 仓库根 `.suite.lock`(`flock` + 写 PID/session/起始时间),跑全套前取锁,取不到就报谁在跑
- 票号**按 session 预分配号段**(如本 session 只用 `dq`–`dz`),而不是每次现挑

⚠ **等待独占的循环有个坑**:`pgrep -f "pytest tests/"` 会匹到承载它自己的 bash
(wrapper 的 cmdline 含整段脚本文本),我因此白等满 45 分钟。
`pgrep -f "bin/python.*pytest"` 同样会自匹配。按 comm 过滤才对:

```bash
pgrep -f pytest | while read p; do
  [ "$(ps -o comm= -p $p 2>/dev/null)" = "python" ] && echo $p
done | wc -l
```

（同一个坑的另一面见记忆 `pkill -f 会匹配承载它的 shell 自杀`。）

## 8c. ★★★ 行为验证已经拿到了 —— 而且不是靠新起一个 run

**我全程都在说"三个修复的行为层只能靠一个新的 $300 run 来验",这是错的。**

另一个 session 在 **16:33 第二次续跑了 r44**(`netflix-r44-resume2.log`,16:33–16:54)。
那时我的修复已经落到磁盘上,于是它**自动加载了**。我一直在等一件已经发生的事。

★ 由此得到一条对下一个 session 有用的事实:**`--resume` 加载的是当前磁盘上的代码**,
不是起跑时的快照。所以修完框架后,**续跑一个已有的 run 就能验行为,不必从零付一次全款**。

### `#1202dr` — debugger 真的醒了,而且三个设计选择全部被印证

```
16:45:36  [debugger] Handling bug_found — opening a triage loop:
          {'task_id': 'task_0879fcb6cc', 'severity': 'P1', 'title': 'GET /api/title…'}
16:45:36  [debugger] run_agentic_loop ENTER (depth=1, max_steps=30)
16:45:37  [debugger] bug_found while busy (…PROCESSING_TASK); skipping the wakeup
16:45:37  [debugger] bug_found while busy …          ← 一秒内 3 条被合并进同一轮
16:45:37  [debugger] bug_found while busy …
16:46:10  [debugger] Tool calls: check_inbox(limit,clear), bug_list_open()
16:46:14  [debugger] 🔧 bug_list_open: args=[]
```

| 设计选择 | 实证 |
|---|---|
| 忙则跳过、不排队 | 3 条并发事件合并进一轮,无嵌套(V30 守卫未触发)、无 livelock |
| prompt 以 `bug_list_open` 开头 | agent 真的先调了它 —— **被跳过的 3 条一条没丢** |
| 批处理而非逐条 | N 个事件 = 1 轮循环 |

`ENTER` 计数:orchestrator 15 / verifier 6 / backend 4 / frontend 3 / **debugger 2**
(此前 3.2 小时是 **0**)。

### `#1202dq` — 周期发射生效

```
[tool-io] TOTAL 出现于  16:34:37   16:49:59   16:54:01
```
间隔 15 分 22 秒(节流值 `ENVGEN_TOOLIO_ROLLUP_MIN` 默认 15 分钟)+ 退出时的 `force=True`。
一个 21 分钟的 run 留下 3 份账,而不是过去的"只有干净退出才有 1 份"。

### `#1202dp` — 未活体触发,但**反事实已对着 r44 的真实状态验过**

`FINAL-GATE GRACE = 0`,resume2 没走到最终门禁(结尾是 Node.js 崩溃,不是门禁判定)。
但可以直接检查:**在 r44 放弃的那一刻,宽限的三个前置条件是否都成立**——

| 守卫 | r44 实测 |
|---|---|
| ① 有东西在被派活(`_gatecheck_wedged_ticks_1040 == 0`) | `#1040 DELIVERY IS WEDGED` 出现 **0 次**;放弃前 **2 秒**刚派出 `task_c448404c80` |
| ② 墙钟余量 ≥ 120s + 60s 尾 | cap 10800s,127 分钟时放弃 → 余 **3180s**,够 17 轮(上限 3) |
| ③ 阻塞项有 owner | `business_response_key_noncanonical` 被派 21 次,`validation_ui_evidence_failed` 10 次 |

**三条全部成立 → 宽限会启动 3 轮 / 共 6 分钟**,而不是在派出修复 2 秒后终结一个还剩
53 分钟墙钟、144 个 tick 的 run。这不等于活体触发,但它回答了最关键的问题:
**这个修复对准的是不是那个真实场景。是。**

触发条件不罕见(r44 主跑撞上过),下一个 run 自然会遇到。

## 9. 方法论(这轮救了我四次,建议照做)

**每条静态审计都要配一个"把缺陷删回去必须变红"的反证测试,否则绿色毫无信息量。**

我这轮的检测器空过了两次,都是同一个毛病 —— **匹到"文本出现该词"而非"该事发生"**:

1. `subs.index("INBOX_ONLY_SUBSCRIPTIONS")` 命中的是 **DEFAULT 块内部一句注释**
   ("moved to INBOX_ONLY_SUBSCRIPTIONS below"),把后半段整个吞成 inbox_only
   → 审计报 10(实为 25),绊线**一条断言都没跑**。
   修:行首锚点 `re.search(rf"^{name}[^=]*=\s*\{{", src, re.M)`。
2. 修好锚点后反证仍不响:检测用**子串**判"有没有分支",而我自己写的注释里
   `bug_found` 出现 6 次。修:解析 `msg_type == "X"` / `msg_type in (...)` 构造。

三次反证全部做完并通过:`#1202dr` 拆分支 → 2 红;订阅绊线删分支 → 正确报出 `bug_found`;
`#1202dp` 移除 grace → 8 红。三次都验证了文件字节还原。

---

## 10. 交给下一个 session 的动作项

**必须做**:

1. **用带 `#1202dq`/`#1202dr`/`#1202dp` 的代码跑一个 run** —— 这是三个修复行为层验证的
   唯一途径,也是 §7 唯一的解锁方式。验证信号:
   - `[debugger] Handling bug_found — opening a triage loop`(#1202dr)
   - 周期性的 `[tool-io] TOTAL`,且硬杀后日志里仍有(#1202dq)
   - `#1202dp FINAL-GATE GRACE n/3`,以及 grace 后是否 CLEARED(#1202dp)
2. **读那份 tool-io 表**,重新测 `check_inbox` 的当代占比,再决定要不要动发送端。

**注意**:

- ⚠ `.gitignore:38` 忽略 `/agent/tests/` —— 本轮 4 个新测试文件**不随代码提交**,
  接手的机器上没有它们(仓库既定 local-only 惯例)。
- ⚠ **活跃 run 期间绝不起 docker 栈** —— 同 env 不同 run 的 compose 端口相同必然互斥,
  曾因此烧掉 r43 的 $400。
- ⚠ **套件不要和 live run 并跑**(I/O 争用,曾 151s 只跑 2%)。
- ⚠ 判交付看 `passed`/`released` 和是否有 release,**别用宽 grep** ——
  我用 `grep -c 'DELIVER\|...'` 得到过 "delivered: 25" 的假阳,实际根本没交付。

**等用户决定(我没有权限自己做)**:

- 根分区 100% 满。`docker system df` 可回收 ≈135GB(镜像 97.97GB / 卷 35.95GB / 容器 1.88GB)。
  ⚠ 根分区的 1.2T 是 `/home` 下**别的用户**的(huichen 231G、jingliu 110G…),不该动;
  卷里是用户各 env 的持久化数据,`--volumes` 必须用户确认。
- 是否提交(15 个改动文件)。
