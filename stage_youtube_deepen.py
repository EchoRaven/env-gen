#!/usr/bin/env python3
"""Comprehensive, internally-consistent hub dataset for the YouTube demo — the
single source of truth for RegistryHub (endpoints/tables/ui_pages/ui_components/
chains/contract_tests), WorkHub (tasks/decisions), CodeHub (commits/PRs/releases),
EventHub (activity feed) and RunHub (validation runs), plus token-cost metrics.
A full 5-milestone roadmap: M1/M2 released, M3 in-progress, M4/M5 planned.
Demo-only. Run order: this → stage_youtube_panels.py (chat/approvals/knowledge/refs).
Supersedes stage_youtube_demo.py + stage_youtube_enrich.py.
"""
import json, time, os
from pathlib import Path

ROOT = Path("/data/common/haibotong/forgingground-gen/generated/youtube")
HUBS = ROOT / "shared" / "hubs"; HUBS.mkdir(parents=True, exist_ok=True)
now = time.time()
def meta(by, v=1): return {"version": v, "last_modified_by": by, "last_modified_at": now}
def dump(name, obj): (HUBS / name).write_text(json.dumps(obj, indent=2), encoding="utf-8")

# ── project + checkpoint (in-generation, on M3) ──────────────────────────────
(ROOT / "project.json").write_text(json.dumps({
    "agents_used": ["orchestrator", "backend", "frontend", "verifier", "debugger", "knowledge"],
    "created_at": now - 5400, "last_active_at": now - 15,
    "description": "A YouTube-style video platform: channels, video upload & playback, "
                   "comments, likes, subscriptions, a personalized home feed, search, and a Creator Studio.",
    "id": "proj_youtube_demo", "name": "youtube", "schema_version": 1, "status": "active",
}, indent=2), encoding="utf-8")
(ROOT / ".checkpoint").write_text(json.dumps({
    "version": "1.0", "name": "youtube", "domain_type": "web_app", "status": "in_progress",
    "current_phase": "agent_workflow", "milestone_index": 3, "total_milestones": 5,
    "started_at": now - 5400, "last_updated": now - 15,
}, indent=2), encoding="utf-8")
(ROOT / "config.yaml").write_text(
    "preview_url: https://youtube-preview.ngrok.app/index.html\n"
    "frontend:\n  preview_url: https://youtube-preview.ngrok.app/index.html\n  host_port: 8092\n",
    encoding="utf-8")

# ── ENDPOINTS (28, across 5 milestones) ──────────────────────────────────────
IMPL, DEF, PLAN = "implemented", "defined", "planned"
def ep(method, path, status, m, resp_key="item", req=None, resp=None, auth=True):
    return {"id": f"{method} {path}", "method": method, "path": path, "status": status,
            "provider": "backend",
            "schema": {"request": req or {}, "response": resp or ({"item": {}} if resp_key == "item" else {"items": []}),
                       "response_key": resp_key},
            "metadata": {"auth_required": auth, "milestone": m}}
