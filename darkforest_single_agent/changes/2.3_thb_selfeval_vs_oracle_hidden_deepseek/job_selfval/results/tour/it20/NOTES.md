# In-person check: job_selfval iteration 20 (2026-11-08 ~05:50)

Booted with `scripts/view.py 20` (frontend http://localhost:15000, backend :20000; compose project
`thbview23-r0-it20`, torn down afterwards). It was driven through the real UI by `../common/tour.py ... '/watch/{id}'`
(screens `01`-`14`), then by `../scripts/manual_check.py` (screens `manual/m01`-`m07`). `contact_sheet.jpg` and
`manual/contact_sheet.jpg` tile them.

Works for a person:
- Landing: poster collage, "Unlimited movies, TV shows, and more", email + Get Started, and the ad-tier banner.
- Two-step sign-in (email -> Continue -> password), as in the reference `login.jpg`. It works with a freshly registered
  account. The frozen hidden UI walk cannot do this step (it waits for a password field on the first screen).
- "Who's watching?" shows the provided avatar art (`avatars/avatar_1.svg`) plus Add Profile -> /browse.
- Home: a full-bleed hero (Spooky in Love) with a condensed title treatment, Play / More Info, and a maturity badge.
  Rails: Trending Now with TOP 10 badges, TV Action & Adventure, Only on Netflix, and Top Searches.
- Every header link renders real catalog data: Home, Shows, Movies (each with a Genres menu), Games, New & Popular
  (Top-10 numerals), and My List (honest empty state). Browse by Languages is a dropdown (Original Language, English,
  Japanese, ...). Its page has the reference's three preference selectors (Original Language / Dubbing / Subtitles)
  above a poster grid.
- Card hover opens a preview card with play / add / thumbs / expand controls. Clicking a card opens a title modal
  (`/browse?title=<id>`; `/title/<id>` redirects to it) with Play, +, thumbs, "Rate this title", and a metadata column.
- Play works from the hero (series -> `/watch/29?ep=49`) and from the title modal (`/watch/48`). The player has a
  full control bar.
- No console errors and no failed requests during either script.

Defects and caveats:
- tour.py logged `play_button_covered`. That is an artifact of the tour, not of the app: with the modal open, the
  first "Play" in the DOM is the hero's button behind the modal, and the click closed the modal. The modal's own Play
  button works (manual m02 -> m03).
- Games: the hero is a TV quiz show (Jeopardy!, "2 Seasons") with a Play button. The game rails ("Party Games") are
  honest empty states ("No titles are available in this category yet"). The dataset has no games.
- The landing headline's line break overlaps a collage poster's caption (cosmetic).
- Look vs references: dark theme, red wordmark, and nav items match. The hero is full-bleed, where the reference uses an
  inset rounded card with a title-logo image.
- Player: the clip is served (200, video/mp4), but headless Playwright Chromium has no H.264 decoder (MEDIA_ERR 4; the app
  shows "The trailer clip could not be loaded"). Playback is unverified here, not shown to be broken. 2.2 had the same
  limitation.
