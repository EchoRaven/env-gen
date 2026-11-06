# Netflix — full-stack streaming catalog clone (spec)

Build a **pixel-faithful, fully-functional Netflix web clone**: a multi-profile video
streaming catalog. Every screen must match its reference screenshot in `references/`, every
interactive control must be wired to a real backend action (no dead buttons, no placeholder
stubs), and all content must use the **real provided assets** (posters/backdrops/trailers in
`assets/`, the catalog rows in `dataset/titles.json`, the logo/icons/fonts in `assets/`).

## Look & feel (match the references exactly)
- Dark theme: near-black background (#141414), white text, Netflix red accent **#e50914**.
- Header: the NETFLIX wordmark (`assets/brand/netflix_wordmark.svg`) top-left; primary nav
  **Home · Shows · Movies · Games · New & Popular · My List · Browse by Languages**; right side
  search icon, notifications bell, and the profile avatar with a dropdown caret. Use the SVGs in
  `assets/icons/netflix/` (play, plus, search, bell, volume, subtitles, thumbs, close, …).
- Browse pages: a large **hero/billboard** (backdrop image, title logo, short synopsis,
  **Play** + **More Info** buttons, maturity badge) над **horizontally-scrolling poster rails**;
  each rail has a section title and poster cards; hovering a card shows a **mini-preview** with
  Play / + (add to list) / thumbs-up / expand and quick tags.
- Typography: use the provided web fonts in `assets/fonts/` (Anton-like display for big titles,
  Inter for UI).

## Screens (each maps to a file in references/)
- `landing` (`/`, logged-out): full-bleed poster collage, wordmark, **Sign In**, email field +
  **Get Started**.
- `login` (`/login`): email + password sign-in; link to sign up.
- `profiles` (`/profiles`, "Who's watching?"): grid of profile avatars + **Manage Profiles**;
  selecting a profile enters the app. (Include even though no screenshot is provided.)
- `browse_home` / `browse_home_rows` (`/browse`): hero billboard + rails — Trending Now,
  Continue Watching, TV Action & Adventure, Games, Only on Netflix, Top Searches, New on Netflix.
- `shows` (`/shows`): TV-Shows landing with a **Genres** dropdown + hero + "Today's Top Picks" rails.
- `movies` (`/movies`): Movies landing with **Genres** dropdown + hero + "Gems for You" rails.
- `games` (`/games`): Games landing, hero + "Party Games" rails.
- `new_and_popular` (`/new`): "New on Netflix", **Top 10 TV Shows** and **Top 10 Movies** (large
  ranked numerals), "Coming This Week".
- `genre_category` (`/browse/genre/:genreId`): a single-genre category page (e.g. "Sports TV
  Shows") with rails filtered to that genre.
- `title_detail` (modal over any browse page): backdrop, title, metadata (year · seasons/HD ·
  maturity rating), synopsis, cast, genres, **Play** / **+ (My List)** / **thumbs**, and an
  **Episodes** list (thumbnail, title, runtime, synopsis) with a season selector for series.
- `player` (`/watch/:titleId`): full-screen video playback of the title's real trailer clip
  (`assets/video/`), with **play/pause, seek bar, −10s/+10s, volume/mute, next-episode,
  episodes, subtitles/audio, fullscreen, back**, and a title overlay.
- `card_hover_preview`: the rail hover mini-card (Play / + / thumbs / expand + tags).
- `rate_dialog`: "Rate for better recommendations" — thumbs-down / thumbs-up / two-thumbs (love).
- `browse_by_languages` (`/browse/languages`): "Original Language / Dubbing / Subtitles" +
  language dropdowns над a full poster grid.
- `account_menu`: the header profile dropdown — **Manage Profiles · Account · Sign out**.

## Functional requirements (every control must work)
- **Auth**: register + login (JWT bearer); logout from the profile menu.
- **Profiles**: list / create / select; My List, ratings and Continue Watching are **per-profile**
  and private to that profile.
- **Browse rails**: the home/section pages compose several rails, each backed by its own list
  endpoint (trending, top-10, by-genre, continue-watching, new). Clicking a poster opens the
  title-detail modal; **Play** opens the player.
- **Title detail**: loads the title + its episodes; **+** toggles My List; thumbs set the rating.
- **Player**: plays the real clip; all controls functional; **back** returns to the previous page.
- **My List**: add / remove / list; the **+** button toggles membership and reflects state (✓).
- **Ratings**: thumbs down / up / love persist per profile and drive the rate dialog.
- **Search**: query titles by name/genre → results grid.
- **Wiring rule**: EVERY nav link, button, icon and card must call a real endpoint or route —
  no dead links, no inert placeholders, no fabricated data. Empty states are honest ("—").

## Data model (tables)
- `users`(id, email, password_hash, name)
- `profiles`(id, user_id, name, avatar, is_kids)
- `titles`(id, name, kind, year, genre, maturity_rating, rating, synopsis, poster, backdrop, video_url, duration, top10_rank)
- `episodes`(id, title_id, season, number, name, synopsis, duration, thumbnail)
- `genres`(id, name)
- `title_genres`(id, title_id, genre_id)
- `my_list`(id, profile_id, title_id)
- `ratings`(id, profile_id, title_id, value)
- `continue_watching`(id, profile_id, title_id, progress_seconds)

## Seed data
Seed `titles` from `dataset/titles.json` (real names, years, genres, ratings, synopses, and the
downloaded `poster`/`backdrop` files). Attach a real trailer clip from `assets/video/` as each
title's `video_url` (reuse across titles as needed). Generate genres from the titles, a few
episodes per series, and 2–3 demo profiles for the seeded demo user. The demo user must see a
populated catalog immediately (posters, rails, a playable title).
