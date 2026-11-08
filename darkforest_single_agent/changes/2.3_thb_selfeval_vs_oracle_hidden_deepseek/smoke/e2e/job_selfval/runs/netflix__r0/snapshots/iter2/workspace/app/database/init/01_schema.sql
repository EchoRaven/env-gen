-- Netflix catalog schema
CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  avatar TEXT NOT NULL DEFAULT 'red',
  is_kids BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS titles (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  year INTEGER NOT NULL,
  genre TEXT NOT NULL,
  maturity_rating TEXT NOT NULL,
  rating NUMERIC(3,1) NOT NULL DEFAULT 0,
  synopsis TEXT NOT NULL,
  poster TEXT NOT NULL,
  backdrop TEXT NOT NULL,
  video_url TEXT NOT NULL,
  duration INTEGER NOT NULL,
  top10_rank INTEGER,
  language TEXT NOT NULL DEFAULT 'en'
);
CREATE TABLE IF NOT EXISTS episodes (
  id SERIAL PRIMARY KEY,
  title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
  season INTEGER NOT NULL,
  number INTEGER NOT NULL,
  name TEXT NOT NULL,
  synopsis TEXT NOT NULL,
  duration INTEGER NOT NULL,
  thumbnail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS genres (
  id SERIAL PRIMARY KEY,
  name TEXT UNIQUE NOT NULL
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
  updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
  UNIQUE(profile_id, title_id)
);
CREATE INDEX IF NOT EXISTS idx_titles_kind ON titles(kind);
CREATE INDEX IF NOT EXISTS idx_episodes_title ON episodes(title_id);
CREATE INDEX IF NOT EXISTS idx_title_genres_genre ON title_genres(genre_id);
CREATE INDEX IF NOT EXISTS idx_my_list_profile ON my_list(profile_id);
CREATE INDEX IF NOT EXISTS idx_continue_profile ON continue_watching(profile_id);
