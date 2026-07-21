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
