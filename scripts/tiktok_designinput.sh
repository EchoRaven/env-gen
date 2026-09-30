#!/usr/bin/env bash
# TikTok 环境生成脚本（design-input 全栈）— 可移植版
#
# 用法:
#   export ENVGEN_KEY_FILE=/path/to/key.sh       # 推荐: 里面 export ENVGEN_PROVIDER/MODEL/LLM_KEY
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

# #1202lp: RESUME=1 续跑同名 run，而不是从零开跑。
#
# 这个脚本一直只会起全新 run，于是每次续跑都要手敲一遍 main.py 命令 —— 而手敲版本漏过
# provider key 桥接（key 文件只给 ENVGEN_LLM_KEY，main.py 找的是 OPENAI_API_KEY），
# run 起来第一次 LLM 调用就 401。同一个桥接在本脚本里写得好好的，只是续跑走不到它。
#
# r121 就是该续跑的典型：2 小时墙钟到顶未交付，但 28 端点 / 13 表 / 12 页 / 全部
# verification 绿都已经在盘上，交付门禁一度完全清空。从零再来是把这些全扔掉。
#
# ENVGEN_MAX_WALLCLOCK_SEC 会盖掉台账里存的上限（#1202ii），续跑时通常要调大 —— 
# 台账里那个 7200 是上一个进程的数，不是这次的意图。
RESUME="${RESUME:-0}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # 脚本在 scripts/ 下，上一级是仓库根
PYTHON="${PYTHON:-python}"
LOG="$ROOT/gm_tiktok_r${RUN}.log"
DI="${ENVGEN_DESIGN_INPUT:-$ROOT/design_inputs/tiktok}"

# #1202z1: THE CALLER'S BUDGET SURVIVES THE KEY FILE.
#
# The key file's job is credentials and prices. It also happens to export
# ENVGEN_MAX_SPEND_USD, and the `source` below is unconditional — so a launch that set a
# cap for THIS run got the key file's number instead, silently. Caught live: r141 was
# launched with ENVGEN_MAX_SPEND_USD=450 against a remaining budget of ~$880 and came up
# with 900 in /proc/<pid>/environ. Nothing said so; the only reason it was noticed is that
# the launcher reads the environment back after starting.
#
# Same family as #1202wz (three providers reached no spend cap at all): a cap that does not
# hold is worse than no cap, because it is believed. Every budget knob is captured here and
# restored after the source, and the override is ANNOUNCED — a silent restore would be the
# mirror image of the defect.
_CALLER_BUDGET_1202Z1=""
for _k1202z1 in ENVGEN_MAX_SPEND_USD ENVGEN_MAX_WALLCLOCK_SEC ENVGEN_MAX_TICKS \
                ENVGEN_DELIVERY_OVERSHOOT ENVGEN_CONVERGING_OVERSHOOT; do
  eval "_v1202z1=\${$_k1202z1:-}"
  [ -n "$_v1202z1" ] && _CALLER_BUDGET_1202Z1="$_CALLER_BUDGET_1202Z1 $_k1202z1=$_v1202z1"
done

# --- key: 从 ENVGEN_KEY_FILE 加载（可选），或要求环境里已有 GOOGLE_API_KEY（不硬编码任何路径/密钥）---
if [ -n "${ENVGEN_KEY_FILE:-}" ] && [ -f "${ENVGEN_KEY_FILE}" ]; then
  # shellcheck disable=SC1090
  source "${ENVGEN_KEY_FILE}"
fi

# #1202z1: ...and now the caller's numbers go back, loudly.
for _kv1202z1 in $_CALLER_BUDGET_1202Z1; do
  _k1202z1="${_kv1202z1%%=*}"; _v1202z1="${_kv1202z1#*=}"
  eval "_now1202z1=\${$_k1202z1:-}"
  if [ "$_now1202z1" != "$_v1202z1" ]; then
    echo "[launch] #1202z1: the key file set $_k1202z1=${_now1202z1:-unset}, the caller asked for $_v1202z1 — the caller wins."
  fi
  export "$_k1202z1=$_v1202z1"
done
# #1202km: provider/model 从 key 文件读，不再硬编码。
# 这个脚本长期写死 `--provider google --model gemini-3.1-pro-preview-customtools`，
# 而 key 文件 2026-09-06 起已经是直连 OpenAI(gpt-5.5)。任何照着 usage 跑的人都会被
# "REFUSED: GOOGLE_API_KEY 未设置" 挡住，或者更糟——用一个没人再用的 provider 烧钱。
PROVIDER="${ENVGEN_PROVIDER:-openai}"
MODEL="${ENVGEN_MODEL:-}"
[ -n "$MODEL" ] || { echo "REFUSED: ENVGEN_MODEL 未设置（用 ENVGEN_KEY_FILE 指向 key 脚本，或自己 export）" >&2; exit 1; }

