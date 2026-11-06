# In-person check: job_oracle_hidden iteration 20 (2026-11-05 ~22:40)

Booted with `scripts/stack.py view 20` (frontend http://127.0.0.1:31080, backend :31000) and driven through the real
UI by `../../../common/tour.py ... '/watch/{id}'`. Screens in this directory; `contact_sheet.jpg` tiles them.

Works for a person:
- Landing (poster collage, big wordmark, email + Get Started). One-step sign-in form (email + password) with a
  freshly registered account. "Who's watching?" -> the account's profile -> /browse.
- All 7 header links render: Home, Shows, Movies, Games, New & Popular (Top-10 numerals, Coming This Week), My List
  (honest empty state with "Browse titles"), and Browse by Languages (Original language / Dubbing / Subtitles filters,
  like the reference).
- Card hover opens a preview card with play / add / rate / more controls. Its Play button opens /watch/<id>, a player
  page with the backdrop as poster and a full control bar (play, ±10s, volume, subtitles, speed, fullscreen).
- Home has a Continue Watching rail with an honest empty state, and a search page exists.
- No console errors. The only failed request is the H.264 clip in headless Chromium (no decoder), so playback is
  unverified, not broken.

Defects seen:
- At least one title's poster renders as a broken white tile in the rails (Trending Now and others).
- Games: every rail says no games are available. This is honest, because the dataset has 32 series, 28 movies, and no
  games. Job 1 instead fills Games with movies labelled "Play Game".
- Sign-in is one step (email + password), where the reference has two steps. Profile tiles are plain coloured squares.
- Clicking a poster opens the hover preview rather than a separate title-detail view (there is no /title route).
- Look vs references: dark theme, wordmark, nav, hero with title text, square buttons. Similar fidelity to job 1.