EPS = [
    # M1 — auth, channels, profiles
    ep("POST", "/auth/register", IMPL, 1, "item", {"email": "str", "password": "str", "name": "str"}, auth=False),
    ep("POST", "/auth/login", IMPL, 1, "item", {"email": "str", "password": "str"}, auth=False),
    ep("GET", "/auth/me", IMPL, 1, "item"),
    ep("GET", "/api/channels/{id}", IMPL, 1, "item"),
    ep("POST", "/api/channels", IMPL, 1, "item", {"name": "str", "handle": "str", "description": "str"}),
    ep("PUT", "/api/channels/{id}", IMPL, 1, "item"),
    ep("GET", "/api/channels/{id}/videos", IMPL, 1, "items"),
    # M2 — videos & upload
    ep("GET", "/api/videos", IMPL, 2, "items"),
    ep("GET", "/api/videos/{id}", IMPL, 2, "item"),
    ep("POST", "/api/videos", IMPL, 2, "item", {"title": "str", "description": "str", "visibility": "str", "video_url": "str"}),
    ep("PUT", "/api/videos/{id}", IMPL, 2, "item"),
    ep("DELETE", "/api/videos/{id}", IMPL, 2, "item"),
    ep("GET", "/api/videos/search", IMPL, 2, "items", {"q": "str"}),
    # M3 — watch, comments, likes (IN PROGRESS)
    ep("GET", "/api/videos/{id}/comments", IMPL, 3, "items"),
    ep("POST", "/api/videos/{id}/comments", IMPL, 3, "item", {"text": "str"}),
    ep("DELETE", "/api/comments/{id}", DEF, 3, "item"),
    ep("POST", "/api/videos/{id}/like", DEF, 3, "item"),
    ep("DELETE", "/api/videos/{id}/like", DEF, 3, "item"),
    ep("GET", "/api/videos/{id}/related", DEF, 3, "items"),
    # M4 — subscriptions & home feed
    ep("POST", "/api/channels/{id}/subscribe", DEF, 4, "item"),
    ep("DELETE", "/api/channels/{id}/subscribe", DEF, 4, "item"),
    ep("GET", "/api/feed/subscriptions", DEF, 4, "items"),
    ep("GET", "/api/feed/home", DEF, 4, "items"),
    # M5 — creator studio, analytics, playlists, history
    ep("GET", "/api/studio/videos", PLAN, 5, "items"),
    ep("GET", "/api/studio/analytics", PLAN, 5, "item"),
    ep("GET", "/api/playlists", PLAN, 5, "items"),
    ep("POST", "/api/playlists", PLAN, 5, "item", {"title": "str", "visibility": "str"}),
    ep("GET", "/api/history", PLAN, 5, "items"),
]
dump("registryhub_endpoints.json", {"_meta": meta("backend", 58), **{e["id"]: e for e in EPS}})

# ── TABLES (10; columns under schema.columns) ────────────────────────────────
def tbl(name, cols, status):
    columns = [{"name": n, "type": t, "primary_key": pk} for (n, t, pk) in cols]
    return {"id": name, "name": name, "status": status, "provider": "backend",
            "schema": {"columns": columns}}
def C(n, t, pk=False): return (n, t, pk)
TBLS = [
    tbl("users", [C("id", "uuid", True), C("email", "varchar", False), C("password_hash", "varchar"), C("name", "varchar"), C("created_at", "timestamp")], IMPL),
    tbl("channels", [C("id", "uuid", True), C("owner_id", "uuid"), C("name", "varchar"), C("handle", "varchar"), C("description", "text"), C("avatar_url", "varchar"), C("banner_url", "varchar"), C("subscriber_count", "int")], IMPL),
    tbl("videos", [C("id", "uuid", True), C("channel_id", "uuid"), C("title", "varchar"), C("description", "text"), C("thumbnail_url", "varchar"), C("video_url", "varchar"), C("duration", "int"), C("views", "int"), C("like_count", "int"), C("visibility", "varchar"), C("created_at", "timestamp")], IMPL),
    tbl("comments", [C("id", "uuid", True), C("video_id", "uuid"), C("author_id", "uuid"), C("text", "text"), C("likes", "int"), C("created_at", "timestamp")], IMPL),
    tbl("video_likes", [C("id", "uuid", True), C("video_id", "uuid"), C("user_id", "uuid"), C("created_at", "timestamp")], DEF),
    tbl("subscriptions", [C("id", "uuid", True), C("subscriber_id", "uuid"), C("channel_id", "uuid"), C("created_at", "timestamp")], DEF),
    tbl("playlists", [C("id", "uuid", True), C("owner_id", "uuid"), C("title", "varchar"), C("visibility", "varchar"), C("created_at", "timestamp")], PLAN),
    tbl("playlist_items", [C("id", "uuid", True), C("playlist_id", "uuid"), C("video_id", "uuid"), C("position", "int")], PLAN),
    tbl("watch_history", [C("id", "uuid", True), C("user_id", "uuid"), C("video_id", "uuid"), C("watched_at", "timestamp")], PLAN),
    tbl("notifications", [C("id", "uuid", True), C("user_id", "uuid"), C("type", "varchar"), C("payload", "jsonb"), C("read", "bool"), C("created_at", "timestamp")], PLAN),
]
dump("registryhub_tables.json", {"_meta": meta("backend", 18), **{t["name"]: t for t in TBLS}})

# ── UI PAGES (11) + UI COMPONENTS (12) ───────────────────────────────────────
def page(name, route, comp, status, apis, m, components):
    return {"id": f"page:ui:{name}", "name": name, "kind": "ui_page", "route": route,
            "component": comp, "status": status, "apis_used": apis,
            "components": components, "metadata": {"milestone": m}}
