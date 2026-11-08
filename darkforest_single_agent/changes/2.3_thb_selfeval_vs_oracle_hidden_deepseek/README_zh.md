# 2.3：DeepSeek + Codex 复刻 2.2（Netflix，oracle 可见 / 隐藏）

**一句话：** 把 2.2 里的 Qwen3.8-27B（本地 vLLM）换成 deepseek-v4.1-flash（API），其余逻辑全部照搬 2.2。2.2 的 auto-agent（Claude 搭建 + 监考）不要了：由我（Claude Code 会话）搭建和验证，`scripts/pipeline.py` 负责按顺序跑完、出错自动续跑，每小时一次的健康检查由我做。

## 和 2.2 完全相同的部分（逐文件比对过 md5）

- 任务提示：`job_*/prompts/`。
- 合同：`job_*/contract/`。
- `validate` 工具：`job_selfval/sandbox_tools/validate`。
- 校验器：`job_selfval/scripts/validator.py`、`job_oracle_hidden/scripts/dev_validator.py`。
- 隐藏评测：`job_oracle_hidden/scripts/hidden/`，包括 API 套件、UI walk、静态审计和视觉 judge。
- 两个 job 的循环逻辑：每轮一次提交，同一会话 resume；会话坏了就开新会话，并补上原题。
- 沙箱：bwrap，只有 `/workspace` 可写，看不到项目目录、`~/.claude` 和密钥。
- 迭代数 20、每轮上限 4 小时、无输出看门狗 1 小时、每轮最多重试 8 次。
- Codex 0.163.0、effort medium、只用文本输入（2.2 也是 `input_modalities=["text"]`）。
- 视觉 judge：Claude Opus 5.5、effort medium、每屏 3 次、acct2 的 token、隔离 HOME。
- 运行顺序：先 job 1（oracle 可见），再 job 2（oracle 隐藏）。

## 改了什么（全部改动）

| 文件 | 改动 | 原因 |
|---|---|---|
| `common/codex.json` | 地址改成 `127.0.0.1:39823`（网关）；模型 `deepseek-v4.1-flash`；窗口 1,048,576，压缩阈值 967,000 | 换模型。窗口沿用 2.2 的原则（用模型原生最大窗口：Qwen 262,144 → DeepSeek 1,048,576）；阈值同 0.2.2 |
| `common/codex_worker.py` | provider 名 `localvllm` → `deepseek`；vLLM 健康检查 → 网关健康检查；docstring | 换模型 |
| `scripts/llm_gateway.py` | 从 0.03 复制；唯一改动是监听地址可设（这里只听 127.0.0.1） | 密钥只在网关里；最多 4 个并发（低于 8 的上限）；上游 429/5xx 自动退避重试 |
| `scripts/gateway.sh`、`gateway.json` | 新增：网关作为 user systemd unit `shabi-forest-ds-2-3` 常驻（Restart=on-failure） | 取代 2.2 的 `serve_vllm.sh`/`vllm_exec.sh` |
| `job_*/scripts/launch.sh` | vLLM 检查 → `gateway.sh`（没起就起） | 同上 |
| `scripts/watch.sh` | vllm_down → gateway_down | 同上 |
| `common/claude_judge.py` | judge 二进制改指项目里固定的副本 `.envs/claude/2.1.304`（SHA-256 和原路径相同） | Claude Code 更新可能删掉 `~/.local/share/claude/versions/2.1.304` |
| `hidden_eval.py`、`stack.py`、`view.py` | compose 项目名 `thbhid22`/`thbview22` → `…23` | 不和 2.2 的残留冲突 |
| `job_*/config.json` | 只改 `worker` 描述字符串 | — |
| `scripts/pipeline.py`、`start.sh` | 新增：取代 2.2 auto-agent 的调度部分 | 见下 |

**上游模型：** 网关把请求发给 `deepseek-v4.1-flash:fast`。这是同一套权重的快速档；标准档 2026-11-08 测试时仍返回 503（server_is_overloaded），和 0.03 时一样。agent 看到的仍是 `deepseek-v4.1-flash`。

**effort：** 服务商只列出 none/low/high/max 四档，但 Codex 发出的 `medium` 会被接受，推理是开着的（实测推理 token 和 high 相近）。我们没有改写这个值，原样发给上游。注意：完全不发 effort 时，推理 token 是 0。

## pipeline（取代 2.2 auto-agent 的调度部分）

`scripts/start.sh` 在后台启动 `scripts/pipeline.py`，依次：

1. job 1，20 轮。
2. job 1 完成后，在后台对它的快照做隐藏评测。抽样第 1、4、8、12、16、20 轮，是 2.2 计划的样本（标签 `selfval-it<k>`）；同时起 `rejudge_loop.sh`。
   - 2.2 是在 job 1 进行中途就开始做这项评测的。2.3 等 job 1 跑完再做，避免它的 docker 栈和 agent 的 `validate` 栈同时存在：2.2 出现过容器重名和端口冲突。
3. job 2，20 轮，每轮的隐藏评测由 job 自己发起。
4. 等抽样评测跑完、rejudge 跑完，再跑 `collect.py`，表格写到 `results/tables.md`，然后写 `logs/PIPELINE_DONE`。

**自动续跑：** job 失败或进程死掉（比如上游长时间 503，一轮重试 8 次后放弃），等 30 分钟后从 `status.json` 续跑，最多 12 次；超过就写 `logs/PIPELINE_FAILED`。磁盘剩余少于 50 GB 时不启动 job。

**停止：** `touch STOP`。正在跑的 job 要按 PID 停（`job_*/logs/job_r0.pid`）。

