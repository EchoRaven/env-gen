# YouTube env — MCP tool surface

Modeled on [ZubeidHendricks/youtube-mcp-server](https://github.com/ZubeidHendricks/youtube-mcp-server)
(its `<resource>_<action>` naming + capability categories), **adapted for this
generated env**: that reference is a read-only proxy onto the public YouTube Data
API, whereas this env is a self-contained clone with its own Postgres data + an
embedded OAuth2 AS — so the MCP server exposes the reference's **read** tools
*and* the **write** tools our authenticated endpoints support.

The FastMCP server is projected from the app's business endpoints (it mirrors the
API contract 1:1). Conventions:
- Each tool maps to one `/api/*` endpoint; auth tools send the bearer token from
  the embedded AS. Read tools are anonymous-safe; write tools require auth.
- Responses follow the fixed envelope: a single resource → `{item}`, a list →
  `{items, total}`.

## Read tools (mirror the reference server)

| tool | maps to | params | returns |
|------|---------|--------|---------|
| `videos_searchVideos` | `GET /api/videos/search` | `query` (req), `maxResults?`, `order?` (`recent`\|`popular`), `channelId?` | `{items, total}` of videos |
| `videos_getVideo` | `GET /api/videos/{videoId}` | `videoId` (req) | `{item}` — video + channel + view/like/comment counts (records a view) |
| `videos_listFeed` | `GET /api/videos` (home feed) | `maxResults?`, `order?` | `{items, total}` recent/popular videos |
| `channels_getChannel` | `GET /api/channels/{handle}` | `handle` or `channelId` (req) | `{item}` — channel + subscriber count |
| `channels_listVideos` | `GET /api/channels/{channelId}/videos` | `channelId` (req), `maxResults?` | `{items, total}` of the channel's videos |
| `channels_searchChannels` | `GET /api/channels/search` | `query` (req), `maxResults?` | `{items, total}` of channels |
| `playlists_getPlaylist` | `GET /api/playlists/{playlistId}` | `playlistId` (req) | `{item}` — playlist metadata |
| `playlists_getPlaylistItems` | `GET /api/playlists/{playlistId}/items` | `playlistId` (req), `maxResults?` | `{items, total}` videos in the playlist |
| `comments_listComments` | `GET /api/videos/{videoId}/comments` | `videoId` (req) | `{items, total}` of comments |

## Write tools (this env adds these — authenticated)

| tool | maps to | params |
|------|---------|--------|
| `videos_uploadVideo` | `POST /api/videos` | `title` (req), `description`, `thumbnailUrl`, `videoUrl` |
| `videos_deleteVideo` | `DELETE /api/videos/{videoId}` | `videoId` (req) |
| `videos_rateVideo` | `POST /api/videos/{videoId}/like` | `videoId` (req), `value` (`like`\|`dislike`) |
| `comments_addComment` | `POST /api/videos/{videoId}/comments` | `videoId` (req), `text` (req) |
| `subscriptions_subscribe` | `POST /api/channels/{channelId}/subscribe` | `channelId` (req) |
| `subscriptions_unsubscribe` | `DELETE /api/channels/{channelId}/subscribe` | `channelId` (req) |
| `subscriptions_listSubscriptions` | `GET /api/subscriptions` | — |
| `videos_listSubscriptionFeed` | `GET /api/videos/subscriptions` | `maxResults?` |
| `channels_updateChannel` | `PATCH /api/channels/me` | `name?`, `description?`, `avatarUrl?`, `bannerUrl?` |
| `playlists_createPlaylist` | `POST /api/playlists` | `title` (req) |
| `playlists_addItem` | `POST /api/playlists/{playlistId}/items` | `playlistId` (req), `videoId` (req) |
| `playlists_removeItem` | `DELETE /api/playlists/{playlistId}/items/{videoId}` | `playlistId` (req), `videoId` (req) |
| `library_watchHistory` | `GET /api/library/history` | — |
| `library_likedVideos` | `GET /api/library/liked` | — |

## Capability categories
- **Video management** — search, detail, feed, upload, delete, rate
- **Channels** — lookup, search, list-videos, update-own, subscribe/unsubscribe
- **Playlists** — read items, create, add/remove items
- **Engagement** — comments (list/add), likes/dislikes
- **Library** — watch history, liked videos, subscription feed

## Divergences from the reference
- `transcripts_getTranscript` is **omitted**: a self-contained clone has no real
  audio/video to transcribe. If desired later, add a `transcript`/`captions`
  text column on `videos` and a `videos_getTranscript(videoId)` read tool.
- `channels_findCreators` / multi-id `channels_getChannels` are folded into
  `channels_searchChannels` + repeated `channels_getChannel`.