PAGES = [
    page("login", "/login", "LoginPage", IMPL, ["POST /auth/login"], 1, ["NavBar"]),
    page("register", "/register", "RegisterPage", IMPL, ["POST /auth/register"], 1, ["NavBar"]),
    page("home", "/", "HomePage", IMPL, ["GET /api/videos"], 2, ["NavBar", "Sidebar", "VideoGrid", "VideoCard"]),
    page("channel", "/channel/{handle}", "ChannelPage", IMPL, ["GET /api/channels/{id}", "GET /api/channels/{id}/videos"], 1, ["NavBar", "ChannelHeader", "SubscribeButton", "VideoGrid"]),
    page("upload", "/upload", "UploadPage", IMPL, ["POST /api/videos"], 2, ["NavBar", "UploadForm"]),
    page("search", "/search", "SearchPage", IMPL, ["GET /api/videos/search"], 2, ["NavBar", "SearchBar", "VideoCard"]),
    page("watch", "/watch/{id}", "WatchPage", DEF, ["GET /api/videos/{id}", "GET /api/videos/{id}/comments", "POST /api/videos/{id}/comments", "POST /api/videos/{id}/like", "GET /api/videos/{id}/related"], 3, ["NavBar", "VideoPlayer", "LikeButton", "CommentList", "CommentForm", "SubscribeButton", "VideoCard"]),
    page("subscriptions", "/subscriptions", "SubscriptionsPage", DEF, ["GET /api/feed/subscriptions"], 4, ["NavBar", "Sidebar", "VideoGrid"]),
    page("studio", "/studio", "StudioPage", PLAN, ["GET /api/studio/videos", "GET /api/studio/analytics"], 5, ["Sidebar", "VideoGrid"]),
    page("history", "/history", "HistoryPage", PLAN, ["GET /api/history"], 5, ["NavBar", "VideoCard"]),
    page("playlist", "/playlist/{id}", "PlaylistPage", PLAN, ["GET /api/playlists"], 5, ["NavBar", "VideoGrid"]),
]
dump("registryhub_ui_pages.json", {"_meta": meta("frontend", 31), **{p["name"]: p for p in PAGES}})

def comp(name, status):
    return {"id": name, "component": name, "name": name, "status": status, "used_by": []}
COMPS = [
    ("NavBar", IMPL), ("Sidebar", IMPL), ("VideoCard", IMPL), ("VideoGrid", IMPL),
    ("ChannelHeader", IMPL), ("SubscribeButton", IMPL), ("SearchBar", IMPL), ("UploadForm", IMPL),
    ("VideoPlayer", DEF), ("LikeButton", DEF), ("CommentList", DEF), ("CommentForm", DEF),
]
dump("registryhub_ui_components.json", {"_meta": meta("frontend", 22), **{n: comp(n, s) for n, s in COMPS}})

# ── App.jsx wiring (implemented+defined pages → not unwired) ──────────────────
appsrc = ROOT / "app" / "frontend" / "src"; appsrc.mkdir(parents=True, exist_ok=True)
routes = "\n".join(f'        <Route path="{p["route"]}" element={{<{p["component"]}/>}} />'
                   for p in PAGES if p["status"] in (IMPL, DEF))
(appsrc / "App.jsx").write_text(
    "import { Routes, Route } from 'react-router-dom';\n"
    + "".join(f"import {p['component']} from './pages/{p['component']}';\n" for p in PAGES if p["status"] in (IMPL, DEF))
    + "export default function App(){\n  return (\n    <Routes>\n" + routes + "\n    </Routes>\n  );\n}\n",
    encoding="utf-8")

# ── WORKHUB tasks (20) + decisions (8) ───────────────────────────────────────
def task(tid, title, who, status, desc, result=""):
    return {"id": tid, "title": title, "assignee": who, "status": status, "description": desc,
            "claimed_by": who if status != "pending" else "", "result": result}
