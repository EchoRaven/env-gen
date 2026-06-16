#!/usr/bin/env bash
# YouTube-style video platform generation via the forgingground retarget pipeline.
# A complex, non-social target (multi-entity catalog: channels -> videos ->
# comments/likes/subscriptions/playlists) used as a runtime generality test.
# Feeds the reference screenshots in reference_images/youtube.
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
AGENT_DIR="${REPO_ROOT}/agent"
PYTHON_BIN="${PYTHON_BIN:-/home/haibotong/miniconda3/envs/dt/bin/python}"
PROJECT_NAME="${PROJECT_NAME:-youtube}"
MODEL="${MODEL:-gemini-3.1-pro-preview}"
PROVIDER="${PROVIDER:-google}"
OUTPUT_BASE="${OUTPUT_BASE:-${REPO_ROOT}/generated}"
REF_DIR="${REF_DIR:-${REPO_ROOT}/reference_images/youtube}"

# Source the API key if dropped at /tmp/envgen_key.sh (export GOOGLE_API_KEY=...).
[ -f /tmp/envgen_key.sh ] && . /tmp/envgen_key.sh
if [ -z "${GOOGLE_API_KEY:-}" ]; then
  echo "ERROR: GOOGLE_API_KEY not set (export it or put it in /tmp/envgen_key.sh)" >&2
  exit 1
fi

read -r -d '' DESCRIPTION <<'EOF' || true
Build a complete YouTube-style video sharing platform (web app, light theme, a left navigation
sidebar and a top search bar with a red accent). Match the supplied reference screenshots.

PAGES (each corresponds to a reference screenshot):
1. Home (home.png): a top bar with the logo, a centered search box, and a sign-in/avatar; a left
   sidebar (Home, Subscriptions, Library, History, Your videos); the main area is a responsive grid
   of video cards — each card shows the thumbnail, title, channel name, view count, relative upload
   time, and a channel avatar.
2. Watch (watch.png): the watch page — a large player area (poster/thumbnail + title), the video
   title, channel avatar + name + subscriber count + a "Subscribe" button, a like/dislike row and
   view count, an expandable description, and a comments section (count, add a comment, list of
   comments with author + text + time). A right column lists "Up next" recommended videos.
3. Channel (channel.png): a channel page — banner image, channel avatar, name, @handle, subscriber
   count, a "Subscribe" button, tabs (Videos / About), and a grid of that channel's videos.
4. Search results (search.png): the search box populated with a query over a vertical list of
   matching videos (thumbnail + title + channel + views + time + a description snippet).
5. Subscriptions (subscriptions.png): the latest videos from channels the signed-in user subscribes
   to, newest first.
6. Library (library.png): the signed-in user's library — watch history, liked videos, and playlists.
(Auth: a simple Login / Sign-up with email + password; synthesize a minimal one if no reference.)

DATA MODEL (Postgres, business rows scoped per authenticated user):
- users: id, username (unique), email (unique), password_hash, avatar_url, created_at.
- channels: id, owner_id (-> users), name, handle (unique), description, avatar_url, banner_url, created_at.
- videos: id, channel_id (-> channels), title, description, thumbnail_url, video_url, views, created_at.
- subscriptions: id, subscriber_id (-> users), channel_id (-> channels), created_at (unique pair).
- video_likes: id, video_id (-> videos), user_id (-> users), value ('like' | 'dislike'), created_at (unique per user+video).
- comments: id, video_id (-> videos), user_id (-> users), text, created_at.
- playlists: id, owner_id (-> users), title, created_at.
- playlist_items: id, playlist_id (-> playlists), video_id (-> videos), position.
- watch_history: id, user_id (-> users), video_id (-> videos), watched_at.

CORE BEHAVIORS / ENDPOINTS (FastAPI, JWT auth):
- Auth: register, login, get current user.
- Channels: create / get own channel, get a channel by handle (with its videos + subscriber count), update own channel.
- Videos: home feed (recent/popular videos), get a single video (increments view count) with its comments,
  list a channel's videos, search videos by title/description, upload a video (title, description,
  thumbnail URL, video URL), delete own video, subscription feed (videos from subscribed channels, newest first).
- Subscriptions: subscribe / unsubscribe a channel; list the user's subscriptions.
- Engagement: like / dislike a video (toggle), add / list comments on a video.
- Library: watch history (record + list), liked videos, playlists CRUD (+ add / remove a video to a playlist).

Include the FastAPI backend (all endpoints above + the auth/tenant control surface), the
React/Vite/Tailwind frontend (all pages above; the YouTube look: white surface, left sidebar, top
search bar, red accent), the Postgres schema for the data model, and seed data: several demo channels
each with a handful of videos (thumbnails via placeholder image URLs), some subscriptions, likes,
comments, and a playlist, so the home grid, watch page, channels, search, subscriptions and library
are populated on first load.
EOF

# Very high backstops only (the external watcher is the real-time protection).
export ENVGEN_MAX_WALLCLOCK_SEC="${ENVGEN_MAX_WALLCLOCK_SEC:-21600}"
export ENVGEN_MAX_TICKS="${ENVGEN_MAX_TICKS:-1200}"

export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"
mkdir -p "${OUTPUT_BASE}"
cd "${AGENT_DIR}"

echo "YouTube generation: ${PROJECT_NAME}  model=${MODEL} (${PROVIDER})  output=${OUTPUT_BASE}/${PROJECT_NAME}"
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
