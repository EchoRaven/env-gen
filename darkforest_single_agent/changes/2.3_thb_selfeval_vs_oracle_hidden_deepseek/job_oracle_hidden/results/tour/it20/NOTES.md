# In-person check: job_oracle_hidden iteration 20 (2026-11-08 ~05:55)

Booted with `scripts/stack.py view 20` (frontend http://127.0.0.1:16000, backend :21000; compose project
`thbview23-hidden-r0-it20`, torn down afterwards). `../common/tour.py` (screens `01`-`05`) stopped at the profile step.
For a new account, this app opens an "Add a Profile" dialog instead of listing a profile, and the tour's generic
profile picker clicked a colour swatch. `../scripts/manual_check.py ... --full` then created a profile named "Tour"
and finished the walk (screens `manual/m01`-`m20`). `contact_sheet.jpg` and `manual/contact_sheet.jpg` tile them.

Works for a person:
- Landing: poster collage, headline, email + Get Started, a language selector next to a red Sign In button (as in the
  reference), and the ad-tier banner.
- Two-step sign-in (email -> Continue -> password), as in the reference. It works with a freshly registered account.
  The frozen hidden UI walk cannot do this step.
- A new account has no profile. The app asks for one (name, avatar colour, Kids Profile), then shows "Who's watching?"
  with a letter tile.
- Home: a full-bleed hero (House of the Dragon) with plain title text, rating, maturity badge, and Play / More Info.
  Rails: Trending Now (TOP 10 badges), Continue Watching (empty state), TV Action & Adventure. A Games rail says
  "No games are included in the supplied catalog".
- All 7 header links render: Home, Shows / Movies (Genres menus; "#1 in TV Shows Today"), Games (an honest page: "The
  supplied catalog contains films and series only"), New & Popular (Top-10 numerals), My List (empty state with a
  "Browse the catalog" button), and Browse by Languages.
- Card hover opens a preview card with play / add / rate / expand controls. Clicking a card opens a title view at
  `/title/<id>` as a modal over the browse page, with Play, +, rating, metadata, Episodes, and More Like This.
- Play works from the hero (`/watch/22`) and from the title view (`/watch/48`). The player has a full control bar with
  an Episodes button.
- No console errors and no failed requests.

Defects and caveats:
- Browse by Languages: the three preference selectors are stacked in a panel that overlaps the first row of the grid,
  and the "Original Language" label overprints the "Select Your Preferences" heading. The grid uses large backdrop tiles
  with the title as text, where the reference has a dense poster grid.
- Profile tiles are letters on a colour, not the provided avatar art.
- Static audit (hidden evaluator): `fabricated_field_fallback`, `activeProfile.name || 'None selected'` in
  `Header.jsx`, present from iteration 1. It is cosmetic (a label shown when no profile is active).
- Look vs references: same as job 1. The hero is full-bleed with plain title text, not the reference's inset card
  with a title-logo image.
- Player: same H.264 limitation of headless Chromium as job 1 (MEDIA_ERR 4). Playback is unverified, not shown broken.
