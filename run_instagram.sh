#!/usr/bin/env bash
# Full Instagram generation via the forgingground retarget pipeline.
# Bigger target than the notes smoke: 8 reference screens (login, signup, home
# feed, explore/search, create-post, reels, direct messages, profile+settings),
# ~25-30 endpoints. Feeds the 8 reference screenshots in reference_images/instagram.
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
AGENT_DIR="${REPO_ROOT}/agent"
PYTHON_BIN="${PYTHON_BIN:-/home/haibotong/miniconda3/envs/dt/bin/python}"
PROJECT_NAME="${PROJECT_NAME:-instagram}"
MODEL="${MODEL:-gpt-5.4}"
PROVIDER="${PROVIDER:-openai}"
OUTPUT_BASE="${OUTPUT_BASE:-${REPO_ROOT}/generated}"
REF_DIR="${REF_DIR:-${REPO_ROOT}/reference_images/instagram}"

# Source the API key if dropped at /tmp/envgen_key.sh (export OPENAI_API_KEY=...).
[ -f /tmp/envgen_key.sh ] && . /tmp/envgen_key.sh
if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "ERROR: OPENAI_API_KEY not set (export it or put it in /tmp/envgen_key.sh)" >&2
  exit 1
fi

read -r -d '' DESCRIPTION <<'EOF' || true
Build a complete Instagram-style photo & video sharing social network (web app, dark theme).
Match the supplied reference screenshots: a left vertical navigation rail (Home, Search/Explore,
Reels, Messages, Notifications, Create, Profile) and a centered content column.

PAGES (each corresponds to a reference screenshot):
1. Login (login.png): username/email + password, "Log in", "Forgot password?", "Create new account".
2. Sign up (create_account.png): email or mobile, password, birthday, full name, username -> creates account.
3. Home feed (home.png): reverse-chronological posts from people the signed-in user follows; each post
   shows author avatar + username + "Follow", the image, action row (like / comment / share / save),
   like count, caption, and a relative timestamp. Right column shows the current user + a
   "Suggested for you" list of users to follow.
4. Explore / Search (search.png): a top search box (search users) over a grid of popular posts.
5. Create new post (create.png): a "Create new post" modal — upload an image (or paste an image URL)
   and write a caption, then publish; the new post appears in the author's profile and followers' feeds.
6. Reels (video.png): a vertical video player showing video posts, with like / comment / share / save
   actions, the author username + "Follow", and caption/hashtags.
7. Direct Messages (profile.png): a messages inbox listing conversations; open a conversation to read
   and send text messages to another user.
8. Profile (more.png): a user's profile — avatar, username, display name, post / follower / following
   counts, "Edit profile" (own) or "Follow"/"Unfollow" (others), and a grid of that user's posts.
   A "More" menu offers Settings / Log out.

DATA MODEL (Postgres, every business row owned/scoped per authenticated user):
- users: id, username (unique), full_name, email (unique), password_hash, bio, avatar_url, created_at.
- follows: id, follower_id, following_id, created_at (a user follows another user; unique pair).
- posts: id, author_id, media_url, media_type ('image' | 'video'), caption, created_at.
- likes: id, post_id, user_id, created_at (unique pair).
- comments: id, post_id, user_id, text, created_at.
- saves: id, post_id, user_id, created_at (bookmarks; unique pair).
- messages: id, sender_id, recipient_id, text, created_at (direct messages between two users).

CORE BEHAVIORS / ENDPOINTS (FastAPI, JWT auth):
- Auth: register, login, get current user.
- Users: get profile by username (with counts), edit own profile, list "suggested" users to follow.
- Follow: follow / unfollow a user; followers & following lists.
- Posts: create a post, get the home feed (posts by followed users + self), list a user's posts,
  list explore posts (recent/popular), get a single post, delete own post.
- Reels: list video posts.
- Engagement: like / unlike a post, add / list comments, save / unsave a post, list saved posts.
- Direct messages: list conversations, list messages in a conversation, send a message.

Include the FastAPI backend (all endpoints above + the auth/tenant control surface), the
React/Vite/Tailwind frontend (all 8 pages above, dark Instagram look with the left nav rail), the
Postgres schema for the data model, and seed data: a handful of demo users that follow each other,
several posts (image + video) with likes and comments, and a couple of direct-message threads, so the
feed, explore grid, reels, profiles and DMs are populated on first load.
EOF

# Budget: full Instagram is a big build — do NOT cap it tightly (per request,
# let it run to completion). These are very high backstops only (the external
# watcher is the real-time key protection: it kills post-impl spins + kickoff
# hangs early). Effectively "no limit" for a healthy run. Override-able.
export ENVGEN_MAX_WALLCLOCK_SEC="${ENVGEN_MAX_WALLCLOCK_SEC:-21600}"
export ENVGEN_MAX_TICKS="${ENVGEN_MAX_TICKS:-1200}"

export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"
mkdir -p "${OUTPUT_BASE}"
cd "${AGENT_DIR}"

echo "Instagram generation: ${PROJECT_NAME}  model=${MODEL} (${PROVIDER})  output=${OUTPUT_BASE}/${PROJECT_NAME}"
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