# main.py 按 provider 找对应的 KEY 环境变量（openai→OPENAI_API_KEY）；key 文件只给
# ENVGEN_LLM_KEY，所以在这里补上桥接，否则 run 起来第一次 LLM 调用就 401。
case "$PROVIDER" in
  openai) export OPENAI_API_KEY="${OPENAI_API_KEY:-${ENVGEN_LLM_KEY:-}}"
          [ -n "${OPENAI_API_KEY:-}" ] || { echo "REFUSED: OPENAI_API_KEY/ENVGEN_LLM_KEY 未设置" >&2; exit 1; } ;;
  google) [ -n "${GOOGLE_API_KEY:-}" ] || { echo "REFUSED: GOOGLE_API_KEY 未设置" >&2; exit 1; } ;;
  anthropic) export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-${ENVGEN_LLM_KEY:-}}"
          [ -n "${ANTHROPIC_API_KEY:-}" ] || { echo "REFUSED: ANTHROPIC_API_KEY/ENVGEN_LLM_KEY 未设置" >&2; exit 1; } ;;
  *) echo "REFUSED: 未知 ENVGEN_PROVIDER=$PROVIDER" >&2; exit 1 ;;
esac

# --- PYTHON 可用性（#1202zj）---
# 这个脚本长期把 $PYTHON 的第一次使用放在 playwright 预检（曾在 line 112），所以一个没设
# PYTHON 的调用者拿到的是一句裸的 `python: command not found`，而不是它该听到的话。
# 凭据预检现在是第一次使用，所以检查搬到这里。
command -v "$PYTHON" >/dev/null 2>&1 || {
  echo "REFUSED: PYTHON=$PYTHON 不可执行。export PYTHON=/path/to/venv/bin/python（要装了本仓库依赖 + playwright 的那个）" >&2
  exit 1; }

# --- 凭据预检（#1202zj）---
# 上面的 case 只检查 key 是否 EXISTS，从不检查它答不答。r141 六道预检全过，然后 82.7 秒后
# 死在 429 insufficient_quota —— 进程墙钟 612 秒，换一次 HTTP 调用两秒就能知道。
# 只在明确的认证/额度答复上拒绝；超时/DNS/5xx/裸 429 只警告不拦（瞬时故障不该变成假拒绝，
# #1174 为这个区分付过两次代价）。ENVGEN_PREFLIGHT=0 可整体跳过。
"$PYTHON" "$ROOT/scripts/preflight_credential.py"; PF_RC=$?
if [ "$PF_RC" = "1" ]; then
  echo "REFUSED: 凭据预检失败（见上）。先解决它，别烧一轮墙钟去重新发现。" >&2
  exit 1
fi

# --- 两 run 不并发 ---
# #1202km: `[e]` 防止 pgrep 匹配到调用者自己的命令行（同一天在别处踩过：pkill -f 杀掉了自己）。
if pgrep -f "[e]nv_generator.llm_generator.main" >/dev/null; then
  echo "REFUSED: another env_generator run is live (两 run 不并发)。先等它收官或 kill 后再启。" >&2
  pgrep -af "[e]nv_generator.llm_generator.main" >&2
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
RESUME_ARG=()
if [ "$RESUME" = "1" ]; then
  OUT="$ROOT/generated/tiktok-web-r${RUN}"
  [ -d "$OUT" ] || { echo "REFUSED: RESUME=1 但 $OUT 不存在，没有可续的 run" >&2; exit 1; }
  RESUME_ARG=(--resume)
  LOG="$ROOT/gm_tiktok_r${RUN}-resume$(date +%H%M).log"
  echo "RESUME: 续跑 tiktok-web-r${RUN}（墙钟上限 ${ENVGEN_MAX_WALLCLOCK_SEC:-台账存值}）→ $LOG"
fi

setsid "$PYTHON" -m env_generator.llm_generator.main \
  --name "tiktok-web-r${RUN}" \
  ${RESUME_ARG[@]+"${RESUME_ARG[@]}"} \
  --output "$ROOT/generated" \
  --design-input "$DI" \
  --provider "$PROVIDER" --model "$MODEL" \
  --description "TikTok web clone (desktop web, dark theme, brand red #FE2C55). Auth: login modal (QR / phone-email / social) + signup. Left nav sidebar (For You, Explore, Following, Friends, LIVE, Messages, Activity, Upload, Profile, More). For You feed: vertical 9:16 video with mute toggle, progress bar, bottom-left caption + sound name, right action rail (follow, like, comment, save, share with counts) and up/down nav. Comments panel: comment list with likes/replies and log-in-to-comment. Explore masonry grid with category tabs. Following and Friends suggested-creator grids with red Follow buttons. LIVE/Discover with its own sidebar and live cards showing viewer counts. Messages: DM conversation list + empty chat pane. Activity/notifications with tabs (All, Likes, Comments, Mentions, Followers). Creator Profile: avatar, following/followers/likes counts, bio, Videos/Favorites/Liked tabs, video grid. Settings/More menu with dark-mode toggle and log out. Seed with the provided real videos, avatars, users, comments and sounds." \
  > "$LOG" 2>&1 &

sleep 6
PID=$(pgrep -f "env_generator.llm_generator.main" | head -1)
echo "LAUNCHED tiktok-web-r${RUN}  真PID=${PID}  log=$LOG"
echo "(PID 陷阱: 上面取的是 python 真 PID，非 wrapper。监控只 grep 决定性事件；两 run 不并发。)"
