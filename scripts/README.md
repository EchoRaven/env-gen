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

## 换 LLM provider（例:Meta 的 Claude 5 Fable,经 Llama API 直连,**不需要 buck2/sidecar**)

`tiktok_designinput.sh` / `run_tiktok_designinput.sh` 都支持用环境变量切换 provider:

```bash
export ENVGEN_PROVIDER=openai                                        # 走 OpenAI 兼容协议
export ENVGEN_MODEL=claude-5-fable-vertex-genai
export ENVGEN_API_BASE=https://api.llama.com/experimental/compat/openai/v1
export ENVGEN_LLM_KEY='LLM|<id>|<secret>'                            # 覆盖 OPENAI_API_KEY，不动共享 key 文件
./run_tiktok_designinput.sh 46
```

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
