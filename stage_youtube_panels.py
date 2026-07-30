#!/usr/bin/env python3
"""Fill the remaining Env Forge panels for the YouTube demo: knowledge (.memory),
references (design spec / must-have checklist), approvals (ask-mode + pending
requests), and the User Console chat (real human↔agent threads via the engine
EventHub). Uses the engine's own APIs so formats never drift. Demo-only.
Run AFTER stage_youtube_enrich.py. Re-touches agent logs so agents read 'active'.
"""
import sys, json, time, os
from pathlib import Path

sys.path.insert(0, "agent")
sys.path.insert(0, "agent/env_generator/llm_generator")

GEN = "generated/youtube"
ROOT = Path(GEN); HUBS = ROOT / "shared" / "hubs"; now = time.time()

# ── 1) knowledge → .memory/<agent>.knowledge.jsonl (hub_reader._knowledge) ──
mem = ROOT / ".memory"; mem.mkdir(exist_ok=True)
KN = {
    "orchestrator": [("decision", "5-milestone roadmap locked: auth → videos/upload → watch/comments/likes → subscriptions/feed → Creator Studio.", 0.95, "kickoff")],
    "backend": [
        ("tech_context", "videos table: channel_id FK, visibility enum (public/unlisted/private), denormalized view+like counts for feed perf.", 0.85, "implementation"),
        ("decision", "Comments paginated 20/page newest-first; like is a unique (video_id,user_id) row, toggled idempotently.", 0.75, "implementation"),
    ],
    "frontend": [
        ("tech_context", "Every page consumes services/api.js named exports (getVideos/postComment/…) — never raw fetch(); keeps auth header + base URL central.", 0.9, "implementation"),
        ("decision", "WatchPage layout: player + title/actions, channel row with Subscribe, comments below, related rail right (single-column on mobile).", 0.7, "implementation"),
    ],
    "verifier": [("observation", "M1/M2 api_smoke green; comment endpoints contract-validated. like/unlike + related still pending implementation.", 0.85, "validation")],
    "knowledge": [("reference", "YouTube reference: 4-col desktop grid, red accent #FF0000, Roboto, hover-scrub thumbnails.", 0.6, "design")],
}
for agent, items in KN.items():
    lines = [json.dumps({"content": c, "category": cat, "importance": imp,
                         "phase": ph, "timestamp": now - i * 320})
             for i, (cat, c, imp, ph) in enumerate(items)]
    (mem / f"{agent}.knowledge.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

# ── 2) references → design/reference_spec.json (hub_reader._references screens) ──
design = ROOT / "design"; design.mkdir(exist_ok=True)
screens = [
    {"name": "Home Feed", "route_hint": "/", "must_have": [
        "Top nav: logo, search bar, upload + avatar", "Responsive video grid (thumbnail, title, channel, views, age)", "Category chips row"]},
    {"name": "Watch", "route_hint": "/watch/{id}", "must_have": [
        "16:9 video player", "Title + view count + like/dislike", "Channel row + Subscribe button", "Comments section (add + list)", "Related-videos rail"]},
    {"name": "Channel", "route_hint": "/channel/{handle}", "must_have": [
        "Banner + avatar + handle + subscriber count", "Subscribe button", "Grid of this channel's videos"]},
    {"name": "Upload", "route_hint": "/upload", "must_have": [
        "File picker / drag-drop", "Title + description fields", "Visibility select", "Publish button"]},
    {"name": "Creator Studio", "route_hint": "/studio", "must_have": [
        "Left sidebar nav", "My-videos table (views / likes / comments)", "Summary analytics cards"]},
]
(design / "reference_spec.json").write_text(json.dumps({"screens": screens}, indent=2), encoding="utf-8")

# ── 3) approvals → ask-mode + request files (engine approval store) ──
from multi_agent.runtime import approval as A  # noqa: E402
A.write_config(HUBS, mode="ask")
appr_dir = HUBS / "approvals"; appr_dir.mkdir(exist_ok=True)
def appr(aid, agent, atype, tool, summary, args, status, ago, **extra):
    rec = {"id": aid, "action_type": atype, "tool": tool, "agent": agent,
           "summary": summary, "args": args, "status": status, "created_at": now - ago}
    rec.update(extra)
    (appr_dir / f"{aid}.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
appr("appr_m3likegate", "verifier", "gate", "registryhub_register_verification_chain",
     "Create gate (verification chain): Like / unlike flow", {"name": "like_flow"}, "pending", 110)
appr("appr_m4task", "orchestrator", "task", "workhub_create_task",
     "Create task: Subscriptions & home-feed ranking → backend",
     {"title": "Subscriptions & home-feed ranking", "assignee": "backend"}, "pending", 55)
appr("appr_m2done", "orchestrator", "task", "workhub_create_task",
     "Create task: Home feed + Upload page → frontend",
     {"title": "Home feed + Upload page", "assignee": "frontend"}, "approved", 1500,
     feedback="", decided_at=now - 1480, decided_by="admin")

# ── 4) User Console chat → real human↔agent threads (engine EventHub) ──
from app import chat_bridge as cb  # noqa: E402
console = cb.human_console(GEN, default_user_id="admin")
eh = console._eventhub
def convo(agent, human_text, agent_text):
    ev = eh.publish_human_message(text=human_text, target_agents=[agent], from_user="admin")
    eh.publish_agent_reply(thread_id=ev["thread_id"], agent=agent, text=agent_text)
convo("orchestrator", "Give me a status summary.",
      "M1 (auth/channels) and M2 (videos/upload) are released. We're mid-M3 (watch/comments/likes): comments done, likes + related-videos in progress. M4 (subscriptions/feed) and M5 (Creator Studio) are planned.")
convo("frontend", "How's the Watch page coming along?",
      "WatchPage scaffold is in — player + comments wired through services/api.js. Finishing the related-videos rail next; it needs GET /api/videos/{id}/related which backend is still implementing.")
convo("backend", "What's left for milestone 3?",
      "Comments endpoints are implemented and validated. Remaining: POST/DELETE /api/videos/{id}/like and GET /api/videos/{id}/related — the like table is defined, the routes are in progress.")

# keep agents 'active' (180s liveness window) at show time
for p in (ROOT / ".agent_logs").rglob("*.jsonl"):
    os.utime(p, (now, now))

print("seeded: knowledge(5 agents) · references(5 screens) · approvals(ask mode, 2 pending +1 approved) · chat(3 threads)")