TASKS = [
    task("t01", "Auth: register/login + JWT (RS256)", "backend", "completed", "M1", "api_smoke green"),
    task("t02", "Channels & profiles CRUD", "backend", "completed", "M1", "validated"),
    task("t03", "Channel's-videos endpoint", "backend", "completed", "M1", "validated"),
    task("t04", "Login / Register / Channel pages", "frontend", "completed", "M1", "wired + ui_smoke green"),
    task("t05", "Video model + columns + migration", "backend", "completed", "M2", "validated"),
    task("t06", "Upload + list + detail + delete endpoints", "backend", "completed", "M2", "validated"),
    task("t07", "Video search endpoint", "backend", "completed", "M2", "validated"),
    task("t08", "Home feed + Upload + Search pages", "frontend", "completed", "M2", "wired"),
    task("t09", "Comments table + endpoints", "backend", "completed", "M3", "implemented"),
    task("t10", "Watch page: player + comments", "frontend", "in_progress", "M3", ""),
    task("t11", "Video like/unlike endpoints", "backend", "in_progress", "M3", ""),
    task("t12", "Related-videos endpoint", "backend", "pending", "M3", ""),
    task("t13", "Comment delete endpoint", "backend", "pending", "M3", ""),
    task("t14", "LikeButton + CommentForm components", "frontend", "in_progress", "M3", ""),
    task("t15", "Subscriptions model + subscribe/unsubscribe", "backend", "pending", "M4", ""),
    task("t16", "Subscription + home feed ranking", "backend", "pending", "M4", ""),
    task("t17", "Subscriptions page", "frontend", "pending", "M4", ""),
    task("t18", "Creator Studio + analytics endpoints", "backend", "pending", "M5", ""),
    task("t19", "Studio dashboard + analytics charts", "frontend", "pending", "M5", ""),
    task("t20", "Playlists + watch history", "backend", "pending", "M5", ""),
]
dump("workhub_tasks.json", {"_meta": meta("orchestrator", 24), **{t["id"]: t for t in TASKS}})

def dec(did, title, author, ago):
    return {"id": did, "title": title, "author": author, "created_at": now - ago}
DECS = [
    dec("d1", "Roadmap: 5 milestones (auth → videos → watch/comments → subs/feed → studio)", "orchestrator", 5300),
    dec("d2", "Auth: JWT RS256, refresh tokens, bcrypt password hashing", "backend", 5100),
    dec("d3", "Postgres + SQLAlchemy; UUID primary keys throughout", "backend", 5000),
    dec("d4", "Frontend: React + Vite + react-router; all data via services/api.js", "frontend", 4900),
    dec("d5", "Video visibility enum: public / unlisted / private", "backend", 3800),
    dec("d6", "Denormalize view & like counts onto videos for feed performance", "backend", 1700),
    dec("d7", "Comments paginated 20/page, newest-first", "backend", 900),
    dec("d8", "Home feed ranking = recency × affinity from subscriptions (M4)", "orchestrator", 300),
]
dump("workhub_decisions.json", {"_meta": meta("orchestrator", 8), **{d["id"]: d for d in DECS}})

# ── workhub pages (roadmap + kickoffs) ───────────────────────────────────────
MILES = [
    {"version": "1.0.0", "name": "Auth, Channels & Profiles"},
    {"version": "1.1.0", "name": "Videos & Upload"},
    {"version": "1.2.0", "name": "Watch, Comments & Likes"},
    {"version": "1.3.0", "name": "Subscriptions & Home Feed"},
    {"version": "1.4.0", "name": "Creator Studio & Analytics"},
]
dump("workhub_pages.json", {
    "_meta": meta("orchestrator"),
    "roadmap": {"id": "roadmap", "kind": "document", "title": "Roadmap", "status": "active",
                "metadata": {"decisions": [{"decision": {"kind": "milestone_plan", "section": "roadmap",
                                                         "content": {"milestones": MILES}}}]}},
    "m1_kickoff": {"id": "m1_kickoff", "title": "M1 kickoff — Auth, Channels & Profiles", "kind": "meeting", "status": "complete"},
    "m2_kickoff": {"id": "m2_kickoff", "title": "M2 kickoff — Videos & Upload", "kind": "meeting", "status": "complete"},
    "m3_kickoff": {"id": "m3_kickoff", "title": "M3 kickoff — Watch, Comments & Likes", "kind": "meeting", "status": "active"},
})

# ── CODEHUB commits (15) + PRs (5) + releases (2) ────────────────────────────
def commit(cid, branch, author, summary, files, ago):
    return {"id": cid, "branch": branch, "author": author, "diff_summary": summary, "files": files, "created_at": now - ago}
