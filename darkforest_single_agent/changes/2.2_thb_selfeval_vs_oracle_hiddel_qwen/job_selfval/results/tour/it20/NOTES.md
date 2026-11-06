# In-person check: job_selfval iteration 20 (2026-11-05 ~15:10)

Booted with `scripts/view.py 20` (frontend http://127.0.0.1:60080, backend :60000) and driven through the real UI by
`../common/tour.py ... '/watch/{id}'`. Screens in this directory; `contact_sheet.jpg` tiles them.

Works for a person:
- Landing (poster collage, email + Get Started, Sign In).
- Two-step sign-in (email -> Continue -> password). It works with a freshly registered account. The frozen hidden UI
  walk cannot do this step (see PROGRESS).
- "Who's watching?" -> first profile -> /browse.
- All 7 header links (Home, Shows, Movies, Games, New & Popular, My List, Browse by Languages) render real
  catalog data. Shows/Movies have a Genres dropdown. New & Popular has Top-10 numerals. My List shows an honest empty state.
- Card hover opens a preview card with play / add / rate controls. Clicking a card opens /title/<id>.
- No console errors and no failed API requests during the tour.

Defects seen:
- Title page: the Play button overlaps the "2026 · ..." metadata line and is covered by another layer. A real mouse
  click on it does nothing. The player is reachable only by URL (/watch/<id>).
- A TV title (The Odyssey, id 2) says "No episodes for this title yet". A left column repeats the poster and synopsis.
- Profile tiles are a letter on a gradient, not the provided avatar icons.
- Look vs references: dark theme, red wordmark and nav items match. The hero is full-bleed with plain title text,
  where the reference uses an inset rounded card with a title-logo image. Buttons are square, not pill.
- Player: the clip is served (200, video/mp4), but headless Playwright Chromium has no H.264 decoder (MEDIA_ERR 4).
  Playback is unverified here, not shown to be broken.
