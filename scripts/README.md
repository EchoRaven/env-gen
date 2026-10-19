# scripts/ — 生成器运行脚本（可移植版）

## `tiktok_designinput.sh`

从仓库根跑一个 TikTok design-input 全栈生成 run。**无 key、无机器特定路径**——一切靠环境变量。

```bash
# 1) 环境
export GOOGLE_API_KEY=...              # 必需（Gemini）
export ENVGEN_UNSPLASH_KEY=...         # 可选（内容图片）
export ENVGEN_PIXABAY_KEY=...          # 可选
export PYTHON=/path/to/venv/bin/python # 装了本仓库依赖 + playwright 的 python；默认 "python"
#   （或把上面这些 export 写进一个文件，然后 export ENVGEN_KEY_FILE=/path/to/that/file.sh）

# 2) design 素材就位（见下）

# 3) 跑
./scripts/tiktok_designinput.sh 1      # 参数是 run 编号；输出 generated/tiktok-web-r1/，日志 gm_tiktok_r1.log
```

铁律：**两 run 不并发**（脚本有守卫）；**run 活着时不要 `docker compose up/down`**；**每个 run 端口随机**——
runtime-verify 时从 `generated/tiktok-web-r<N>/docker/docker-compose.yml` 的 `ports:` 读真实端口。

## `reclaim_generated.sh` — 从 `generated/` 回收磁盘（默认只预览）

2026-10-13:`/data` 满了(剩 3.4G),而单个 run 要约 6G。不先腾空间就会撞 ENOSPC,
而 `#1203ib` 记过**满盘会被误判成「app 的问题」**,等于烧掉一整轮预算去追一个不在 app 里的缺陷。

```bash
./scripts/reclaim_generated.sh             # 预览(默认 KEEP_N=20), 不删任何东西
KEEP_N=30 ./scripts/reclaim_generated.sh   # 预览更保守的切法
APPLY=1 ./scripts/reclaim_generated.sh     # 真的删
```

三道安全保证,都是按构造成立的:

1. **只动本仓库的 `generated/`** —— 路径写死,不是参数。`/data` 是**多用户共享盘**
   (`datasets/`、`relm/`、`sota/`、`yiran/`,以及 `/data/common` 下十几个其他用户),
   那些都不是我们该清的。
2. **保留被源码引用的 run** —— 好几张票的注释点名了具体 run 作为证据
   (`#1203ir` 引 gmrun4、`#1148` 引 netflix-local-r8、`#1203it` 引 instagram-core-r176…),
   删掉它就让那条注释**不可复核**。实测有 **90 个** run 被引用,全部自动保留。
3. **活 run 期间拒绝执行** —— 判据是 run 自己台账里的 `usage.pid` + `kill -0`,
   **不是** `pgrep -f`:后者会匹配到检查者自己的命令行,本脚本第一版就因此误判(铁律记在
   `feedback_pgrep_pattern_matches_itself`)。

另外保留最近 `KEEP_N` 个 tiktok run,以及 r184–r188(2026-10-13 那批补丁的证据来源)。
配合 `disk_headroom.py`(它看根盘/docker)一起用。

## design 素材（`design_inputs/tiktok/`）

生成器需要 `design_inputs/tiktok/{references,assets,docs,dataset}`。**这批素材 ~200MB（图片/视频），
默认 `.gitignore`，不进 git**（避免永久性仓库膨胀）。在新机器上用以下之一准备：

- **rsync/scp 从有素材的主机同步**（推荐）：
  ```bash
  rsync -avz <主机>:/data/common/haibotong/forgingground-gen/design_inputs/tiktok/ ./design_inputs/tiktok/
  ```
- 或把素材放别处，跑之前 `export ENVGEN_DESIGN_INPUT=/abs/path/to/tiktok`。

素材树（供核对）：
```
design_inputs/tiktok/
  references/   # 参考截图（design 分析用）
  assets/       # 图片 + mp4（staging/seeding 用，最大头）
  dataset/      # seed json（用户/视频/评论/声音等真数据）
  docs/         # 说明
```