COMMITS = [
    commit("k01", "agent/backend", "backend", "Auth: register/login + JWT RS256", ["app/backend/oauth_routes.py", "app/backend/models.py"], 5000),
    commit("k02", "agent/backend", "backend", "Channels CRUD + channel videos", ["app/backend/custom_routes.py"], 4700),
    commit("k03", "agent/frontend", "frontend", "Login/Register/Channel pages + NavBar", ["app/frontend/src/pages/LoginPage.jsx", "app/frontend/src/components/NavBar.jsx"], 4500),
    commit("k04", "integration", "orchestrator", "merge agent/* → integration (M1 1.0.0)", ["app/backend/main.py", "app/frontend/src/App.jsx"], 4200),
    commit("k05", "agent/backend", "backend", "Video model + upload + list/detail/delete", ["app/backend/custom_routes.py", "app/backend/models.py"], 2400),
    commit("k06", "agent/backend", "backend", "Video search endpoint", ["app/backend/custom_routes.py"], 2200),
    commit("k07", "agent/frontend", "frontend", "Home feed + Upload + Search pages", ["app/frontend/src/pages/HomePage.jsx", "app/frontend/src/pages/UploadPage.jsx"], 2000),
    commit("k08", "agent/frontend", "frontend", "VideoCard + VideoGrid + Sidebar components", ["app/frontend/src/components/VideoCard.jsx"], 1800),
    commit("k09", "integration", "orchestrator", "merge agent/* → integration (M2 1.1.0)", ["app/backend/main.py", "app/frontend/src/App.jsx"], 1500),
    commit("k10", "agent/backend", "backend", "Comments table + list/create endpoints", ["app/backend/custom_routes.py", "app/backend/models.py"], 700),
    commit("k11", "agent/frontend", "frontend", "WatchPage scaffold: player + comment list", ["app/frontend/src/pages/WatchPage.jsx"], 380),
    commit("k12", "agent/backend", "backend", "video_likes table + like route stubs", ["app/backend/models.py"], 240),
    commit("k13", "agent/frontend", "frontend", "LikeButton + CommentForm components", ["app/frontend/src/components/LikeButton.jsx"], 150),
    commit("k14", "agent/backend", "backend", "wire POST /api/videos/{id}/comments", ["app/backend/custom_routes.py"], 95),
    commit("k15", "agent/frontend", "frontend", "WatchPage: wire comments to services/api.js", ["app/frontend/src/pages/WatchPage.jsx"], 40),
]
dump("codehub_commits.json", {"_meta": meta("orchestrator", 15), **{c["id"]: c for c in COMMITS}})

def pr(num, title, author, branch, status, ago):
    return {"id": num, "number": num, "title": title, "author": author, "source_branch": branch, "status": status, "created_at": now - ago}
PRS = [
    pr(1, "M1: Auth, channels & profiles", "backend", "agent/backend", "merged", 4250),
    pr(2, "M1: Auth & channel pages", "frontend", "agent/frontend", "merged", 4230),
    pr(3, "M2: Videos, upload, search", "backend", "agent/backend", "merged", 1550),
    pr(4, "M2: Home/upload/search UI", "frontend", "agent/frontend", "merged", 1520),
    pr(5, "M3: Watch page + comments (WIP)", "frontend", "agent/frontend", "open", 120),
]
dump("codehub_pull_requests.json", {"_meta": meta("orchestrator", 5), **{str(p["number"]): p for p in PRS}})

dump("codehub_releases.json", {
    "_meta": meta("orchestrator", 2),
    "1.0.0": {"id": "1.0.0", "tag": "1.0.0", "source": "integration", "branch": "release-v1.0.0",
              "notes": "M1: auth + channels + profiles validated; api_smoke + ui_smoke green.", "created_at": now - 4200},
    "1.1.0": {"id": "1.1.0", "tag": "1.1.0", "source": "integration", "branch": "release-v1.1.0",
              "notes": "M2: video model + upload + search + my-videos validated.", "created_at": now - 1500},
})

