-- Netflix clone — schema (runs on empty postgres volume)
CREATE TABLE users (
    id            SERIAL PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT        NOT NULL,
    name          TEXT        NOT NULL DEFAULT ''
);

CREATE TABLE profiles (
    id      SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name    TEXT    NOT NULL,
    avatar  TEXT    NOT NULL DEFAULT '0',
    is_kids BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE genres (
    id   SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE titles (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL,               -- 'series' | 'movie'
    year            TEXT,
    genre           TEXT,                        -- primary genre
    maturity_rating TEXT,
    rating          DOUBLE PRECISION,
    synopsis        TEXT,
    poster          TEXT,
    backdrop        TEXT,
    video_url       TEXT,
    duration        INTEGER NOT NULL DEFAULT 0,  -- total content, seconds
    top10_rank      INTEGER,
    language        TEXT                          -- original language (iso)
);

CREATE TABLE episodes (
    id         SERIAL PRIMARY KEY,
    title_id   INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
    season     INTEGER NOT NULL,
    number     INTEGER NOT NULL,
    name       TEXT,
    synopsis   TEXT,
    duration   INTEGER NOT NULL DEFAULT 0,       -- seconds
    thumbnail  TEXT
);

CREATE TABLE title_genres (
    id        SERIAL PRIMARY KEY,
    title_id  INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
    genre_id  INTEGER NOT NULL REFERENCES genres(id) ON DELETE CASCADE,
    UNIQUE (title_id, genre_id)
);

CREATE TABLE my_list (
    id         SERIAL PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    title_id   INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
    UNIQUE (profile_id, title_id)
);

CREATE TABLE ratings (
    id         SERIAL PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    title_id   INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
    value      INTEGER NOT NULL,                 -- 1 = down, 2 = up, 3 = love
    UNIQUE (profile_id, title_id)
);

CREATE TABLE continue_watching (
    id               SERIAL PRIMARY KEY,
    profile_id       INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    title_id         INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
    progress_seconds INTEGER NOT NULL DEFAULT 0,
    UNIQUE (profile_id, title_id)
);

CREATE INDEX idx_titles_kind ON titles (kind);
CREATE INDEX idx_titles_top10 ON titles (top10_rank);
CREATE INDEX idx_episodes_title ON episodes (title_id);
CREATE INDEX idx_my_list_profile ON my_list (profile_id);
CREATE INDEX idx_ratings_profile ON ratings (profile_id);
CREATE INDEX idx_cw_profile ON continue_watching (profile_id);
