#!/usr/bin/env bash
# CORE Instagram (~10 endpoints) — scoped to stay under the context-bloat
# threshold that starves implementation at 25-endpoint scale. Auth + home feed +
# profile + create-post + like/comment/follow. Same reference screens for the look.
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
AGENT_DIR="${REPO_ROOT}/agent"
PYTHON_BIN="${PYTHON_BIN:-/home/haibotong/miniconda3/envs/dt/bin/python}"
PROJECT_NAME="${PROJECT_NAME:-instagram-core}"
MODEL="${MODEL:-gpt-5.5}"
PROVIDER="${PROVIDER:-openai}"
OUTPUT_BASE="${OUTPUT_BASE:-${REPO_ROOT}/generated}"
REF_DIR="${REF_DIR:-${REPO_ROOT}/reference_images/instagram}"

[ -f /tmp/envgen_key.sh ] && . /tmp/envgen_key.sh
if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "ERROR: OPENAI_API_KEY not set" >&2; exit 1
fi

read -r -d '' DESCRIPTION <<'EOF' || true
Build a CORE Instagram-style photo-sharing web app (dark theme, left nav rail), kept deliberately
SMALL — the core social loop only. Match the supplied reference screenshots for the look (login,
home feed, profile, create-post).

PAGES:
1. Login + Sign up (login.png / create_account.png): username/email + password.
2. Home feed (home.png): reverse-chronological posts from people the user follows + self; each post
   shows author avatar + username, the image, a like button + like count, a comment count, and the
   caption. A right column lists a few suggested users to follow.
3. Profile (more.png): a user's avatar, username, post/follower/following counts, a Follow/Unfollow
   button (or Edit on your own), and a grid of that user's posts.
4. Create post (create.png): upload an image URL + caption -> publishes; appears in the author's
   profile and followers' feeds.

DATA MODEL (Postgres, every row owned/scoped per authenticated user):
- users: id, username (unique), full_name, email (unique), password_hash, avatar_url, created_at.
- follows: id, follower_id, following_id, created_at.
- posts: id, author_id, image_url, caption, created_at.
- likes: id, post_id, user_id, created_at (unique pair).
- comments: id, post_id, user_id, text, created_at.

KEEP THE API SMALL — exactly these ~10 business endpoints (plus the auth/tenant control surface):
- POST /api/auth/register          (create account)
- POST /api/auth/login             (login -> token)
- GET  /api/users/me               (current user)
- GET  /api/users/{username}       (a profile + counts)
- POST /api/users/{username}/follow   (follow/unfollow toggle)
- POST /api/posts                  (create a post)
- GET  /api/feed                   (home feed: posts by followed users + self, newest first)
- GET  /api/users/{username}/posts (that user's posts, for the profile grid)
- POST /api/posts/{post_id}/like   (like/unlike toggle)
- POST /api/posts/{post_id}/comments (add a comment)

Do NOT add search, explore, reels/video, direct messages, stories, saves, or notifications — those
are out of scope for this core. Include the FastAPI backend (the ~10 endpoints + auth surface), the
React/Vite/Tailwind frontend (the 4 pages, dark Instagram look), the Postgres schema, and seed data:
a few demo users that follow each other with several posts, likes, and comments, so the feed and
profiles are populated on first load.
EOF

# Core scope (~10 endpoints) — give it a generous backstop; watcher is the real key-protection.
export ENVGEN_MAX_WALLCLOCK_SEC="${ENVGEN_MAX_WALLCLOCK_SEC:-7200}"
export ENVGEN_MAX_TICKS="${ENVGEN_MAX_TICKS:-300}"

export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"
mkdir -p "${OUTPUT_BASE}"
cd "${AGENT_DIR}"

echo "CORE Instagram: ${PROJECT_NAME}  model=${MODEL} (${PROVIDER})  output=${OUTPUT_BASE}/${PROJECT_NAME}"
echo "Reference images: ${REF_DIR}"
echo

exec "${PYTHON_BIN}" -m env_generator.llm_generator.main \
  --name "${PROJECT_NAME}" \
  --description "${DESCRIPTION}" \
  --output "${OUTPUT_BASE}" \
  --reference-dir "${REF_DIR}" \
  --provider "${PROVIDER}" \
  --model "${MODEL}" \
  --fresh \
  --log \
  --verbose
