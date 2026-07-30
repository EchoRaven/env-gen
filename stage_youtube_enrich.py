#!/usr/bin/env python3
"""Enrich the staged YouTube demo so the Env Forge detail page reads as a LIVE
mid-generation env: a populated activity feed (eventhub), a believable task board
(progress %), commit history (M1/M2 merges), and per-agent action logs so the
agent drawers show real recent actions. Schemas match hub_reader's readers exactly.
Demo-only; no real generation. Re-run anytime; touches agent logs so agents read
'active' (the 180s liveness window) at show time.
"""
import json, os, time
from pathlib import Path

ROOT = Path("/data/common/haibotong/forgingground-gen/generated/youtube")
HUBS = ROOT / "shared" / "hubs"
now = time.time()

def meta(by, v=1):
    return {"version": v, "last_modified_by": by, "last_modified_at": now}

def dump(name, obj):
    (HUBS / name).write_text(json.dumps(obj, indent=2), encoding="utf-8")

# ── eventhub: activity feed (hub_reader._events: event_type/source_hub/priority/payload/created_at)
events = {}
feed = [
    ("registryhub", "endpoint_implemented", {"endpoint_id": "POST /api/videos/{id}/comments", "by": "backend"}, 40),
    ("codehub", "commit_pushed", {"branch": "agent/frontend", "summary": "WatchPage: player + comments wired"}, 95),
    ("registryhub", "ui_page_registered", {"name": "watch", "route": "/watch/{id}", "status": "defined", "by": "frontend"}, 150),
    ("runhub", "api_smoke_passed", {"milestone": "1.1.0", "probes": 9, "failed": 0}, 320),
    ("workhub", "task_claimed", {"task": "Implement video like/unlike endpoints", "by": "backend"}, 380),
    ("codehub", "release_cut", {"tag": "1.1.0", "notes": "M2: video model + upload validated"}, 1500),
    ("registryhub", "endpoint_implemented", {"endpoint_id": "GET /api/videos/{id}/comments", "by": "backend"}, 1900),
    ("codehub", "release_cut", {"tag": "1.0.0", "notes": "M1: auth + channels + profiles validated"}, 4200),
]
for i, (hub, et, payload, ago) in enumerate(feed):
    eid = f"ev_{i:03d}"
    events[eid] = {"id": eid, "source_hub": hub, "event_type": et,
                   "priority": "high" if "release" in et else "normal",
                   "payload": payload, "created_at": now - ago}
dump("eventhub_events.json", {"_meta": meta("eventhub", 88), **events})

# ── workhub tasks: progress board (M1/M2 done, M3 in-flight, M4/M5 pending)
def task(tid, title, assignee, status, desc, result=""):
    return {"id": tid, "title": title, "assignee": assignee, "status": status,
            "description": desc, "claimed_by": assignee if status != "pending" else "",
            "result": result}
tasks = {t["id"]: t for t in [
    task("t1", "Auth: register/login + JWT", "backend", "completed", "M1 auth surface", "api_smoke green"),
    task("t2", "Channels & profiles CRUD", "backend", "completed", "M1 channels", "validated"),
    task("t3", "Login/Register/Channel pages", "frontend", "completed", "M1 UI", "wired + smoke green"),
    task("t4", "Video model + upload endpoint", "backend", "completed", "M2 videos", "validated"),
    task("t5", "Home feed + Upload page", "frontend", "completed", "M2 UI", "wired"),
    task("t6", "Comments endpoints", "backend", "completed", "M3 comments", "implemented"),
    task("t7", "Watch page: player + comments", "frontend", "in_progress", "M3 watch UI", ""),
    task("t8", "Video like/unlike endpoints", "backend", "in_progress", "M3 likes", ""),
    task("t9", "Related-videos endpoint", "backend", "pending", "M3 related", ""),
    task("t10", "Subscriptions & home-feed ranking", "backend", "pending", "M4", ""),
    task("t11", "Creator Studio + analytics", "frontend", "pending", "M5", ""),
]}
dump("workhub_tasks.json", {"_meta": meta("orchestrator", 12), **tasks})

# ── codehub commits (hub_reader._commits: branch/author/diff_summary/files/created_at)
def commit(cid, branch, author, summary, files, ago):
    return {"id": cid, "branch": branch, "author": author, "diff_summary": summary,
            "files": files, "created_at": now - ago}
