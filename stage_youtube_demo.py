#!/usr/bin/env python3
"""Stage a READY-MADE YouTube demo project frozen at milestone 3 of 5 (demo purpose —
NOT a real generation). Produces the project + hub state the live_monitor reads so the
Overview shows M1/M2 released, M3 active (current), M4/M5 planned, plus the registered
contract (endpoints/tables/ui_pages) and a previewUrl → the hand-built fancy app on :8090.
"""
import json, time
from pathlib import Path

ROOT = Path("/data/common/haibotong/forgingground-gen/generated/youtube")
HUBS = ROOT / "shared" / "hubs"
HUBS.mkdir(parents=True, exist_ok=True)
now = 1781905000.0  # fixed demo timestamps (deterministic)

def meta(by="orchestrator", v=3):
    return {"version": v, "last_modified_by": by, "last_modified_at": now}

def dump(name, obj):
    (HUBS / name).write_text(json.dumps(obj, indent=2), encoding="utf-8")

# ---- project.json + .checkpoint (in-generation, on M3) ----
(ROOT / "project.json").write_text(json.dumps({
    "agents_used": ["orchestrator", "backend", "frontend", "verifier", "debugger", "knowledge"],
    "created_at": now - 5400, "last_active_at": now - 20,
    "description": "Build a YouTube-style video platform (channels, videos, upload, watch, "
                   "comments, likes, subscriptions, home feed, search, and a Creator Studio).",
    "id": "proj_youtube_demo", "name": "youtube", "schema_version": 1,
    "status": "active",
}, indent=2), encoding="utf-8")

(ROOT / ".checkpoint").write_text(json.dumps({
    "version": "1.0", "name": "youtube",
    "description": "YouTube-style video platform — 5-milestone roadmap.",
    "domain_type": "web_app", "status": "in_progress",
    "current_phase": "agent_workflow", "milestone_index": 3, "total_milestones": 5,
    "started_at": now - 5400, "last_updated": now - 20,
}, indent=2), encoding="utf-8")

# ---- previewUrl → fancy static app on :8090 ----
(ROOT / "config.yaml").write_text(
    "preview_url: http://127.0.0.1:8090/index.html\n"
    "frontend:\n  preview_url: http://127.0.0.1:8090/index.html\n  host_port: 8090\n",
    encoding="utf-8")

# ---- milestone roadmap (5) + kickoff pages (M1/M2 done, M3 active) ----
MILES = [
    {"version": "1.0.0", "name": "Auth, Channels & Profiles"},
    {"version": "1.1.0", "name": "Videos & Upload"},
    {"version": "1.2.0", "name": "Watch, Comments & Likes"},
    {"version": "1.3.0", "name": "Subscriptions & Home Feed"},
    {"version": "1.4.0", "name": "Creator Studio & Analytics"},
]
dump("workhub_pages.json", {
    "_meta": meta("orchestrator"),
    "roadmap": {"id": "roadmap", "kind": "document", "title": "Roadmap",
                "status": "active",
                "metadata": {"decisions": [
                    {"decision": {"kind": "milestone_plan", "section": "roadmap",
                                  "content": {"milestones": MILES}}}]}},
    "m1_kickoff": {"id": "m1_kickoff", "title": "M1 kickoff — Auth, Channels & Profiles",
                   "kind": "meeting", "status": "complete"},
    "m2_kickoff": {"id": "m2_kickoff", "title": "M2 kickoff — Videos & Upload",
                   "kind": "meeting", "status": "complete"},
    "m3_kickoff": {"id": "m3_kickoff", "title": "M3 kickoff — Watch, Comments & Likes",
                   "kind": "meeting", "status": "active"},
})

# ---- releases: M1 (1.0.0) + M2 (1.1.0) cut; M3 (1.2.0) NOT yet → active ----
dump("codehub_releases.json", {
    "_meta": meta("orchestrator", 2),
    "1.0.0": {"id": "1.0.0", "tag": "1.0.0", "source": "integration",
              "notes": "M1: auth + channels + profiles validated; api_smoke + ui_smoke green.",
              "created_at": now - 4200},
    "1.1.0": {"id": "1.1.0", "tag": "1.1.0", "source": "integration",
              "notes": "M2: video model + upload + my-videos list validated.",
              "created_at": now - 1500},
})

# ---- registered contract: endpoints (M1/M2 implemented, M3 in progress) ----
def ep(method, path, status, schema=None, m=None):
    return {"id": f"{method} {path}", "method": method, "path": path,
            "status": status, "provider": "backend",
            "schema": schema or {}, "metadata": {"milestone": m}}

