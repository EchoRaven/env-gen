CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  email VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(512) NOT NULL,
  name VARCHAR(255) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS profiles (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name VARCHAR(120) NOT NULL,
  avatar VARCHAR(120) NOT NULL DEFAULT 'red',
  is_kids BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS titles (
  id INTEGER PRIMARY KEY,
  name VARCHAR(300) NOT NULL,
  kind VARCHAR(40) NOT NULL,
  year VARCHAR(12) NOT NULL,
  genre VARCHAR(120) NOT NULL DEFAULT '',
  maturity_rating VARCHAR(20) NOT NULL DEFAULT '',
  rating NUMERIC(3,1) NOT NULL DEFAULT 0,
  synopsis TEXT NOT NULL DEFAULT '',
  poster TEXT NOT NULL DEFAULT '',
  backdrop TEXT NOT NULL DEFAULT '',
  video_url TEXT NOT NULL DEFAULT '',
  duration INTEGER NOT NULL DEFAULT 0,
  top10_rank INTEGER,
  language VARCHAR(10) NOT NULL DEFAULT 'en'
);

CREATE TABLE IF NOT EXISTS episodes (
  id SERIAL PRIMARY KEY,
  title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
  season INTEGER NOT NULL,
  number INTEGER NOT NULL,
  name VARCHAR(250) NOT NULL,
  synopsis TEXT NOT NULL DEFAULT '',
  duration INTEGER NOT NULL DEFAULT 0,
  thumbnail TEXT NOT NULL DEFAULT '',
  UNIQUE(title_id, season, number)
);

CREATE TABLE IF NOT EXISTS genres (
  id SERIAL PRIMARY KEY,
  name VARCHAR(120) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS title_genres (
  id SERIAL PRIMARY KEY,
  title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
  genre_id INTEGER NOT NULL REFERENCES genres(id) ON DELETE CASCADE,
  UNIQUE(title_id, genre_id)
);

CREATE TABLE IF NOT EXISTS my_list (
  id SERIAL PRIMARY KEY,
  profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(profile_id, title_id)
);

CREATE TABLE IF NOT EXISTS ratings (
  id SERIAL PRIMARY KEY,
  profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
  value INTEGER NOT NULL CHECK (value IN (-1, 1, 2)),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(profile_id, title_id)
);

CREATE TABLE IF NOT EXISTS continue_watching (
  id SERIAL PRIMARY KEY,
  profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
  progress_seconds INTEGER NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(profile_id, title_id)
);

CREATE INDEX IF NOT EXISTS idx_profiles_user ON profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_titles_kind ON titles(kind);
CREATE INDEX IF NOT EXISTS idx_episodes_title ON episodes(title_id);
CREATE INDEX IF NOT EXISTS idx_title_genres_title ON title_genres(title_id);
CREATE INDEX IF NOT EXISTS idx_title_genres_genre ON title_genres(genre_id);
CREATE INDEX IF NOT EXISTS idx_my_list_profile ON my_list(profile_id);
CREATE INDEX IF NOT EXISTS idx_ratings_profile ON ratings(profile_id);
CREATE INDEX IF NOT EXISTS idx_continue_profile ON continue_watching(profile_id);