commits = {c["id"]: c for c in [
    commit("c6", "agent/frontend", "frontend", "WatchPage scaffold: player + comment list",
           ["app/frontend/src/pages/WatchPage.jsx"], 95),
    commit("c5", "agent/backend", "backend", "Comments endpoints + comments table",
           ["app/backend/custom_routes.py", "app/backend/models.py"], 600),
    commit("c4", "integration", "orchestrator", "merge agent/* → integration (M2 1.1.0)",
           ["app/backend/main.py", "app/frontend/src/App.jsx"], 1500),
    commit("c3", "agent/backend", "backend", "Video model + upload + my-videos list",
           ["app/backend/custom_routes.py"], 1900),
    commit("c2", "agent/frontend", "frontend", "Home feed + Upload page",
           ["app/frontend/src/pages/HomeFeed.jsx", "app/frontend/src/pages/UploadPage.jsx"], 2400),
    commit("c1", "integration", "orchestrator", "merge agent/* → integration (M1 1.0.0)",
           ["app/backend/main.py", "app/frontend/src/App.jsx"], 4200),
]}
dump("codehub_commits.json", {"_meta": meta("orchestrator", 6), **commits})

# ── system token usage → COST panel (hub_reader._metrics: per-key total_input/output/cost + by_model)
MODEL = "gemini-3.1-pro-preview"
def usage(ti, to):
    cost = round(ti / 1e6 * 1.25 + to / 1e6 * 5.0, 2)  # gemini pro in/out rates
    return {"total_input": ti, "total_output": to, "total_cost": cost,
            "by_model": {MODEL: {"input": ti, "output": to, "cost": cost}}}
dump("system_token_usage.json", {
    "orchestrator": usage(3_500_000, 250_000),
    "backend":      usage(4_100_000, 320_000),
    "frontend":     usage(2_600_000, 190_000),
    "verifier":     usage(1_250_000, 70_000),
    "debugger":     usage(820_000, 45_000),
    "knowledge":    usage(540_000, 25_000),
})

# ── verification chains → CHAINS panel (hub_reader._chains: name/status/steps[method,path,expect]/last_result)
def chain(cid, name, desc, status, steps, last=None):
    return {"id": cid, "name": name, "description": desc, "status": status,
            "steps": [{"method": m, "path": p, "expect": e} for (m, p, e) in steps],
            "last_result": last}
chains = {c["id"]: c for c in [
    chain("auth_flow", "Auth flow", "register → login → authenticated fetch", "passing",
          [("POST", "/auth/register", 201), ("POST", "/auth/login", 200), ("GET", "/api/channels/{id}", 200)],
          {"passed": True, "steps_passed": 3, "steps": 3}),
    chain("channel_lifecycle", "Channel lifecycle", "create channel → fetch → update", "passing",
          [("POST", "/api/channels", 201), ("GET", "/api/channels/{id}", 200), ("PUT", "/api/channels/{id}", 200)],
          {"passed": True, "steps_passed": 3, "steps": 3}),
    chain("video_publish", "Video publish & fetch", "upload video → list feed → fetch detail", "passing",
          [("POST", "/api/videos", 201), ("GET", "/api/videos", 200), ("GET", "/api/videos/{id}", 200)],
          {"passed": True, "steps_passed": 3, "steps": 3}),
    chain("comment_flow", "Comment flow", "post comment → list comments on video", "passing",
          [("POST", "/api/videos/{id}/comments", 201), ("GET", "/api/videos/{id}/comments", 200)],
          {"passed": True, "steps_passed": 2, "steps": 2}),
    chain("like_flow", "Like / unlike (M3 — in progress)", "like → unlike → related videos", "pending",
          [("POST", "/api/videos/{id}/like", 200), ("DELETE", "/api/videos/{id}/like", 200),
           ("GET", "/api/videos/{id}/related", 200)], None),
]}
dump("registryhub_verification_chains.json", {"_meta": meta("verifier", 9), **chains})

# ── per-endpoint contract tests (hub_reader._contract_tests: endpoint_id + result{verdict,status_code})
def ctest(eid, ok, code):
    return {"endpoint_id": eid, "result": {"verdict": "pass" if ok else "fail",
                                           "passed": ok, "status_code": code}}
