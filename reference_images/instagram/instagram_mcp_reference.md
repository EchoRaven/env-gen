# Instagram MCP Server — Tool Reference

Reference for the FastMCP server this environment must generate. It mirrors the tool
surface of the real, in-production Instagram MCP servers, adapted to this **self-hosted**
app (local Postgres + the app's own FastAPI REST API + the embedded OAuth2 JWT auth —
**not** the live Instagram Graph API).

**Grounded in the most-used community Instagram MCP servers:**
- **`AleemHaider/instagram-mcp`** — 24 tools across five capability areas: profile/media,
  publishing, comments, DMs, insights.
- **`trypeggy/instagram_dm_mcp`** — the most-starred Instagram MCP (direct-messages focus).
- **`anand-kamble/mcp-instagram`** — profiles, timelines, stories + engagement (like,
  comment, follow).
- **`MCPware/instagram-mcp`** — posts, comments, DMs, reels, carousels.

## Design rules for the generated server

1. **1:1 with the REST API.** Every business REST endpoint gets exactly one MCP tool;
   every MCP tool calls one endpoint. No tool without a backing endpoint; no business
   endpoint without a tool.
2. **Naming: `<resource>_<action>`** (camelCase action), collision-free — e.g.
   `posts_create`, `feed_get`, `users_follow`, `posts_addComment`, `messages_send`.
3. **Auth on every tool.** All tools require the signed-in user's bearer JWT and operate
   as that user (per-user scope); no tool takes a `userId`. (`/auth/*` are the AS surface,
   not business tools.)
4. **Shapes mirror the REST envelope.** List → `{items, total}`; single resource →
   `{item}`; mutations → the affected `{item}`; errors → `{detail}` + HTTP status.
5. **Idempotent toggles:** like/unlike, save/unsave, follow/unfollow are safe to repeat.

---

## Users / profile tools  (milestone M1)

| Tool | Mirrors (community IG MCP) | Endpoint | Description |
|---|---|---|---|
| `users_getMe` | profile: `get_me` | `GET /api/users/me` | The signed-in user's profile (username, full_name, bio, avatar, counts). → `{item}` |
| `users_updateMe` | profile: `update_profile` | `PUT /api/users/me` | Update own profile (full_name, bio, avatar_url). → `{item}` |
| `users_get` | profile: `get_user` | `GET /api/users/{username}` | Public profile of a user by username. → `{item}` |
| `users_suggested` | `suggested_users` | `GET /api/users/suggested` | "Suggested for you" users. → `{items,total}` |

## Posts / feed tools  (milestone M2)

| Tool | Mirrors | Endpoint | Description |
|---|---|---|---|
| `posts_create` | publishing: `create_post` | `POST /api/posts` | Create a post: `media_url`, `media_type` (image\|video), `caption`. → `{item}` |
| `feed_get` | `get_timeline` / `get_feed` | `GET /api/feed` | Reverse-chronological home feed of followed users' posts. → `{items,total}` |
| `explore_get` | `get_explore` | `GET /api/explore` | Explore grid of posts/reels beyond the user's follows. → `{items,total}` |
| `users_posts` | media: `get_user_media` | `GET /api/users/{username}/posts` | A user's post grid. → `{items,total}` |
| `posts_get` | media: `get_media` | `GET /api/posts/{post_id}` | A single post (author, media, caption, counts). → `{item}` |
| `posts_delete` | publishing: `delete_media` | `DELETE /api/posts/{post_id}` | Delete the signed-in user's own post. → `{item}` |

## Follow tools  (milestone M3)

| Tool | Mirrors | Endpoint | Description |
|---|---|---|---|
| `users_follow` | engagement: `follow_user` | `POST /api/users/{username}/follow` | Follow a user (idempotent). → `{item}` |
| `users_unfollow` | engagement: `unfollow_user` | `DELETE /api/users/{username}/follow` | Unfollow a user (idempotent). → `{item}` |
| `users_followers` | `get_followers` | `GET /api/users/{username}/followers` | A user's followers list. → `{items,total}` |
| `users_following` | `get_following` | `GET /api/users/{username}/following` | Who a user follows. → `{items,total}` |

## Engagement tools  (milestone M4)

| Tool | Mirrors | Endpoint | Description |
|---|---|---|---|
| `posts_like` | engagement: `like_media` | `POST /api/posts/{post_id}/like` | Like a post (idempotent). → `{item}` |
| `posts_unlike` | engagement: `unlike_media` | `DELETE /api/posts/{post_id}/like` | Remove a like (idempotent). → `{item}` |
| `posts_addComment` | comments: `create_comment` | `POST /api/posts/{post_id}/comments` | Comment on a post (`text`). → `{item}` |
| `posts_listComments` | comments: `list_comments` | `GET /api/posts/{post_id}/comments` | A post's comments. → `{items,total}` |
| `posts_save` | `save_media` | `POST /api/posts/{post_id}/save` | Bookmark/save a post (idempotent). → `{item}` |
| `posts_unsave` | `unsave_media` | `DELETE /api/posts/{post_id}/save` | Remove a save (idempotent). → `{item}` |

## Media / discovery / direct-messages tools  (milestone M5)

| Tool | Mirrors | Endpoint | Description |
|---|---|---|---|
| `reels_list` | media (video): `get_reels` | `GET /api/reels` | Vertical feed of video posts (reels). → `{items,total}` |
| `users_saved` | `get_saved` | `GET /api/users/me/saved` | The signed-in user's saved/bookmarked posts. → `{items,total}` |
| `search_users` | `search_users` | `GET /api/search/users?q=` | Search users by username/name. → `{items,total}` |
| `messages_listConversations` | dm: `list_threads` (trypeggy) | `GET /api/messages/conversations` | DM conversation inbox. → `{items,total}` |
| `messages_getThread` | dm: `get_thread` / `list_messages` | `GET /api/messages/{username}` | Messages in the thread with one user. → `{items,total}` |
| `messages_send` | dm: `send_message` (trypeggy) | `POST /api/messages/{username}` | Send a text DM to a user. → `{item}` |

---

## Conventions

- **One tool per business endpoint**, registered via `mcp_registry_register_server` +
  `mcp_registry_register_tool` (the coverage gate fails delivery if a registered tool has
  no consumer or an endpoint has no tool).
- **Auth:** every tool forwards the signed-in user's bearer token; the endpoint enforces
  per-user ownership (a user only deletes their own posts, sees their own saved/DMs, etc.).
- **Data model (per the milestone spec):** `users`, `follows`, `posts`
  (media_url, media_type, caption), `likes`, `comments`, `saves`, `messages`.
- **Timestamps** ISO 8601; **pagination** `limit` + `offset` on list tools.
- **Errors** propagate the endpoint's `{detail}` + status (401 missing/expired token,
  403/404 on a resource the user doesn't own).
- **Reels** = posts with `media_type='video'`; **Saved** = posts the user bookmarked;
  these are views over the same `posts` table, not separate entities.

## Sources
- [AleemHaider/instagram-mcp (GitHub)](https://github.com/AleemHaider/instagram-mcp) — 24-tool Graph-API server (profile/media, publishing, comments, DMs, insights)
- [trypeggy/instagram_dm_mcp (GitHub)](https://github.com/trypeggy/instagram_dm_mcp) — most-starred Instagram DM MCP
- [anand-kamble/mcp-instagram (GitHub)](https://github.com/anand-kamble/mcp-instagram) — profiles/timelines/stories + like/comment/follow
- [MCPware/instagram-mcp (GitHub)](https://github.com/MCPware/instagram-mcp) — posts/comments/DMs/reels/carousels
