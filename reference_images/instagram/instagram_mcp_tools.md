# Instagram MCP Server — Required Tool Surface

This document specifies the MCP (Model Context Protocol) tools the Instagram
environment's MCP server must provide, so AI agents can operate the app
programmatically. It is adapted from the most complete community Instagram MCP
server (mcpware/instagram-mcp, 23 tools over the Instagram Graph API); tool
names and semantics are kept, backed here by the environment's own API.

## Profile & Account

- `get_profile_info` — retrieve a profile: username, full name, bio, follower
  count, following count, media count.
- `get_account_insights` — account-level analytics: reach, profile views,
  follower growth over a period.
- `validate_access_token` — verify whether the current auth token is valid.

## Media & Publishing

- `get_media_posts` — fetch a user's recent posts with engagement metrics
  (likes, comments) and timestamps.
- `get_media_insights` — detailed analytics for one post: likes, comments,
  saves, reach.
- `publish_media` — upload and publish an image or video post (media URL,
  caption).
- `publish_carousel` — publish a carousel post of 2–10 images/videos.
- `publish_reel` — publish a Reel (short video).
- `get_content_publishing_limit` — remaining daily publishing quota.

## Comments

- `get_comments` — list comments on a post.
- `post_comment` — add a comment to a post.
- `reply_to_comment` — reply to an existing comment (threaded).
- `delete_comment` — remove a comment.
- `hide_comment` — hide or unhide a comment.

## Direct Messages

- `get_conversations` — list DM conversations for the account.
- `get_conversation_messages` — read the messages in one conversation.
- `send_dm` — send a direct message in a conversation.

## Discovery & Content

- `search_hashtag` — resolve a hashtag name to its id.
- `get_hashtag_media` — top/recent posts for a hashtag.
- `get_stories` — currently active stories.
- `get_mentions` — posts where the account is tagged.
- `business_discovery` — look up another account's public profile and stats.

## Behavioral requirements

- Every tool authenticates with the environment's bearer-token auth; an
  invalid/missing token returns an auth error rather than data.
- Publishing tools enforce limits (e.g. 25 posts/day) and report the remaining
  quota via `get_content_publishing_limit`.
- Engagement counts returned by `get_media_posts` / `get_media_insights` must
  reflect real persisted data (a `post_comment` call is visible in the next
  `get_comments` and increments the post's comment count).

Source: https://github.com/mcpware/instagram-mcp
