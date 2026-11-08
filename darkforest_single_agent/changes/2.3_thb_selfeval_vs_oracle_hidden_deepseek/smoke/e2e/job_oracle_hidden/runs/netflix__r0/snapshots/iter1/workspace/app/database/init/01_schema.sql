-- Netflix clone schema and seed data
CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  avatar TEXT NOT NULL DEFAULT 'red',
  is_kids BOOLEAN NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS titles (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  year INTEGER,
  genre TEXT,
  maturity_rating TEXT,
  rating NUMERIC(3,1) DEFAULT 0,
  synopsis TEXT DEFAULT '',
  poster TEXT NOT NULL,
  backdrop TEXT,
  video_url TEXT NOT NULL,
  duration INTEGER NOT NULL DEFAULT 0,
  top10_rank INTEGER,
  language TEXT DEFAULT 'en'
);
CREATE TABLE IF NOT EXISTS episodes (
  id SERIAL PRIMARY KEY,
  title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
  season INTEGER NOT NULL,
  number INTEGER NOT NULL,
  name TEXT NOT NULL,
  synopsis TEXT,
  duration INTEGER NOT NULL,
  thumbnail TEXT,
  UNIQUE(title_id, season, number)
);
CREATE TABLE IF NOT EXISTS genres (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE
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
  UNIQUE(profile_id, title_id)
);
CREATE TABLE IF NOT EXISTS ratings (
  id SERIAL PRIMARY KEY,
  profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
  value INTEGER NOT NULL,
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
CREATE INDEX IF NOT EXISTS idx_title_genres_genre ON title_genres(genre_id);
CREATE INDEX IF NOT EXISTS idx_my_list_profile ON my_list(profile_id);
CREATE INDEX IF NOT EXISTS idx_ratings_profile ON ratings(profile_id);
CREATE INDEX IF NOT EXISTS idx_continue_profile ON continue_watching(profile_id);