contract_tests = {eid: ctest(eid, ok, code) for eid, ok, code in [
    ("POST /auth/register", True, 201), ("POST /auth/login", True, 200),
    ("GET /api/channels/{id}", True, 200), ("POST /api/channels", True, 201),
    ("PUT /api/channels/{id}", True, 200), ("GET /api/videos", True, 200),
    ("GET /api/videos/{id}", True, 200), ("POST /api/videos", True, 201),
    ("PUT /api/videos/{id}", True, 200), ("DELETE /api/videos/{id}", True, 204),
    ("GET /api/videos/{id}/comments", True, 200), ("POST /api/videos/{id}/comments", True, 201),
]}
dump("registryhub_contract_tests.json", {"_meta": meta("verifier", 12), **contract_tests})

# ── validation runs + probes → RUNS tab, probes panel, api_smoke gate (hub_reader._runs_raw/_probes/list_runs/_gates)
def probe(m, p, code):
    return {"method": m, "path": p, "status": code, "ok": 200 <= code < 400}
def run(rid, ms, ago_start, dur, status, fails, ticks, probes):
    return {"id": rid, "status": status, "milestone": ms, "started_at": now - ago_start,
            "finished_at": now - ago_start + dur, "coordination_ticks": ticks,
            "fail_count": fails, "healthcheck": "ok", "probes": probes}
runs = {r["id"]: r for r in [
    run("run_m1", "1.0.0", 4300, 175, "completed", 0, 9,
        [probe("POST", "/auth/register", 201), probe("POST", "/auth/login", 200),
         probe("POST", "/api/channels", 201), probe("GET", "/api/channels/{id}", 200)]),
    run("run_m2", "1.1.0", 1600, 205, "completed", 0, 11,
        [probe("POST", "/auth/login", 200), probe("GET", "/api/videos", 200),
         probe("GET", "/api/videos/{id}", 200), probe("POST", "/api/videos", 201),
         probe("GET", "/api/channels/{id}", 200)]),
    run("run_m3", "1.2.0", 160, 80, "running", 0, 4,
        [probe("GET", "/api/videos/{id}/comments", 200),
         probe("POST", "/api/videos/{id}/comments", 201)]),
]}
dump("runhub_runs.json", {"_meta": meta("verifier", 5), **runs})

# ── per-agent action logs → agent drawers + 'active' status (mtime < 180s)
LOGS = ROOT / ".agent_logs"
def agent_log(role, actions):
    d = LOGS / f"{role} Agent"
    d.mkdir(parents=True, exist_ok=True)
    lines = []
    for k, (tool, args, result) in enumerate(actions):
        lines.append(json.dumps({
            "timestamp": time.strftime("%H:%M:%S", time.localtime(now - (len(actions) - k) * 12)),
            "event_type": "tool_call", "content": f"{tool}({args})",
            "metadata": {"result": result, "ok": True}}))
    (d / "actions.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

agent_log("Orchestrator", [
    ("check_inbox", "{}", "{'count': 3}"),
    ("coordination_tick", "{'phase': 'implementation'}", "dispatched watch-page work"),
    ("read_registry", "{'hub': 'registryhub'}", "15 endpoints, 7 pages"),
])
agent_log("Backend Lead", [
    ("registryhub_register_endpoint", "{'method':'POST','path':'/api/videos/{id}/comments'}", "ok"),
    ("write_file", "{'path':'app/backend/custom_routes.py'}", "wrote 142 lines"),
    ("registryhub_register_endpoint", "{'method':'POST','path':'/api/videos/{id}/like'}", "status=defined"),
])
agent_log("Frontend Lead", [
    ("registryhub_register_ui_page", "{'name':'watch','route':'/watch/{id}'}", "registered (defined)"),
    ("write_file", "{'path':'app/frontend/src/pages/WatchPage.jsx'}", "wrote player + comments"),
    ("read_file", "{'path':'app/frontend/src/services/api.js'}", "ok"),
])
agent_log("Verifier", [
    ("run_api_smoke", "{'milestone':'1.1.0'}", "9 probes, 0 failed"),
    ("record_check", "{'name':'api_smoke','status':'pass'}", "ok"),
])
agent_log("Knowledge", [
    ("get_skill", "{'name':'release-readiness'}", "returned checklist"),
])
agent_log("Debugger", [
    ("check_inbox", "{}", "{'count': 0}"),
])

# touch all agent logs so they read 'active' (180s window) at show time
for p in LOGS.rglob("*.jsonl"):
    os.utime(p, (now, now))

print("ENRICHED youtube demo:")
print("  events:", len(events), "| tasks:", len(tasks),
      "(", sum(1 for t in tasks.values() if t["status"] == "completed"), "done )",
      "| commits:", len(commits), "| agent logs: 6 roles (active)")
