#!/usr/bin/env python3
"""Generate app/database/init/02_seed.sql + app/backend/seed_data.json from the dataset."""
import hashlib, json, os, secrets, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = json.load(open("/workspace/design/dataset/titles.json"))

VIDEOS = sorted(f for f in os.listdir("/workspace/design/assets/video") if f.endswith(".mp4"))

def pbkdf2_hash(password: str, salt_hex: str | None = None) -> str:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"{salt.hex()}${digest.hex()}"

def verify_hash(password: str, stored: str) -> bool:
    salt_hex, hash_hex = stored.split("$", 1)
    return pbkdf2_hash(password, salt_hex) == stored

def esc(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    v = " ".join(str(v).split())          # collapse newlines/extra whitespace
    return "'" + v.replace("'", "''") + "'"

# ---- deterministic per-title attributes -----------------------------------
import random
rng = random.Random(42)

# top10: top 10 series and top 10 movies by rating
series = sorted([t for t in DATA if t["kind"] == "series"], key=lambda t: (-t["rating"], t["name"]))
movies = sorted([t for t in DATA if t["kind"] == "movie"], key=lambda t: (-t["rating"], t["name"]))
top10 = {}
for rank, t in enumerate(series[:10], 1):
    top10[t["id"]] = ("series", rank)
for rank, t in enumerate(movies[:10], 1):
    top10[t["id"]] = ("movie", rank)

# movie durations 95..150 min; series: generated episodes
EP_NAMES = [
    "The Arrival", "Second Chance", "Undercurrent", "The Reckoning", "Half Light",
    "Broken Compass", "The Long Way", "Silent Hours", "Crossing Lines", "The Inheritance",
    "Ashes", "No Man's Land", "The Signal", "Last Exit", "Open Water",
    "The Weight", "Frayed", "North Star", "The Threshold", "Quiet Before",
]
EP_SYNOPSES = [
    "Loose ends from the past refuse to stay buried, forcing an uneasy alliance.",
    "A quiet mistake spirals into a crisis that threatens everything they have built.",
    "New arrivals upend the status quo, and old loyalties are tested to the limit.",
    "A desperate plan hinges on a single act of trust no one is ready to give.",
    "The truth surfaces in pieces, and each one rewrites what came before.",
    "A race against the clock turns an ordinary night into the most dangerous of their lives.",
    "An old enemy returns with a familiar promise and a price that keeps rising.",
    "What starts as a favor turns into an obligation that can't be unwritten.",
]

def _asset(p):
    if not p:
        return None
    return "/assets/" + p.split("/", 1)[1]

def build():
    rows = []
    episodes = []
    epi_id = 0
    for t in DATA:
        tid = t["id"]
        video = f"/assets/video/{VIDEOS[tid % len(VIDEOS)]}"
        backdrop = _asset(t["backdrop"])
        poster = _asset(t["poster"])
        if t["kind"] == "movie":
            duration = int(rng.uniform(95, 150) * 60)
            seasons = 0
        else:
            seasons = 1 + (tid % 3)
            total = 0
            for s in range(1, seasons + 1):
                count = 6 + ((tid + s) % 3)
                for n in range(1, count + 1):
                    epi_id += 1
                    dur = int(rng.uniform(22, 55) * 60)
                    total += dur
                    episodes.append({
                        "id": epi_id, "title_id": tid, "season": s, "number": n,
                        "name": EP_NAMES[(tid + s * 3 + n) % len(EP_NAMES)],
                        "synopsis": EP_SYNOPSES[(tid + s + n) % len(EP_SYNOPSES)],
                        "duration": dur,
                        "thumbnail": backdrop or poster,
                    })
            duration = total
        rows.append({
            "id": tid, "name": t["name"], "kind": t["kind"], "year": str(t.get("year") or ""),
            "genre": t.get("genre"), "maturity_rating": t.get("maturity_rating"),
            "rating": t.get("rating"), "synopsis": t.get("synopsis"),
            "poster": poster,
            "backdrop": backdrop,
            "video_url": video, "duration": duration,
            "top10_rank": top10.get(tid, (None, None))[1],
            "language": t.get("language"),
            "_seasons": seasons,
        })
    return rows, episodes

TITLES, EPISODES = build()

# ---- genres ------------------------------------------------------------------
genre_names = []
for t in TITLES:
    src = json.load(open("/workspace/design/dataset/titles.json"))
    break
by_id = {t["id"]: t for t in DATA}
for t in TITLES:
    for g in (by_id[t["id"]].get("genres") or ([t["genre"]] if t["genre"] else [])):
        if g and g not in genre_names:
            genre_names.append(g)
genre_id = {g: i + 1 for i, g in enumerate(genre_names)}
title_genres = []
for t in TITLES:
    for g in (by_id[t["id"]].get("genres") or ([t["genre"]] if t["genre"] else [])):
        if g in genre_id:
            title_genres.append((t["id"], genre_id[g]))

# ---- demo user / profiles ----------------------------------------------------
DEMO_EMAIL = "demo@netflix.local"
DEMO_PW = "demo1234"
DEMO_HASH = pbkdf2_hash(DEMO_PW)
assert verify_hash(DEMO_PW, DEMO_HASH)
assert not verify_hash("wrong", DEMO_HASH)

PROFILES = [
    {"id": 1, "user_id": 1, "name": "Alex", "avatar": "0", "is_kids": False},
    {"id": 2, "user_id": 1, "name": "Sam", "avatar": "3", "is_kids": False},
    {"id": 3, "user_id": 1, "name": "Kids", "avatar": "5", "is_kids": True},
]
MY_LIST = [(1, 2), (1, 4), (1, 6), (1, 9), (1, 14), (1, 21)]          # profile 1 (Alex)
RATINGS = [(1, 3, 3), (1, 7, 2), (1, 11, 1)]                             # profile 1
CW = [(1, 2, 1543), (1, 7, 891), (1, 15, 2401), (1, 33, 310)]            # profile 1

# ---- emit SQL ------------------------------------------------------------------
lines = []
lines.append("-- Netflix clone — seed (generated from dataset/titles.json)")
lines.append("BEGIN;")
lines.append("DELETE FROM continue_watching; DELETE FROM ratings; DELETE FROM my_list;")
lines.append("DELETE FROM title_genres; DELETE FROM episodes; DELETE FROM titles;")
lines.append("DELETE FROM profiles; DELETE FROM users; DELETE FROM genres;")

for name in genre_names:
    lines.append(f"INSERT INTO genres (id, name) VALUES ({genre_id[name]}, {esc(name)});")
lines.append(f"SELECT setval('genres_id_seq', {max(genre_id.values())});")

lines.append(f"INSERT INTO users (id, email, password_hash, name) VALUES (1, {esc(DEMO_EMAIL)}, {esc(DEMO_HASH)}, 'Demo');")
lines.append("SELECT setval('users_id_seq', 1);")

for p in PROFILES:
    lines.append(f"INSERT INTO profiles (id, user_id, name, avatar, is_kids) VALUES "
                 f"({p['id']}, {p['user_id']}, {esc(p['name'])}, {esc(p['avatar'])}, {'TRUE' if p['is_kids'] else 'FALSE'});")
lines.append("SELECT setval('profiles_id_seq', 3);")

for t in TITLES:
    lines.append("INSERT INTO titles (id, name, kind, year, genre, maturity_rating, rating, synopsis, poster, backdrop, video_url, duration, top10_rank, language) VALUES ("
                 f"{t['id']}, {esc(t['name'])}, {esc(t['kind'])}, {esc(t['year'])}, {esc(t['genre'])}, {esc(t['maturity_rating'])}, "
                 f"{t['rating'] if t['rating'] is not None else 'NULL'}, {esc(t['synopsis'])}, {esc(t['poster'])}, {esc(t['backdrop'])}, "
                 f"{esc(t['video_url'])}, {t['duration']}, {t['top10_rank'] if t['top10_rank'] is not None else 'NULL'}, {esc(t['language'])});")
lines.append(f"SELECT setval('titles_id_seq', {max(t['id'] for t in TITLES)});")

for e in EPISODES:
    lines.append(f"INSERT INTO episodes (id, title_id, season, number, name, synopsis, duration, thumbnail) VALUES "
                 f"({e['id']}, {e['title_id']}, {e['season']}, {e['number']}, {esc(e['name'])}, {esc(e['synopsis'])}, {e['duration']}, {esc(e['thumbnail'])});")
lines.append(f"SELECT setval('episodes_id_seq', {len(EPISODES)});")

for tid, gid in title_genres:
    lines.append(f"INSERT INTO title_genres (title_id, genre_id) VALUES ({tid}, {gid});")

for pid, tid in MY_LIST:
    lines.append(f"INSERT INTO my_list (profile_id, title_id) VALUES ({pid}, {tid});")
lines.append(f"SELECT setval('my_list_id_seq', {len(MY_LIST)});")
for pid, tid, val in RATINGS:
    lines.append(f"INSERT INTO ratings (profile_id, title_id, value) VALUES ({pid}, {tid}, {val});")
lines.append(f"SELECT setval('ratings_id_seq', {len(RATINGS)});")
for pid, tid, prog in CW:
    lines.append(f"INSERT INTO continue_watching (profile_id, title_id, progress_seconds) VALUES ({pid}, {tid}, {prog});")
lines.append(f"SELECT setval('continue_watching_id_seq', {len(CW)});")
lines.append("COMMIT;")

sql_path = os.path.join(ROOT, "app", "database", "init", "02_seed.sql")
with open(sql_path, "w") as f:
    f.write("\n".join(lines) + "\n")

# seed_data.json for the validator's literal-id recovery (app/backend/seed_data.json)
seed = {
    "users": [{"id": 1, "email": DEMO_EMAIL, "name": "Demo"}],
    "profiles": PROFILES,
    "genres": [{"id": gid, "name": n} for n, gid in genre_id.items()],
    "titles": [{k: t[k] for k in ("id", "name", "kind", "year")} for t in TITLES],
    "episodes": EPISODES,
    "my_list": [{"id": i + 1, "profile_id": p, "title_id": t} for i, (p, t) in enumerate(MY_LIST)],
    "ratings": [{"id": i + 1, "profile_id": p, "title_id": t, "value": v} for i, (p, t, v) in enumerate(RATINGS)],
    "continue_watching": [{"id": i + 1, "profile_id": p, "title_id": t, "progress_seconds": g} for i, (p, t, g) in enumerate(CW)],
}
seed_path = os.path.join(ROOT, "app", "backend", "seed_data.json")
with open(seed_path, "w") as f:
    json.dump(seed, f)

print("wrote", sql_path, len(lines), "lines;", len(TITLES), "titles;", len(EPISODES), "episodes;", len(genre_names), "genres")
