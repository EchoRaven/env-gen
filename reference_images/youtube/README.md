# YouTube reference screenshots

Compressed to ≤1280 px JPEG (q85) to stay light for context + the visual-fidelity
gate. Originals backed up at `/tmp/youtube_ref_originals/`. The pipeline reads
every image here and maps them to screens — filenames are descriptive hints.

This set covers the **consumer app** *and* **YouTube Studio (creator)**.

## Consumer app
| file | page |
|------|------|
| `youtube_home.jpg` | Home — video grid + left sidebar + top search bar |
| `youtube_shorts.jpg` | Shorts — vertical short-video player |
| `youtube_subscription.jpg` | Subscriptions feed |
| `youtube_you.jpg` | "You" — library / history / your content |
| `youtube_enter_channel.jpg` | A channel page (banner, subscribe, video grid) |
| `youtube_click_notification.jpg` | Notifications panel |
| `youtube_login.jpg` | Login / sign-in |
| `youtube_settings.jpg` | Account settings |
| `youtbue_click_profile.jpg` | Profile / account menu |
| `youtube_click_create_button.jpg` | "Create" button dropdown (upload / shorts / live) |
| `youtube_upload_video.jpg` | Upload a video |

## YouTube Studio (creator)
| file | page |
|------|------|
| `youtube_channel_content.jpg` | Studio → Content (your-videos table) |
| `youtube_channel_analystic.jpg` | Studio → Analytics |
| `youtube_Channel_customization.jpg` | Studio → Customization |
| `youtube_channel_earn.jpg` | Studio → Earn / monetization |
| `youtube_Audio_library.jpg` | Studio → Audio library |

Launch with `./run_youtube.sh` (Gemini). MCP tool surface for the generated env:
see `MCP_TOOLS.md`.
