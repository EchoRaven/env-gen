#!/usr/bin/env python3
"""Smoke test all 17 contract endpoints + auth. Usage: python tools/api_smoke.py [base_url]"""
import json
import sys
import time
import urllib.request
import urllib.error

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010"
FAILS = []
PASSES = []

def req(method, path, token=None, body=None, headers=None, raw=False):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    if headers:
        for k, v in headers.items():
            r.add_header(k, v)
    try:
        with urllib.request.urlopen(r) as resp:
            txt = resp.read().decode()
            return resp.status, (txt if raw else (json.loads(txt) if txt else None))
    except urllib.error.HTTPError as e:
        txt = e.read().decode()
        try:
            return e.code, json.loads(txt)
        except Exception:
            return e.code, txt

def items(d):
    return d["items"] if isinstance(d, dict) and isinstance(d.get("items"), list) else d

def check(name, cond, extra=""):
    if cond:
        PASSES.append(name)
        print(f"  PASS {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL {name} {extra}")

# 1. health
s, d = req("GET", "/health")
check("health 200", s == 200, f"got {s} {d}")

# 2. auth unenforced check: every /api/* must 401 without token
api_paths = ["/api/profiles", "/api/titles", "/api/titles/trending", "/api/titles/top10",
             "/api/genres", "/api/search", "/api/my-list", "/api/continue-watching"]
for p in api_paths:
    s, d = req("GET", p)
    check(f"401 without token {p}", s == 401, f"got {s} {d}")

# 3. register
email = f"smoke{time.time():.0f}@example.com"
s, d = req("POST", "/auth/register", body={"email": email, "password": "password123", "name": "Smoke"})
check("register 200 + token", s in (200, 201) and "access_token" in d, f"got {s} {d}")
token = d.get("access_token") if isinstance(d, dict) else None

# 4. register duplicate
s, d = req("POST", "/auth/register", body={"email": email, "password": "password123"})
check("register duplicate 409", s == 409, f"got {s}")

# 5. login wrong password
s, d = req("POST", "/auth/login", body={"email": email, "password": "wrongpass"})
check("login wrong pw 401", s == 401, f"got {s}")

# 6. login ok
s, d = req("POST", "/auth/login", body={"email": email, "password": "password123"})
check("login 200 + token", s == 200 and "access_token" in d, f"got {s}")
token = d["access_token"]

# 7. demo user login
s, d = req("POST", "/auth/login", body={"email": "demo@netflix.example", "password": "demo1234"})
check("demo login works", s == 200 and "access_token" in d, f"got {s}")
demo_token = d["access_token"] if s == 200 else token

T = {"Authorization": f"Bearer {token}"}

# profiles
s, d = req("GET", "/api/profiles", token)
check("GET profiles list", s == 200 and isinstance(d, dict) and isinstance(d.get("items"), list), f"got {s} {d}")
s, d = req("POST", "/api/profiles", token, body={"name": "Smoke Profile", "avatar": "avatar_3", "is_kids": False})
check("POST profile", s in (200, 201) and d.get("id"), f"got {s} {d}")
profile_id = d.get("id")

# titles
s, d = req("GET", "/api/titles", token)
check("GET titles list 60", s == 200 and isinstance(items(d), list) and len(items(d)) == 60, f"got {s} n={len(items(d)) if isinstance(items(d),list) else d}")
first_id = items(d)[0]["id"] if items(d) else 1
for key in ["id","name","kind","year","genre","maturity_rating","rating","synopsis","poster","backdrop","video_url","duration","top10_rank"]:
    if key not in items(d)[0]:
        check(f"title has field {key}", False)
        break
else:
    check("title fields complete", True)

s, d = req("GET", f"/api/titles/{first_id}", token)
check("GET title by id", s == 200 and d["id"] == first_id, f"got {s}")
s, d = req("GET", "/api/titles/99999", token)
check("GET missing title 404", s == 404, f"got {s}")

# episodes
series_id = next(t["id"] for t in d2) if False else None
s, d = req("GET", "/api/titles", token)
series_id = next(t["id"] for t in items(d) if t["kind"] == "series")
s, d = req("GET", f"/api/titles/{series_id}/episodes", token)
check("GET episodes", s == 200 and isinstance(items(d), list) and len(items(d)) > 0 and "name" in items(d)[0] and "season" in items(d)[0], f"got {s} {str(d)[:120]}")

# trending / top10
s, d = req("GET", "/api/titles/trending", token)
check("GET trending", s == 200 and isinstance(items(d), list) and 0 < len(items(d)) <= 20, f"got {s} n={len(items(d)) if isinstance(items(d),list) else '?'}")
s, d = req("GET", "/api/titles/top10", token)
check("GET top10", s == 200 and isinstance(items(d), list) and all(t.get("top10_rank") for t in items(d)), f"got {s}")
s, d = req("GET", "/api/titles/top10?kind=movie", token)
check("GET top10 movie filter", s == 200 and all(t["kind"] == "movie" for t in items(d)), f"got {s}")