## 换 LLM provider（经 Llama API 兼容网关直连,**不需要 buck2/sidecar**)

`tiktok_designinput.sh` / `run_tiktok_designinput.sh` 都支持用环境变量切换 provider:

```bash
export ENVGEN_PROVIDER=openai                                        # 走 OpenAI 兼容协议
export ENVGEN_MODEL=claude-4-7-opus-vertex-genai
export ENVGEN_API_BASE=https://api.llama.com/experimental/compat/openai/v1
export ENVGEN_LLM_KEY='LLM|<id>|<secret>'                            # 覆盖 OPENAI_API_KEY，不动共享 key 文件
./run_tiktok_designinput.sh 53
```

### ★ 网关模型选型（2026-07-21 实测,**这是踩坑最深的一段,换模型前先读**）

网关的模型名是 `<模型>-<后端>` 式,且**后端后缀决定能不能用工具** —— pipeline 是 100% 工具驱动的,所以这一条是生死线:

| 模型名 | 对话 | **工具调用** | 结论 |
|---|---|---|---|
| `claude-4-7-opus-vertex-genai` | ✓ | **✓ 含 tool_result 回合 + 多轮 + 视觉** | **可用,框架零改动** |
| `gpt-5-5-genai-responses` | ✓ | **✗ 结构性不可能** | 不可用 |
| `gpt-5-6-sol-genai-responses` | ✓ | ✗ 同上 | 不可用 |
| `claude-5-fable-vertex-genai` | ✗ 500 | — | 网关 mapper 崩 |

**`-responses` 后缀的模型全部不能用工具**，原因在网关而非模型，客户端无法绕过：

- 发嵌套 `tools[].function`（Chat 标准）→ 下游 400 `Missing required parameter: 'tools[0].name'`
- 发扁平 `tools[].name`（Responses 式）→ 网关 500，吐自己的 PHP 栈
  `LlamaApiExperimentalOpenAIChatCompletionsMapper.php(86): HH\Shapes::at()`
- 两种形状**同时**给 → 过了 mapper，下游仍报同一个 400

第三条是判定性的：证明 mapper **从 `tools[].function` 重建**工具对象而非透传，所以输出形状由网关决定，
客户端发什么都无效。即该 mapper 给一个 **Responses API 下游**生成了 **Chat Completions 形状**的 tools。

**权限是按 key 绑定的**（metagen key 由 LLM key 服务端推导，请求里传 `X-MetaGen-Key` 之类**无效**）：
一把 key 能用 opus-4.7 + gpt-5.5，另一把能用 gpt-5.6-sol —— 换模型跑不通先确认是不是 key 不对，
错误文案会直接把生效的 `mg-api-...` 打出来。

### 第三方 OpenAI 兼容端点的坑（都已在框架侧修掉，换新 provider 时按此排查）

| 症状 | 原因 | 已修 |
|---|---|---|
| 400 `frequency_penalty is not supported in OpenAI compatibility mode` | 我们默认发 penalties（值是 0.0，语义空操作） | #247a 仅在非零时发送 |
| 400 `` `temperature` is deprecated for this model `` | Claude on Vertex 拒绝采样参数 | #247b sampling-hostile 家族判定（claude/vertex/anthropic/fable）+ `ENVGEN_NO_SAMPLING_PARAMS=1` |
| 400 `image exceeds 5 MB maximum: N bytes > 5242880` | 上限按 **base64 字符串长度** 算，且 design-prep 直接拼 image_url parts | #248 全路径压缩（`ENVGEN_IMAGE_BYTE_LIMIT`，默认 4.5M base64 字符） |
| 400 `unexpected tool_use_id ... must have a corresponding tool_use block in the PREVIOUS message` | 观察遮蔽把 assistant 轮次删了却留下 tool 结果 → 孤儿；Anthropic 要求**相邻** | #249 遮蔽后按相邻性剪孤儿，dict/对象两种形态都处理 |

