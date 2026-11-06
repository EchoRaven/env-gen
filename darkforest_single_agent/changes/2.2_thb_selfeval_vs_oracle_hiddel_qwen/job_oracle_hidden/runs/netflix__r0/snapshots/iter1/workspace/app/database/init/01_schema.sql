-- Netflix clone schema (Postgres 16)
CREATE TABLE IF NOT EXISTS users (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    avatar TEXT NOT NULL DEFAULT 'avatar_0',
    is_kids BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS genres (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS titles (
    id BIGINT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    year TEXT NOT NULL,
    genre TEXT,
    maturity_rating TEXT,
    rating DOUBLE PRECISION,
    synopsis TEXT,
    language TEXT,
    poster TEXT,
    backdrop TEXT,
    video_url TEXT,
    duration INTEGER,
    top10_rank INTEGER
);

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
    season INTEGER NOT NULL,
    number INTEGER NOT NULL,
    name TEXT NOT NULL,
    synopsis TEXT,
    duration INTEGER,
    thumbnail TEXT
);

CREATE TABLE IF NOT EXISTS title_genres (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
    genre_id INTEGER NOT NULL REFERENCES genres(id) ON DELETE CASCADE,
    UNIQUE (title_id, genre_id)
);

CREATE TABLE IF NOT EXISTS my_list (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
    UNIQUE (profile_id, title_id)
);

CREATE TABLE IF NOT EXISTS ratings (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
    value INTEGER NOT NULL CHECK (value IN (1, 2, 3)),
    UNIQUE (profile_id, title_id)
);

CREATE TABLE IF NOT EXISTS continue_watching (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
    progress_seconds INTEGER NOT NULL DEFAULT 0,
    UNIQUE (profile_id, title_id)
);

CREATE INDEX IF NOT EXISTS ix_titles_kind ON titles (kind);
CREATE INDEX IF NOT EXISTS ix_titles_rating ON titles (rating);
CREATE INDEX IF NOT EXISTS ix_titles_year ON titles (year);
CREATE INDEX IF NOT EXISTS ix_episodes_title ON episodes (title_id);
CREATE INDEX IF NOT EXISTS ix_profiles_user ON profiles (user_id);