endpoints = {}
for e in [
    # M1 (implemented)
    ep("POST", "/auth/register", "implemented", m=1),
    ep("POST", "/auth/login", "implemented", m=1),
    ep("GET", "/api/channels/{id}", "implemented",
       {"response_key": "item"}, 1),
    ep("POST", "/api/channels", "implemented", {"response_key": "item"}, 1),
    ep("PUT", "/api/channels/{id}", "implemented", {"response_key": "item"}, 1),
    # M2 (implemented)
    ep("GET", "/api/videos", "implemented", {"response_key": "items"}, 2),
    ep("GET", "/api/videos/{id}", "implemented", {"response_key": "item"}, 2),
    ep("POST", "/api/videos", "implemented", {"response_key": "item"}, 2),
    ep("PUT", "/api/videos/{id}", "implemented", {"response_key": "item"}, 2),
    ep("DELETE", "/api/videos/{id}", "implemented", {"response_key": "item"}, 2),
    # M3 (IN PROGRESS — some implemented, some still defined)
    ep("GET", "/api/videos/{id}/comments", "implemented", {"response_key": "items"}, 3),
    ep("POST", "/api/videos/{id}/comments", "implemented", {"response_key": "item"}, 3),
    ep("POST", "/api/videos/{id}/like", "defined", {"response_key": "item"}, 3),
    ep("DELETE", "/api/videos/{id}/like", "defined", {"response_key": "item"}, 3),
    ep("GET", "/api/videos/{id}/related", "defined", {"response_key": "items"}, 3),
]:
    endpoints[e["id"]] = e
dump("registryhub_endpoints.json", {"_meta": meta("backend", 47), **endpoints})

# ---- tables ----
def tbl(name, cols, status="implemented"):
    return {"id": name, "name": name, "status": status, "provider": "backend",
            "columns": [{"name": c} for c in cols]}
tables = {t["name"]: t for t in [
    tbl("users", ["id", "email", "password_hash", "name", "created_at"]),
    tbl("channels", ["id", "owner_id", "name", "handle", "description", "avatar_url", "banner_url"]),
    tbl("videos", ["id", "channel_id", "title", "description", "thumbnail_url", "video_url",
                   "duration", "views", "visibility", "created_at"]),
    tbl("comments", ["id", "video_id", "author_id", "text", "likes", "created_at"], "implemented"),
    tbl("video_likes", ["id", "video_id", "user_id", "created_at"], "defined"),
    tbl("subscriptions", ["id", "subscriber_id", "channel_id", "created_at"], "defined"),
]}
dump("registryhub_tables.json", {"_meta": meta("backend", 12), **tables})

# ---- ui_pages (M1/M2 implemented + M3 watch in progress; M4/M5 planned) ----
def page(name, route, component, status, apis, m):
    return {"id": f"page:ui:{name}", "name": name, "kind": "ui_page", "route": route,
            "component": component, "status": status, "apis_used": apis,
            "metadata": {"milestone": m}}
pages = {p["name"]: p for p in [
    page("login", "/login", "LoginPage", "implemented", ["POST /auth/login"], 1),
    page("register", "/register", "RegisterPage", "implemented", ["POST /auth/register"], 1),
    page("channel", "/channel/{handle}", "ChannelPage", "implemented", ["GET /api/channels/{id}"], 1),
    page("upload", "/upload", "UploadPage", "implemented", ["POST /api/videos"], 2),
    page("home", "/", "HomePage", "implemented", ["GET /api/videos"], 2),
    page("watch", "/watch/{id}", "WatchPage", "defined",
         ["GET /api/videos/{id}", "GET /api/videos/{id}/comments", "POST /api/videos/{id}/comments",
          "POST /api/videos/{id}/like", "GET /api/videos/{id}/related"], 3),
    page("studio", "/studio", "StudioPage", "defined", ["GET /api/videos"], 5),
]}
dump("registryhub_ui_pages.json", {"_meta": meta("frontend", 21), **pages})

# ---- a few recent eventhub events for the "live activity" feel ----
dump("eventhub_events.json", {"_meta": meta("eventhub", 88), "events": [
    {"type": "ui_page_registered", "agent": "frontend", "at": now - 300,
     "data": {"name": "watch", "route": "/watch/{id}", "status": "defined"}},
    {"type": "api_test_recorded", "agent": "verifier", "at": now - 240,
     "data": {"endpoint_id": "GET /api/videos/{id}/comments", "verdict": "pass"}},
    {"type": "endpoint_implemented", "agent": "backend", "at": now - 120,
     "data": {"endpoint_id": "POST /api/videos/{id}/comments"}},
]})

print("STAGED youtube demo at", ROOT)
print("  milestones: M1,M2 released · M3 ACTIVE (current) · M4,M5 planned")
print("  endpoints:", len(endpoints), "| tables:", len(tables), "| ui_pages:", len(pages))
print("  previewUrl: http://127.0.0.1:8090/index.html")