**排查要领**:所有请求都经 `utils/llm.py:_prepare_messages_for_request`（剪孤儿 → 压图片）。
新 provider 的协议修复**只加在这一处**，四个调用点自动生效（历史上每个修复都要改四遍、且总漏一处）。

Claude on Vertex **要求** `max_tokens`；生成器按模型名解析（`claude-5-fable-vertex-genai` → 8192），也可 `--max-tokens` 显式指定。

## `mutate.py` — 跑证伪变异，且**绝不**把工具自己的失败当成结论

每个守卫都要靠「删掉它→测试变红」来验证。这个流程此前每次都手写,而在 2026-10-14 它
**失败了两次,两次都看起来像发现**:

* 一条 `sed` 因为引号从没匹配上,**什么都没改**,而手写脚本打印
  `MISSED <- M4 ...` —— 我据此以为「测试太弱」,去改测试;用 python 加上计数断言重跑同一条
  变异,它其实 CAUGHT。
* 一条把 `try:` 换成 `if False:` 的变异留下孤立的 `except`,pytest **收集**就失败了 ——
  一个语法错误的 mutant 同样被打印成 `MISSED`。

所以这里有**四个判决,互不混淆**:

    CAUGHT       mutant 编译了、跑了,测试变红 → 这条测试在这里有证伪力
    MISSED       mutant 编译了、跑了,测试仍然绿 → 真缺口
    NOT APPLIED  锚点没有**恰好出现一次** → 什么都没测(不是关于测试的证据)
    BROKEN       mutant 编译不过,或测试模块收集不了 → 什么都没测

只有全部 CAUGHT 才 exit 0。另外它**拒绝在 baseline 是红的时候开工** —— 对着一个失败的测试
文件,每条变异都会读成 CAUGHT,那是同一种虚假安慰升了一级。

★ **规格要存进仓库,不要写到 `/tmp`(`#1203pe`)**。规格是「这条变异在验哪条性质」的唯一记录,
而本节此前教的是 `cat > /tmp/spec.json` —— 于是每次会话结束它就没了。**这会废掉一条依赖历史的
纪律**:后落的补丁会改写先落补丁的锚点,那条性质悄悄变成「没有变异在验」而套件照绿;要抓它必须
拿**过去的**规格去对当前的树,而过去的规格已经不在。落地时实测:当前会话有 **62 份规格 / 253 条
变异**,而**任何更早会话一份都没有**,仓库里也没有副本 —— 这条纪律的跨会话那一半**从来没能跑过**。
`mutate.py` 自己的头注就引了 `#826`:「a check that lives in a habit is not a check」。

规格放 `scripts/mutations/*.json`,免费的锚点普查用:

```bash
scripts/mutation_census.py            # 只数锚点,不跑测试
scripts/mutation_census.py --strict   # 有「未解释的锚点丢失」就退非零
```

锚点不再恰好出现一次**不自动等于问题** —— 代码可能是被刻意重写的。但它必须**被解释**,方式是在
那条变异的 `label` 里写上 `[SUPERSEDED <日期>: 性质现在由谁承接]` / `[NOT RUNNABLE: …]` /
`[BAD-ANCHOR: …]`。词表是封闭的:**「代码变了」不算解释**,那正是要报的东西。

```bash
cat > scripts/mutations/mut_<ticket>.json <<'EOF'
{"file": "agent/env_generator/llm_generator/multi_agent/runtime/delivery_gate.py",
 "test": "tests/test_1203jg_the_top_blocker_said_nothing.py",
 "mutations": [
   {"label": "the reason is dropped, only page names kept",
    "find": "why.append(\"%s: %s\" % (page, summary or \"no summary recorded\"))",
    "replace": "why.append(page)"}]}
EOF
scripts/mutate.py /tmp/spec.json      # 或 ... | scripts/mutate.py -
```