# ── EVENTHUB activity feed (14) ──────────────────────────────────────────────
FEED = [
    ("registryhub", "ui_component_registered", {"name": "CommentForm", "by": "frontend"}, 35, "normal"),
    ("codehub", "commit_pushed", {"branch": "agent/frontend", "summary": "WatchPage: wire comments"}, 40, "normal"),
    ("registryhub", "endpoint_implemented", {"endpoint_id": "POST /api/videos/{id}/comments", "by": "backend"}, 95, "normal"),
    ("workhub", "task_claimed", {"task": "Video like/unlike endpoints", "by": "backend"}, 150, "normal"),
    ("registryhub", "ui_page_registered", {"name": "watch", "route": "/watch/{id}", "status": "defined"}, 200, "normal"),
    ("registryhub", "contract_test_recorded", {"endpoint_id": "GET /api/videos/{id}/comments", "verdict": "pass"}, 260, "normal"),
    ("workhub", "decision_recorded", {"title": "Comments paginated 20/page"}, 900, "normal"),
    ("codehub", "commit_pushed", {"branch": "agent/backend", "summary": "Comments table + endpoints"}, 700, "normal"),
    ("runhub", "api_smoke_passed", {"milestone": "1.1.0", "probes": 5, "failed": 0}, 1450, "high"),
    ("codehub", "release_cut", {"tag": "1.1.0", "notes": "M2 validated"}, 1500, "high"),
    ("codehub", "pull_request_merged", {"number": 4, "title": "M2: Home/upload/search UI"}, 1520, "normal"),
    ("registryhub", "endpoint_implemented", {"endpoint_id": "GET /api/videos/search", "by": "backend"}, 2200, "normal"),
    ("runhub", "api_smoke_passed", {"milestone": "1.0.0", "probes": 4, "failed": 0}, 4150, "high"),
    ("codehub", "release_cut", {"tag": "1.0.0", "notes": "M1 validated"}, 4200, "high"),
]
EVS = {}
for i, (hub, et, payload, ago, pri) in enumerate(FEED):
    eid = f"ev_{i:03d}"
    EVS[eid] = {"id": eid, "source_hub": hub, "event_type": et, "priority": pri, "payload": payload, "created_at": now - ago}
dump("eventhub_events.json", {"_meta": meta("eventhub", 90), **EVS})

# ── verification CHAINS (7) ──────────────────────────────────────────────────
def chain(cid, name, desc, status, steps, last=None):
    return {"id": cid, "name": name, "description": desc, "status": status,
            "steps": [{"method": m, "path": p, "expect": e} for (m, p, e) in steps], "last_result": last}
CHAINS = [
    chain("auth_flow", "Auth flow", "register → login → authenticated fetch", "passing",
          [("POST", "/auth/register", 201), ("POST", "/auth/login", 200), ("GET", "/auth/me", 200)], {"passed": True, "steps_passed": 3, "steps": 3}),
    chain("channel_lifecycle", "Channel lifecycle", "create → fetch → update → list videos", "passing",
          [("POST", "/api/channels", 201), ("GET", "/api/channels/{id}", 200), ("PUT", "/api/channels/{id}", 200), ("GET", "/api/channels/{id}/videos", 200)], {"passed": True}),
    chain("video_publish", "Video publish & fetch", "upload → list feed → fetch detail", "passing",
          [("POST", "/api/videos", 201), ("GET", "/api/videos", 200), ("GET", "/api/videos/{id}", 200)], {"passed": True}),
    chain("video_search", "Video search", "publish → search by query", "passing",
          [("POST", "/api/videos", 201), ("GET", "/api/videos/search", 200)], {"passed": True}),
    chain("comment_flow", "Comment flow", "post comment → list comments", "passing",
          [("POST", "/api/videos/{id}/comments", 201), ("GET", "/api/videos/{id}/comments", 200)], {"passed": True}),
    chain("like_flow", "Like / unlike (M3 — in progress)", "like → unlike → related", "pending",
          [("POST", "/api/videos/{id}/like", 200), ("DELETE", "/api/videos/{id}/like", 200), ("GET", "/api/videos/{id}/related", 200)], None),
    chain("subscribe_flow", "Subscribe & feed (M4 — planned)", "subscribe → home feed includes channel", "pending",
          [("POST", "/api/channels/{id}/subscribe", 201), ("GET", "/api/feed/subscriptions", 200)], None),
]
dump("registryhub_verification_chains.json", {"_meta": meta("verifier", 11), **{c["id"]: c for c in CHAINS}})