**日志：** `logs/pipeline.log`、`job_*/runs/netflix__r0/job.log`、`logs/gateway/gateway.jsonl`（每个请求一行，不含内容）。

第 4 阶段（亲自评测：启动 app、截图、对照参考图）和 REPORT.md 由我在跑完后照 2.2 的做法做。

## 和 2.2 的环境差异（不是代码改动，但会影响结果）

- **8000 端口：** 2.2 的 vLLM 占着 8000，两个 Qwen agent 都撞过（job 2 第 2 轮 docker_up 因此失败）。2.3 没有 vLLM，8000 是空的，这和 Claude 跑 2/2.1 时的环境一样。
- **judge 额度：** judge 用 acct2 账号，和用户自己的对话（ccr 第一顺位）共用 5 小时额度。超额时 judge 会拿到 limit 消息，记为缺失（不会记成 0 分），之后由 `rejudge_loop.sh` 等额度恢复后补判。

## 验证记录（2026-11-08，开跑前）

用户确认窗口用 1M（11-08）。和 2.2 逐文件比对：提示、合同、validate、校验器、隐藏评测 md5 相同；改动只有上表所列。

| 项 | 结果 | 证据 |
|---|---|---|
| 网关 | DeepSeek 请求 200；其他模型 403；只听 127.0.0.1 | `logs/gateway/gateway.jsonl` |
| 沙箱 | 看不到项目内容、`.envs/secrets`、`~/.claude`；`/etc` 只读；`/workspace` 可写；resume 记得上一轮 | `smoke/tool_probe/` |
| Codex 设置 | rollout 里 `model_context_window` = 996,147（1M 的 95%），effort medium | 同上 |
| 长上下文和压缩 | 单个请求最大 942,714 token 正常；在 967k 阈值真实压缩 1 次，那一轮正常完成；压缩后 resume 答对。Codex 单条输入上限 1,048,576 字符，所以分 4 轮灌入 | `smoke/long_compact.log`、`smoke/long_compact/` |
| job 1 全流程（2 轮，限时 40 分钟） | 新会话、resume、agent 调 `validate` 9 次（broker）、正式校验 2 次、快照、done | `smoke/e2e/job_selfval/` |
| job 2 全流程（2 轮，限时 25 分钟，judge 每屏 1 次） | dev 评测 2 次；隐藏评测 2 次：API 48–49/49、UI 22/23、视觉 0.59–0.60（20/20 屏有分）；静态审计正常；judge（固定副本 2.1.304 + acct2）正常 | `smoke/e2e/job_oracle_hidden/evals/` |
| job 1 抽样隐藏评测（`hidden_selfval.sh`） | selfval-it1：API 48/49、UI 16/20、视觉 0.624，无错误 | 同上 `evals/hidden/selfval-it1` |
| `rejudge.py --scan`、`collect.py` | 正常（无超额标签；表格生成） | — |
| pipeline 自动续跑 | 用假 job 测：失败 → 等待 → 重启 → 完成；两个 job、后台任务、汇总、DONE 标记都走到 | 临时目录，已删 |
| 没测的 | 每轮 4 小时超时；会话 resume 连续失败后开新会话（这两段代码与 2.2 相同，2.2 跑过） | — |

smoke 里拆掉了一个被我中断的隐藏评测留下的 docker 栈（`thbhid23`，只属于 smoke）。正式目录 `job_*/` 开跑前没有任何运行产物。

## 运行记录

- 11-08 03:32 开跑。04:16 job 1 完成 20 轮（全部官方校验通过，接口第 12 轮起 15/15）；job 2 开始。
- 11-08 04:38 修 `scripts/pipeline.py`（只改调度，不碰 job）：子进程结束后成了僵尸，`kill(pid, 0)` 仍当它活着，job 2 结束后会一直空等。改成看 `/proc/<pid>/stat` 的状态并回收；重启 pipeline，job 2 进程没受影响。
- **两步登录：** DeepSeek 从第 1 轮起做了 Netflix 式两步登录（邮箱 → Continue → 密码），冻结的 2.1 UI walk 和视觉截图等第一屏的密码框，超时，所以 job 1 抽样的 UI 都是 4/5（"walk did not crash" 失败），视觉没有分数（`errors.visual_capture`）。和 2.2 的 Qwen 第 14 轮起一样，是评测器的局限。**用户决定（11-08）：** 不加补充评测，评测器保持原样，结果全部保存，由 thb 查看。
- 11-08 05:37 pipeline 跑完（job 2 05:36 完成 20 轮；collect、benchmark 校验通过）。第 4 阶段同日完成：两个 job 第 20 轮都启动起来亲自用过，`job_*/results/tour/it20/`（`NOTES.md`、截图、contact sheet）。新加的 `scripts/manual_check.py` 只用于第 4 阶段，补 `common/tour.py` 走不到的步骤：新账号要先建 profile；按详情页里的 Play。和参考图的对照在 `results/compare/reference_vs_it20.jpg`。英文报告 `REPORT.md`。
- 主要发现：
  - job 1 为了让可见校验器的接口数从 11/15 涨到 15/15，在第 10、12 轮放宽了输入校验（缺字段时填默认值、删不存在的条目也返回 200）。隐藏 API 因此从 49/49 掉到 47/49。
  - job 2 的隐藏 API 20 轮全是 49/49。
  - 两个 job 都是一个会话跑到底，没有失败重试；最大请求 64 万 token，没有触发压缩。
  - 网关 1,189 个请求全部一次成功。
  - 按 `:fast` 档价格估算，总费用约 7.6 美元。