`file` 相对仓库根(也接受绝对路径);`test` 相对 `agent/`,所以从 `suite.sh` 输出里
复制的路径可以直接用。每条变异之后都会恢复文件,结束时按 sha256 校验,并在没恢复时 exit 3。

★ 它用 **pytest 的退出码**分类,不是子串匹配输出:第一版找 `"error during collection"`,
而它自己的测试会把这个字符串当**数据**喂进来,于是一条真 CAUGHT 被报成 BROKEN ——
判据匹配到了 payload 而不是状态。用这个工具变异它自己的时候发现的(#1203ji)。

## `verify_shipped_fixes.py` — 一个 run 跑完后，逐条回答「我发的修复到底生效了没有」

2026-09-29 有六个行为变更和两个仪器落地，**一个都没有线上验证过**——provider 余额归零，
r141 起跑 82.7 秒就死在 `429 insufficient_quota`。检验点当时只存在于记忆里的散文，
意味着余额一恢复，第一件事是我重新推导该打开哪个文件。那是**摩擦恰好落在瓶颈上**，
所以把它变成一条命令。

```bash
python scripts/verify_shipped_fixes.py generated/tiktok-web-r142
python scripts/verify_shipped_fixes.py --self-test     # 对着 r140（早于所有修复）自检
```

每条检查只给三种判定，且**绝不混淆第三种**：

| 判定 | 含义 |
|---|---|
| `CONFIRMED` | 产物说的和修复预测的一致 |
| `FALSIFIED` | 产物说的相反——预测错了，去读为什么 |
| `NOT MEASURED` | 产物缺失或为空，这个 run **什么都没说** |

第三种才是要害。只有通过/失败两档的检查器，会把「产物不存在」塞进其中一档，
而**产物不存在不构成任何一方的证据**——这就是 #1202z5 在另一个模块修的同一个缺陷。

`--self-test` 跑在 `generated/tiktok-web-r140` 上，那个 run **早于这里的每一个修复**：
仪器类检查必须全部答 `NOT MEASURED`。若它对一个不可能带有修复的 run 报 `CONFIRMED`，
说明检查器读错了字段。

### `--live`：不花 credits 就能验的那一半

余额归零时,我把六个修复整体归为「需要活 run」——**错了,其中四个只需要产物**。
判据是:对每一个问「哪部分需要模型,哪部分只需要已经在磁盘上或已经跑着的东西」。

```bash
python scripts/verify_shipped_fixes.py --live generated/tiktok-web-r140
```

- **#1202zd** —— 连到该 run **活着的 Postgres**(端口从 `docker-compose.yml` 读,**不从 `docker ps` 猜**),
  用 `ast` 从模板里抽出出厂的行转换函数(不是抄一份),执行真的 `INSERT..RETURNING`,
  确认 `username` 回来了、裸 `json.dumps` **抛错**(那正是它防的 500)、转换后可序列化,
  然后**回滚** —— 活着的 app 不被碰。`finally` 里的 rollback 有结构断言钉着,因为它是往交付库里
  插数据的**唯一许可**。
- **#1202ze** —— 回放磁盘上**全部真实门禁记录**。那个报告器是门禁 dict 的纯函数,
  所以它从不需要门禁「运行」(那要替换注入的回调,还会让 `scaffold_design_readme` 往交付树写文件),
  它需要门禁的**输出**,而那早就在 `logs/delivery_gate.jsonl` 里。

栈没起来 → `NOT MEASURED`,不是 `FALSIFIED`:**栈的状态不构成关于修复的证据**,
报成失败会把下一个读它的人送去调一个没坏的东西。

覆盖：#1202za（哪个工具在重复轮询）、#1202zb（没有端点读的表）、#1202zc（工具菜单是否
不再每轮重排、32 的上限有没有被顶到）、#1202zd（register 是否返回本 app 的列 + 行是否做了
JSON 安全转换）、#1202ze（门禁判过而 smoke 为假）、#1202zf（交付树里是否还缺媒体）、
以及 uncached/cached 的**比例**（不是美元总额——run 越长越贵，效率不变）。

## `preflight_credential.py` — 起 run 之前，先问凭据答不答

启动脚本长期有六道预检（provider/model、key 存在、不并发、素材、磁盘 60G、playwright），
但它只检查 key **存在**，从不检查它**答不答**。r141 六道全过，然后 82.7 秒后死在
`429 insufficient_quota`——**进程墙钟 612 秒**，而一次 HTTP 调用两秒就能知道。
现在它是启动脚本的第七道预检（`ENVGEN_PREFLIGHT=0` 可跳过），也能单独跑：

```bash
source /path/to/key.sh && python scripts/preflight_credential.py; echo $?
```

分类是这道检查的全部设计，两个方向错了都比不做更贵：

| 退出码 | 含义 | 触发 |
|---|---|---|
| `0` | 可以起 run | 200，或 provider 不在可探测之列（google/metagen/local） |
| `1` | **明确拒绝** | 401/403、body 里点名额度/账单的 429、模型 404 |
| `2` | 不确定，**不拒绝** | 超时/DNS/连接重置/5xx/无法解析的 body，以及**裸 429** |

裸 429 是普通限流、会自己好。#1159 和 #1174 为这个区分付过两次代价：r15 对着一个死账户
重试了 2 小时 50 分，而 r16——已花 $262、只剩一道门禁——被一次 **57 秒**的额度抖动杀掉。
在网络抖动上拒绝，是把「白烧一轮」换成「本可以跑却没跑」，那更糟。

密钥永不出现在输出里：provider 若把 key 回显在错误体里，会被洗成 `sk-***`。

## `disk_headroom.py` — 有没有地方跑 run，以及空间**实际**在哪能回收

启动脚本的磁盘预检长期是这三行：

```sh
AVAIL_G=$(df --output=avail -BG / | tail -1 | tr -dc 0-9)
[ "${AVAIL_G:-0}" -ge 60 ] || { echo "REFUSED: ... 先 docker builder prune -af"; exit 1; }
```

**两个缺陷。** 其一：`df -BG` **向上取整** —— 2026-09-29 实测 root 可用 **59.625 GiB**
（64,022,118,400 字节），`df -BG` 打印 **60G**，检查**放行**。地板实际是 59.001 GiB，
而且是朝「放行」的方向取整，正好放进那个第 40 分钟写满磁盘而死的 run。

其二：那句 `先 docker builder prune -af` 指向一个空抽屉 —— 同一天 build cache **0B**，
而镜像 **39.06GB**、卷 **20.82GB**。一条曾经为真的提示，会把读它的人送去唯一什么都没有的地方。

```bash
python scripts/disk_headroom.py [floor_gb]    # 默认 60；低于地板 exit 1
```

它按精确字节判断，并把回收建议改成**当场测量**，且区分两种回收的安全性：

| 回收项 | 安全性 |
|---|---|
| 悬空**镜像** | **安全** —— 无 tag、无容器引用、可重建 |
| 悬空**卷** | **不安全** —— `dangling=true` 的含义是「没有容器引用」，**包含「当前停着但数据要留」的环境**。这台机器上那批覆盖了其他工作线（windows_web / macos_web / 通讯类 app）的环境，共 432 个卷 / 20.8G。**不能整体 prune，要逐个决定。** |

---

## `text_assertion_ratio.py` —— 哪些测试其实什么都没在验（#1203pg）

断言写成 `"<某行代码>" in inspect.getsource(mod)` 时，它被满足的条件是**那行存在**。于是
「保留那行、让它永不执行」或「反转它外面的 `if`」的变异，在源码文本上**一模一样**。一个
**从不调用它所命名的东西**的测试，根本看不见行为变化。

**它是靠预测验证的，不是事后拟合。** 2026-10-19 一批四个守卫，先算占比再跑变异：

| 测试 | 占比 | 变异结果 |
|---|---|---|
| `test_fwval_early_return_checklist_502.py`（纯谓词） | 0.00 | **4/4 CAUGHT** |
| `test_redispatch_nags_without_cloning_794.py` | 0.95 | **0/3** —— 三个真缺口 |
| `test_the_visual_defer_check_that_failed_open_888.py` | 1.00 | 2 MISSED + 1 对照 CAUGHT |
| `test_the_kickoff_guard_that_failed_open_882.py` | 1.00 | 2 MISSED + 1 对照 CAUGHT |

共 **7 个真缺口**，补行为驱动后 **12/12 CAUGHT**。

**最坏组合，按名字就能认出来**：「**fail open** 的守卫 + 全文本断言」—— 它整个意义就是
「出错时的行为」，而没有任何东西驱动出错路径。888 和 882 都是这样找到的，而两个文件里
**唯一被捕到的变异都是同一个性质**（permissive default 被那个只出现一次的
`return False` / `_pre_finalize = False` 钉住）。

```bash
python scripts/text_assertion_ratio.py --check          # 先验证检测器；不过就 exit 1
python scripts/text_assertion_ratio.py --limit 30       # 占比 1.00 的排名
python scripts/text_assertion_ratio.py --min-ratio 0.8
```

**`--check` 不是装饰。** 这个检测器写错过**四次**，每次都给出了自信的数字，而每次修正都是朝
「更少假阳」的方向走 —— 头条数字依次是 **7 → 105 → 64 → 32**：

1. **漏了传递**：`_src()` 返回 `getsource(...)`、`s = _src()`、`blk = s[i:j]` —— 三跳。
   第一版只认直接形式，把 #794 算成 **0.05**（人工读数 18/19），并报「只有 7 个测试全是文本」。
2. **把读夹具当成读源码**：`.read()` 单独匹配，于是 `open("fixture.json").read()` 也算文本，
   占比全面虚高。
3. **文本名字从字符串字面量里漏出来并级联**：匹配用的是「名字作为单词出现在 unparse 文本里」，
   于是 `test_1202z0` 的链条 `src → tree → fn → calls` 之后，
   `wh = _WH([{"title": "...the page **calls** an auth-required endpoint..."}])`
   从**字符串内部**捡到了 `calls`，于是 `wh` 被标记、`d = wh.created[0]["description"]` 也被标记
   —— 那个文件 **18 条断言全被算成源码文本**，而它其实是全目录里最行为化的之一（它造一个假
   WorkHub 并断言它建出来的任务）。修法：比 **`ast.Name` 的 id**，不比文本。
   这与 `#1203ph` 在 `test_1202eu` 上修的是**同一类错**，相隔两小时。
4. **「读源码」和「跑源码」被算成一回事**：`test_1202kn` 用 `getsource` 把门禁表达式取出来再
   `eval` 它 —— 全是源码派生的名字，占比 1.00，而它的变异 **2/2 CAUGHT**，因为求值就是驱动。

**而自检本身的锚点也烂过一次，这是最贵的一课。** 第一版锚在两个真实文件的人工读数
（18/19 和 0/7）上。不到一小时就失效 —— 因为我按这个仪器自己的发现去补了行为驱动，读数
变成 18/27 和 0/10，于是「检查」在**完全正确的工作上报红**（#1203oa：挂起的测量会烂）。
现在自检锚在**由构造决定答案的合成用例**上（含那个三跳 bug 的永久回归用例），真实文件只
断言**不会烂的形状**：「纯谓词 ⇒ 文本数 0」、「混合 ⇒ 两种断言都有」。第 2 个缺陷就是
合成用例抓出来的。

**用法**：占比高 ⇒ 写一个**保留全部被断言字符串、只改行为**的变异（插 `return` 让它不可
达 / 反转它外面的 `if` / 反转状态过滤），并**配一个预期 CAUGHT 的对照**，否则分不清
「测试太弱」和「变异是空的」。**占比 1.00 不等于有缺口** —— `test_1202kn` 就是 1.00 而 2/2
CAUGHT。具体数字不写在这里（#1202vs：每一份拷贝都是负债），跑一次工具就有。