# genres
s, d = req("GET", "/api/genres", token)
check("GET genres", s == 200 and isinstance(items(d), list) and len(items(d)) >= 10, f"got {s} n={len(items(d)) if isinstance(items(d),list) else '?'}")
gid = items(d)[0]["id"]
s, d = req("GET", f"/api/genres/{gid}/titles", token)
check("GET genre titles", s == 200 and isinstance(items(d), list) and len(items(d)) > 0, f"got {s}")

# search
s, d = req("GET", "/api/search?q=the", token)
check("GET search results", s == 200 and isinstance(items(d), list) and len(items(d)) > 0, f"got {s}")
s, d = req("GET", "/api/search?q=zzzznotfoundzzz", token)
check("search empty honest", s == 200 and items(d) == [], f"got {s} {d}")

# my list business chain
s, d = req("POST", "/api/my-list", token, body={"title_id": first_id})
check("POST my-list", s in (200, 201) and d.get("title_id") == first_id, f"got {s} {d}")
s, d = req("GET", "/api/my-list", token)
check("GET my-list contains", s == 200 and any(t["id"] == first_id for t in items(d)), f"got {s}")
s, d = req("DELETE", f"/api/my-list/{first_id}", token)
check("DELETE my-list by title id", s in (200, 204), f"got {s} {d}")
s, d = req("GET", "/api/my-list", token)
check("GET my-list removed", s == 200 and all(t["id"] != first_id for t in items(d)), f"got {s}")

# PUT my-list (framework default-crud probe): missing id -> 404, valid token
s, d = req("PUT", "/api/my-list/999999", token, body={})
check("PUT my-list missing 404", s == 404, f"got {s} {d}")
s, d = req("PUT", "/api/my-list/999999", None, body={})
check("PUT my-list 401 without token", s == 401, f"got {s}")

# PUT profiles update alias
s, d = req("PUT", f"/api/profiles/{profile_id}", token, body={"name": "Smoke Profile Renamed"})
check("PUT profile update", s == 200 and d.get("name") == "Smoke Profile Renamed", f"got {s} {d}")

# rating
s, d = req("POST", f"/api/titles/{first_id}/rating", token, body={"value": 2})
check("POST rating", s in (200, 201) and d.get("value") == 2, f"got {s} {d}")
s, d = req("POST", f"/api/titles/{first_id}/rating", token, body={"value": 3})
check("POST rating update", s in (200, 201) and d.get("value") == 3, f"got {s} {d}")

# continue watching
s, d = req("GET", "/api/continue-watching", token)
check("GET continue-watching list", s == 200 and isinstance(items(d), list), f"got {s}")
s, d = req("POST", "/api/continue-watching", token, body={"title_id": first_id, "progress_seconds": 123})
check("POST continue-watching", s in (200, 201), f"got {s} {d}")
s, d = req("GET", "/api/continue-watching", token)
check("continue-watching persisted", s == 200 and any(t["id"] == first_id and t["progress_seconds"] == 123 for t in items(d)), f"got {s}")

# demo user has seeded continue watching + my list
s, d = req("GET", "/api/continue-watching", demo_token)
check("demo continue-watching seeded", s == 200 and len(items(d)) >= 3, f"got {s} n={len(items(d)) if isinstance(items(d),list) else '?'}")
s, d = req("GET", "/api/my-list", demo_token)
check("demo my-list seeded", s == 200 and len(items(d)) >= 4, f"got {s} n={len(items(d)) if isinstance(items(d),list) else '?'}")
s, d = req("GET", "/api/profiles", demo_token)
check("demo profiles 3", s == 200 and len(items(d)) == 3, f"got {s}")

# per-profile isolation: profile 2 sees own my list (2 seeded)
hdr = {"X-Profile-Id": str(demo_token and None) if False else None}
s, d = req("POST", "/auth/login", body={"email": "demo@netflix.example", "password": "demo1234"})
dt = d["access_token"]
s, d = req("GET", "/api/my-list", dt, headers={"X-Profile-Id": "2"})
check("profile 2 my-list isolated", s == 200 and all(t["id"] in (2, 9) for t in items(d)) and len(items(d)) == 2, f"got {s} {d}")

# media
s, d = req("GET", "/media/brand/netflix_wordmark.svg", raw=True)
check("media svg served", s == 200 and "<svg" in d, f"got {s}")

print()
print(f"PASSED: {len(PASSES)}  FAILED: {len(FAILS)}")
if FAILS:
    print("Failures:", FAILS)
    sys.exit(1)
