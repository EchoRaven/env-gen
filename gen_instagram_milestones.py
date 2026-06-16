#!/usr/bin/env python3
"""Multi-milestone breakdown for full Instagram -> instagram_milestones.json.

5 SMALL slices (~6 business endpoints each) so every milestone stays well under the
~770-message saturation wall and can run with condensation DISABLED (the only regime
proven to let the coding lane implement — exactly how instagram-core's 8-endpoint
single milestone delivers). Full DATA MODEL repeated in each (table reg is idempotent).
"""
import json

DM = """DATA MODEL (Postgres, every business row owned/scoped per authenticated user):
- users: id, username (unique), full_name, email (unique), password_hash, bio, avatar_url, created_at.
- follows: id, follower_id, following_id, created_at (unique pair).
- posts: id, author_id, media_url, media_type ('image' | 'video'), caption, created_at.
- likes: id, post_id, user_id, created_at (unique pair).
- comments: id, post_id, user_id, text, created_at.
- saves: id, post_id, user_id, created_at (unique pair).
- messages: id, sender_id, recipient_id, text, created_at."""

BUILD = ("MILESTONE {m} — building on the ALREADY-DELIVERED earlier milestones (auth/profile"
         "{ctx} already work and are deployed). The endpoints below are NEW; do NOT re-implement"
         " existing ones (visible via apihub_list_endpoints as `implemented`).")

def slice_text(header, pages, endpoints, extra=""):
    eps = "\n".join(f"- {e}" for e in endpoints)
    return f"""{header}

PAGES:
{pages}

{DM}

NEW API ENDPOINTS (FastAPI, JWT auth):
{eps}

{extra}""".strip()

M1 = slice_text(
    "Build the core of an Instagram-style photo/video social app (web, dark theme, left nav rail). "
    "MILESTONE M1 — authentication + user profiles.",
    "1. Login: username/email + password.\n2. Sign up: email, password, full name, username.\n"
    "3. Profile: avatar, username, display name, counts, Edit profile (own).",
    ["POST /auth/register","POST /auth/login","GET /api/users/me","PUT /api/users/me",
     "GET /api/users/suggested","GET /api/users/{username}"],
    "Include FastAPI backend, React/Vite/Tailwind frontend (login, signup, profile pages, dark "
    "Instagram look + left nav rail), Postgres schema for the full data model, and seed demo users.")

M2 = slice_text(
    BUILD.format(m="M2", ctx="") + " Add POSTS + the HOME FEED.",
    "- Home feed: reverse-chronological posts (author avatar+username, image, caption, timestamp); "
    "right column current-user + Suggested.\n- Create new post: upload image (or URL) + caption.\n"
    "- Profile: grid of the user's posts.",
    ["POST /api/posts","GET /api/feed","GET /api/explore","GET /api/users/{username}/posts",
     "GET /api/posts/{post_id}","DELETE /api/posts/{post_id}"],
    "Wire these into the existing frontend (feed page, create-post modal, profile post grid).")

M3 = slice_text(
    BUILD.format(m="M3", ctx="/posts/feed") + " Add FOLLOW.",
    "- Profile & feed: Follow/Unfollow button; follower/following counts and lists.",
    ["POST /api/users/{username}/follow","DELETE /api/users/{username}/follow",
     "GET /api/users/{username}/followers","GET /api/users/{username}/following"],
    "Wire follow/unfollow buttons + followers/following lists into the existing frontend.")

M4 = slice_text(
    BUILD.format(m="M4", ctx="/posts/feed/follow") + " Add ENGAGEMENT (likes, comments, saves).",
    "- Each post: action row like / comment / save, like count, a comments view.",
    ["POST /api/posts/{post_id}/like","DELETE /api/posts/{post_id}/like",
     "POST /api/posts/{post_id}/comments","GET /api/posts/{post_id}/comments",
     "POST /api/posts/{post_id}/save","DELETE /api/posts/{post_id}/save"],
    "Wire the like/comment/save action row + comments view into the existing frontend.")

M5 = slice_text(
    BUILD.format(m="M5", ctx="/posts/feed/follow/engagement") + " Add REELS, SAVED, SEARCH, DIRECT MESSAGES.",
    "- Reels: vertical video player of video posts.\n- Saved: grid of bookmarked posts.\n"
    "- Explore/Search: search users.\n- Direct Messages: conversation inbox; open + send text messages.",
    ["GET /api/reels","GET /api/users/me/saved","GET /api/search/users",
     "GET /api/messages/conversations","GET /api/messages/{username}","POST /api/messages/{username}"],
    "Wire Reels, Saved, Search/Explore, and Direct Messages pages into the left nav rail.")

milestones = [
    {"name":"M1-auth-profile","version":"1.0.0","description_slice":M1},
    {"name":"M2-posts-feed","version":"1.1.0","description_slice":M2},
    {"name":"M3-follow","version":"1.2.0","description_slice":M3},
    {"name":"M4-engagement","version":"1.3.0","description_slice":M4},
    {"name":"M5-media-dms","version":"1.4.0","description_slice":M5},
]
out="/data/common/haibotong/env-gen/instagram_milestones.json"
json.dump(milestones, open(out,"w"), indent=2)
total=sum(s["description_slice"].count("\n- /") + s["description_slice"].count("\n- POST") +
          s["description_slice"].count("\n- GET") + s["description_slice"].count("\n- PUT") +
          s["description_slice"].count("\n- DELETE") for s in milestones)
print(f"wrote {out}: {len(milestones)} milestones")
for m in milestones:
    n=sum(m["description_slice"].count(f"\n- {v} ") for v in ("POST","GET","PUT","DELETE"))
    print(f"  {m['name']} ({m['version']}): {n} endpoints")
