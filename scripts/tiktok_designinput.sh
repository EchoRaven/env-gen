#!/usr/bin/env bash
# TikTok 环境生成脚本（design-input 全栈）— 可移植版
#
# 用法:
#   export GOOGLE_API_KEY=...            # 必需（Gemini）
#   export ENVGEN_UNSPLASH_KEY=...       # 可选（内容图片）
#   export ENVGEN_PIXABAY_KEY=...        # 可选
#   # 或: export ENVGEN_KEY_FILE=/path/to/key.sh  让脚本 source 它（里面 export 上述变量）
#   export PYTHON=/path/to/dt-env/bin/python     # 默认 "python"；必须是装了本仓库依赖 + playwright 的环境
#   ./scripts/tiktok_designinput.sh <runNN>      # 例: ./scripts/tiktok_designinput.sh 1
#
# 前置:
#   - 从仓库根运行；design_inputs/tiktok/{references,assets,docs,dataset} 已就位
#     （design_inputs 因体积大（~200MB 图片/视频）默认 gitignore；用 rsync/scp 从主机同步，
#      或设 ENVGEN_DESIGN_INPUT 指向别处）
#   - docker + docker compose 可用；root 盘 ≥60G 空闲
#
# 铁律: 两 run 不并发；run 活着时不要 docker up/down；每 run 端口不同（读生成的 compose）。
set -euo pipefail

RUN="${1:?用法: $0 <runNN>  (日志编号)}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # 脚本在 scripts/ 下，上一级是仓库根
PYTHON="${PYTHON:-python}"
LOG="$ROOT/gm_tiktok_r${RUN}.log"
DI="${ENVGEN_DESIGN_INPUT:-$ROOT/design_inputs/tiktok}"

# --- key: 从 ENVGEN_KEY_FILE 加载（可选），或要求环境里已有 GOOGLE_API_KEY（不硬编码任何路径/密钥）---
if [ -n "${ENVGEN_KEY_FILE:-}" ] && [ -f "${ENVGEN_KEY_FILE}" ]; then
  # shellcheck disable=SC1090
  source "${ENVGEN_KEY_FILE}"
fi
[ -n "${GOOGLE_API_KEY:-}" ] || { echo "REFUSED: GOOGLE_API_KEY 未设置（export，或用 ENVGEN_KEY_FILE 指向一个 key 脚本）" >&2; exit 1; }

# --- 两 run 不并发 ---
if pgrep -f "env_generator.llm_generator.main" >/dev/null; then
  echo "REFUSED: another env_generator run is live (两 run 不并发)。先等它收官或 kill 后再启。" >&2
  pgrep -af "env_generator.llm_generator.main" >&2
  exit 1
fi

# --- 素材就位检查 ---
[ -d "$DI/references" ] && [ -n "$(ls "$DI/references" 2>/dev/null)" ] \
  || { echo "REFUSED: $DI/references 不存在或为空（design 素材未就位；rsync 过来或设 ENVGEN_DESIGN_INPUT）" >&2; exit 1; }

# --- 磁盘预检（docker build cache 每天涨 30-60G；满了先 docker builder prune -af）---
AVAIL_G=$(df --output=avail -BG / | tail -1 | tr -dc 0-9)
[ "${AVAIL_G:-0}" -ge 60 ] || { echo "REFUSED: root 剩 ${AVAIL_G}G < 60G，先 docker builder prune -af" >&2; exit 1; }

# --- 浏览器预检（幂等；缺 headless-shell 会让 runtime 门禁全盲）---
"$PYTHON" -m playwright install chromium chromium-headless-shell \
  || { echo "REFUSED: playwright browser preflight 失败" >&2; exit 1; }

cd "$ROOT/agent"

# setsid: 脱离当前会话，session 轮转不会杀掉本 run
setsid "$PYTHON" -m env_generator.llm_generator.main \
  --name "tiktok-web-r${RUN}" \
  --output "$ROOT/generated" \
  --design-input "$DI" \
  --provider google --model gemini-3.1-pro-preview-customtools \
  --description "TikTok web clone (desktop web, dark theme, brand red #FE2C55). Auth: login modal (QR / phone-email / social) + signup. Left nav sidebar (For You, Explore, Following, Friends, LIVE, Messages, Activity, Upload, Profile, More). For You feed: vertical 9:16 video with mute toggle, progress bar, bottom-left caption + sound name, right action rail (follow, like, comment, save, share with counts) and up/down nav. Comments panel: comment list with likes/replies and log-in-to-comment. Explore masonry grid with category tabs. Following and Friends suggested-creator grids with red Follow buttons. LIVE/Discover with its own sidebar and live cards showing viewer counts. Messages: DM conversation list + empty chat pane. Activity/notifications with tabs (All, Likes, Comments, Mentions, Followers). Creator Profile: avatar, following/followers/likes counts, bio, Videos/Favorites/Liked tabs, video grid. Settings/More menu with dark-mode toggle and log out. Seed with the provided real videos, avatars, users, comments and sounds." \
  > "$LOG" 2>&1 &

sleep 6
PID=$(pgrep -f "env_generator.llm_generator.main" | head -1)
echo "LAUNCHED tiktok-web-r${RUN}  真PID=${PID}  log=$LOG"
echo "(PID 陷阱: 上面取的是 python 真 PID，非 wrapper。监控只 grep 决定性事件；两 run 不并发。)"