# ── CONTRACT TESTS (per implemented endpoint) ────────────────────────────────
def ctest(eid, ok, code): return {"endpoint_id": eid, "result": {"verdict": "pass" if ok else "fail", "passed": ok, "status_code": code}}
CT = {}
for e in EPS:
    if e["status"] == IMPL:
        code = {"POST": 201, "DELETE": 204}.get(e["method"], 200)
        if e["path"].endswith("/login") or e["path"] == "/auth/me":
            code = 200
        CT[e["id"]] = ctest(e["id"], True, code)
dump("registryhub_contract_tests.json", {"_meta": meta("verifier", 16), **CT})

# ── RUNHUB validation runs (3) ───────────────────────────────────────────────
def probe(m, p, code): return {"method": m, "path": p, "status": code, "ok": 200 <= code < 400}
def run(rid, ms, ago, dur, status, fails, ticks, probes):
    return {"id": rid, "status": status, "milestone": ms, "started_at": now - ago, "finished_at": now - ago + dur,
            "coordination_ticks": ticks, "fail_count": fails, "healthcheck": "ok", "probes": probes}
RUNS = [
    run("run_m1", "1.0.0", 4300, 175, "completed", 0, 9,
        [probe("POST", "/auth/register", 201), probe("POST", "/auth/login", 200), probe("GET", "/auth/me", 200),
         probe("POST", "/api/channels", 201), probe("GET", "/api/channels/{id}", 200)]),
    run("run_m2", "1.1.0", 1600, 205, "completed", 0, 11,
        [probe("GET", "/api/videos", 200), probe("GET", "/api/videos/{id}", 200), probe("POST", "/api/videos", 201),
         probe("DELETE", "/api/videos/{id}", 204), probe("GET", "/api/videos/search", 200)]),
    run("run_m3", "1.2.0", 160, 80, "running", 0, 4,
        [probe("GET", "/api/videos/{id}/comments", 200), probe("POST", "/api/videos/{id}/comments", 201)]),
]
dump("runhub_runs.json", {"_meta": meta("verifier", 5), **{r["id"]: r for r in RUNS}})

# ── token-cost metrics (higher than smoke-notes' ~$30; bigger 5-milestone app) ─
MODEL = "gemini-3.1-pro-preview"
def _cost(ti, to): return round(ti / 1e6 * 1.25 + to / 1e6 * 5.0, 2)
def usage(ti, to, reqs):
    c = _cost(ti, to)
    return {"total_input": ti, "total_output": to, "total_cost": c, "requests": reqs,
            "by_model": {MODEL: {"input": ti, "output": to, "cost": c}}}
def mstone(ti, to, reqs): return {"input": ti, "output": to, "cost": _cost(ti, to), "requests": reqs}
dump("system_token_usage.json", {
    # per-agent (sums to ≈ $46, well above smoke-notes' $30)
    "orchestrator": usage(6_500_000, 480_000, 540),
    "backend":      usage(9_200_000, 720_000, 680),
    "frontend":     usage(6_800_000, 560_000, 590),
    "verifier":     usage(2_900_000, 210_000, 320),
    "debugger":     usage(1_800_000, 150_000, 240),
    "knowledge":    usage(900_000, 80_000, 110),
    # per-milestone — ALL spend is on M1/M2 (done) + M3 (active); M4/M5 haven't
    # run yet → $0. Sums match the per-agent totals (28.1M in / 2.2M out / 2480 calls).
    "_by_milestone": {
        "M1 · Auth, Channels & Profiles":  mstone(8_300_000, 630_000, 760),
        "M2 · Videos & Upload":            mstone(9_300_000, 715_000, 840),
        "M3 · Watch, Comments & Likes":    mstone(10_500_000, 855_000, 880),
        "M4 · Subscriptions & Home Feed":  mstone(0, 0, 0),
        "M5 · Creator Studio & Analytics": mstone(0, 0, 0),
    },
})

print("DEEPENED youtube hubs:")
print(f"  endpoints {len(EPS)} | tables {len(TBLS)} | pages {len(PAGES)} | components {len(COMPS)}")
print(f"  tasks {len(TASKS)} | decisions {len(DECS)} | commits {len(COMMITS)} | PRs {len(PRS)} | releases 2")
print(f"  events {len(EVS)} | chains {len(CHAINS)} | contract_tests {len(CT)} | runs {len(RUNS)}")
