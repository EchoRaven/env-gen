#!/usr/bin/env bash
# YouTube-style video platform generation via the forgingground retarget pipeline.
# A complex, non-social target: the consumer app AND a Creator Studio (channels ->
# videos -> comments/likes/subscriptions/playlists/notifications + studio content/
# analytics/customization/monetization/audio-library). Runtime generality test.
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
sidebar, a top search bar with a red accent) INCLUDING a Creator Studio. Match the supplied
reference screenshots.

CONSUMER PAGES:
1. Home (youtube_home): top bar (logo, centered search box, sign-in/avatar), left sidebar (Home,
   Shorts, Subscriptions, You, History); main area is a responsive grid of video cards — thumbnail,
   title, channel name + avatar, view count, relative upload time.
2. Watch: a video page — large player area (poster/thumbnail + title), the title, channel avatar +
   name + subscriber count + a Subscribe button, a like/dislike row + view count, an expandable
   description, and a comments section (count, add a comment, list with author + text + time); a
   right "Up next" column of recommended videos.
3. Shorts (youtube_shorts): a vertical short-video player (full-height card) with like/dislike,
   comment, share actions, the author + Subscribe, and a caption; scroll to the next short.
4. Channel (youtube_enter_channel): banner, avatar, name, @handle, subscriber count, a Subscribe
   button, tabs (Videos / About), and a grid of that channel's videos.
5. Search results: the search box with a query over a vertical list of matching videos (thumbnail,
   title, channel, views, time, description snippet).
6. Subscriptions (youtube_subscription): latest videos from subscribed channels, newest first.
7. You / Library (youtube_you): the user's library — watch history, liked videos, and playlists.
8. Notifications (youtube_click_notification): a panel/list of notifications (new uploads from
   subscriptions, comment replies), newest first, with read/unread state.
9. Settings (youtube_settings): account settings — profile, channel, privacy toggles.
10. Login (youtube_login): email + password sign-in / sign-up.

CREATOR STUDIO PAGES (the signed-in user's own channel; reached from the avatar / Create menu):
11. Upload (youtube_upload_video): upload a video — title, description, thumbnail URL, video URL,
    visibility (public/unlisted/private); publishing adds it to the channel + feeds.
12. Studio Content (youtube_channel_content): a table of the creator's own videos — thumbnail+title,
    visibility, upload date, views, comments, likes; row actions Edit (title/description/visibility)
    and Delete.
13. Studio Analytics (youtube_channel_analystic): a dashboard of the channel's aggregate stats —
    total views, total watch time, subscriber count, and a "top videos" list ranked by views (numbers
    computed from the data; simple stat cards / bars are fine, no charting library required).
14. Studio Customization (youtube_Channel_customization): edit channel branding — name, @handle,
    description, avatar URL, banner URL.
15. Studio Earn / Monetization (youtube_channel_earn): a monetization status page — eligibility
    against thresholds (e.g. >= 1000 subscribers AND a watch-hours bar) and a DISPLAY-ONLY estimated
    revenue computed from total views (no real payments).
16. Studio Audio Library (youtube_Audio_library): a browsable/searchable table of royalty-free audio
    tracks (title, artist, genre, duration) a creator can use; a "Use" / "Download" action.

DATA MODEL (Postgres, business rows scoped per authenticated user):
- users: id, username (unique), email (unique), password_hash, avatar_url, created_at.
- channels: id, owner_id (-> users), name, handle (unique), description, avatar_url, banner_url, created_at.
- videos: id, channel_id (-> channels), title, description, thumbnail_url, video_url,
  kind ('video' | 'short'), visibility ('public' | 'unlisted' | 'private'), views, created_at.
- subscriptions: id, subscriber_id (-> users), channel_id (-> channels), created_at (unique pair).
- video_likes: id, video_id (-> videos), user_id (-> users), value ('like' | 'dislike'), created_at (unique per user+video).
- comments: id, video_id (-> videos), user_id (-> users), text, created_at.
- playlists: id, owner_id (-> users), title, created_at.
- playlist_items: id, playlist_id (-> playlists), video_id (-> videos), position.
- watch_history: id, user_id (-> users), video_id (-> videos), watched_at.
- notifications: id, user_id (-> users), kind, message, video_id (-> videos, nullable), is_read, created_at.
- audio_tracks: id, title, artist, genre, duration_seconds, audio_url, created_at (a SHARED library, not user-owned).

CORE BEHAVIORS / ENDPOINTS (FastAPI, JWT auth):
- Auth: register, login, get current user.
- Channels: create / get own channel (GET /api/channels/me), get a channel by handle (with videos +
  subscriber count), update own channel (customization).
- Videos: home feed (recent/popular), get a single video (increments views) with comments, list a
  channel's videos, list shorts, search videos by title/description, upload a video, edit own video
  (title/description/visibility), delete own video, subscription feed (videos from subscribed
  channels, newest first).
- Subscriptions: subscribe / unsubscribe a channel; list the user's subscriptions.
- Engagement: like / dislike a video (toggle), add / list comments on a video.
- Library: watch history (record + list), liked videos, playlists CRUD (+ add / remove a video).
- Notifications: list the user's notifications, mark read.
- Studio: list the creator's own videos with per-video stats; channel analytics (aggregate
  views / watch-time / subscribers + top videos); monetization status (computed eligibility +
  estimated revenue); audio library (list / search tracks).

MCP TOOLS (FastMCP server mirroring the API 1:1, <resource>_<action> naming, modeled on the
youtube-mcp-server design): read tools videos_searchVideos / videos_getVideo / videos_listFeed /
videos_listShorts / channels_getChannel / channels_getMyChannel / channels_listVideos /
channels_searchChannels / playlists_getPlaylist / playlists_getPlaylistItems / comments_listComments /
notifications_list / studio_listMyVideos / studio_getAnalytics / studio_getMonetization /
audio_searchTracks, plus authenticated write tools videos_uploadVideo / videos_updateVideo /
videos_deleteVideo / videos_rateVideo / comments_addComment / subscriptions_subscribe /
subscriptions_unsubscribe / channels_updateChannel / playlists_createPlaylist / playlists_addItem /
notifications_markRead — one tool per business endpoint.

Include the FastAPI backend (all endpoints above + the auth/tenant control surface), the
React/Vite/Tailwind frontend (all pages above; the YouTube look: white surface, left sidebar, top
search bar with a red accent, and the distinct Studio layout for creator pages), the Postgres schema,
and seed data: several demo channels each with a handful of videos (some marked 'short') with
placeholder thumbnail URLs, subscriptions between them, likes, comments, a playlist, a few audio
tracks, and some notifications — so home, shorts, watch, channels, search, subscriptions, library,
Studio content / analytics / customization / earn, and the audio library are all populated on first load.
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
