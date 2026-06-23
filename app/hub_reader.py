"""Read a generated environment's collaboration-hub state from disk.

env-gen persists every hub as a JSON store under ``<env>/shared/hubs/`` — that IS
the runtime's database. This module maps those real stores into the state shape
the Env Forge UI consumes. Best-effort: every section is independently guarded so
a missing/partial store yields an empty section, never a crash. NO hardcoded data.
"""
from __future__ import annotations

import ast
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CORE_AGENTS = [
    # role MUST match the agent's display name (the .agent_logs/<role> Agent/ dir):
    # backend/frontend were renamed Lead→Engineer, so these must track that.
    ("orchestrator", "Orchestrator"), ("backend", "Backend Engineer"),
    ("frontend", "Frontend Engineer"), ("verifier", "Verifier"),
    ("debugger", "Debugger"), ("knowledge", "Knowledge"),
]


def _load(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _records(d: dict) -> list[dict]:
    return [v for k, v in (d or {}).items() if k != "_meta" and isinstance(v, dict)]


def _iso(ts: Any) -> str:
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
        return str(ts or "")
    except Exception:
        return ""


def _hubs(gen: Path) -> Path:
    return gen / "shared" / "hubs"


def _hub_mtime(h: Path) -> float:
    """Most-recent write across the hub stores — a liveness signal (the runtime
    rewrites these JSON stores as agents work). 0.0 if none/unreadable."""
    try:
        return max((p.stat().st_mtime for p in h.glob("*.json")), default=0.0)
    except OSError:
        return 0.0


# ── per-section readers ─────────────────────────────────────────────────────

def _endpoints(h: Path) -> list[dict]:
    out = []
    for v in _records(_load(h / "registryhub_endpoints.json")):
        if v.get("kind") in ("auth", "oauth", "infra"):
            continue  # business endpoints only
        sch = v.get("schema") or {}
        out.append({"id": v.get("id", ""), "method": (v.get("method") or "").upper(),
                    "path": v.get("path", ""), "status": v.get("status", "defined"),
                    "provider": v.get("provider", ""),
                    "auth_required": bool((v.get("metadata") or {}).get("auth_required", True)),
                    "request_schema": sch.get("request") or {},
                    "response_schema": sch.get("response") or {}})
    return out


def _tables(h: Path) -> list[dict]:
    out = []
    for v in _records(_load(h / "registryhub_tables.json")):
        cols = ((v.get("schema") or {}).get("columns")) or []
        out.append({"id": v.get("id", ""), "name": v.get("name", ""),
                    "status": v.get("status", "defined"), "columns": len(cols),
                    "columns_detail": [{"name": c.get("name", ""), "type": c.get("type", ""),
                                        "primary_key": bool(c.get("primary_key"))}
                                       for c in cols if isinstance(c, dict)]})
    return out


def _wired_routes(gen: Path) -> str:
    for rel in ("app/frontend/src/App.jsx", "app/frontend/src/App.tsx"):
        f = gen / rel
        if f.is_file():
            try:
                return f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                return ""
    return ""


def _ui_pages(gen: Path, h: Path) -> list[dict]:
    app_src = _wired_routes(gen)
    # The registry frequently omits route/component (the lane registered names only);
    # backfill the route from the compiled reference spec so the UI isn't blank.
    ref_routes = {s.get("name"): s.get("route_hint", "")
                  for s in (_load(gen / "design" / "reference_spec.json").get("screens") or [])
                  if isinstance(s, dict) and s.get("name")}
    out = []
    for v in _records(_load(h / "registryhub_ui_pages.json")):
        name = v.get("name", "")
        # NB: v["path"] is a FILE path (an audit artifact), NOT a URL route — never
        # surface it as the route. Backfill the real route from the reference spec.
        route = v.get("route") or ref_routes.get(name, "")
        component = v.get("component", "")
        # Drop audit-detected file entries that aren't real pages — main.jsx (infra),
        # a component's source file, or a page's bare .jsx — they carry neither a
        # route nor a declared component. A real declared page always has one.
        if not route and not component:
            continue
        wired = bool(route) and (f'path="{route}"' in app_src or f"path='{route}'" in app_src
                                 or (route == "/" and "index" in app_src))
        out.append({"id": v.get("id", name), "name": name,
                    "route": route, "component": component,
                    "status": v.get("status", "defined"),
                    "apis": len(v.get("apis_used") or []), "wired": wired,
                    "components": v.get("components") or []})
    return out


def _ui_components(gen: Path, h: Path) -> list[dict]:
    # The lane rarely fills a component's own ``used_by`` — but pages DO declare the
    # components they compose, so derive the reverse mapping (component -> #pages).
    usage: dict[str, int] = {}
    for p in _records(_load(h / "registryhub_ui_pages.json")):
        for c in (p.get("components") or []):
            usage[str(c)] = usage.get(str(c), 0) + 1
    out = []
    for v in _records(_load(h / "registryhub_ui_components.json")):
        comp = v.get("component") or v.get("name", "")
        cid = v.get("id", "")
        ub = v.get("used_by")
        used = len(ub) if isinstance(ub, list) else (usage.get(comp) or usage.get(cid) or usage.get(v.get("name", "")) or 0)
        out.append({"id": cid, "name": comp, "status": v.get("status", "defined"), "used_by": int(used)})
    if out:
        return out
    # Registry empty — surface the components that actually exist in the built frontend.
    comps_dir = gen / "app" / "frontend" / "src" / "components"
    if comps_dir.is_dir():
        for f in sorted(comps_dir.rglob("*.jsx")):
            out.append({"id": f.stem, "name": f.stem, "status": "implemented", "used_by": int(usage.get(f.stem, 0))})
    return out


def _contract_tests(h: Path) -> list[dict]:
    latest: dict[str, dict] = {}
    for v in _records(_load(h / "registryhub_contract_tests.json")):
        eid = v.get("endpoint_id", "")
        latest[eid] = v  # store order ≈ chronological; keep last seen
    out = []
    for eid, v in latest.items():
        res = v.get("result") or {}
        ok = res.get("passed") is True or res.get("verdict") == "pass"
        out.append({"endpoint": eid, "status": "pass" if ok else "fail",
                    "code": res.get("status_code") or 0})
    return out


def _chains(h: Path) -> list[dict]:
    out = []
    for k, v in (_load(h / "registryhub_verification_chains.json")).items():
        if k == "_meta" or not isinstance(v, dict):
            continue
        steps = v.get("steps") or []
        lr = v.get("last_result")
        last_result = _truncate_jsonable(lr) if isinstance(lr, (dict, list)) else (str(lr)[:600] if lr else None)
        out.append({"name": v.get("name", k), "status": v.get("status", "unknown"),
                    "steps": len(steps), "description": v.get("description", ""),
                    "last_result": last_result,
                    "step_detail": [{"method": str(s.get("method", "")), "path": str(s.get("path", "")),
                                     "expect": s.get("expect")}
                                    for s in steps if isinstance(s, dict)][:40]})
    return out


def _tasks(h: Path) -> list[dict]:
    out = []
    for v in _records(_load(h / "workhub_tasks.json")):
        res = v.get("result")
        out.append({"id": v.get("id", ""), "title": v.get("title", ""),
                    "assignee": v.get("assignee", ""), "status": v.get("status", "pending"),
                    "description": v.get("description", ""),
                    "claimed_by": v.get("claimed_by", ""),
                    "result": res if isinstance(res, str) else (json.dumps(res)[:600] if res else "")})
    return out[-100:]


def _decisions(h: Path) -> list[dict]:
    return [{"id": v.get("id", ""), "title": v.get("title", v.get("decision", "")),
             "author": v.get("author", v.get("_updated_by", "")),
             "created_at": _iso(v.get("created_at"))}
            for v in _records(_load(h / "workhub_decisions.json"))]


def _commits(h: Path) -> list[dict]:
    out = [{"id": v.get("id", ""), "branch": v.get("branch", ""),
            "author": v.get("author", ""), "summary": v.get("diff_summary", ""),
            "files": [str(f) for f in (v.get("files") or [])],
            "created_at": _iso(v.get("created_at"))}
           for v in _records(_load(h / "codehub_commits.json"))]
    return sorted(out, key=lambda c: c["created_at"], reverse=True)[:50]


def _prs(h: Path) -> list[dict]:
    return [{"id": v.get("id", v.get("number", "")), "title": v.get("title", ""),
             "author": v.get("author", ""), "branch": v.get("source_branch", v.get("branch", "")),
             "status": v.get("status", v.get("state", "open"))}
            for v in _records(_load(h / "codehub_pull_requests.json"))]


def _runs_raw(h: Path) -> list[dict]:
    return _records(_load(h / "runhub_runs.json"))


def _probes(h: Path) -> list[dict]:
    runs = _runs_raw(h)
    if not runs:
        return []
    last = sorted(runs, key=lambda r: r.get("started_at") or 0)[-1]
    out = []
    for p in (last.get("probes") or []):
        if not isinstance(p, dict):
            continue
        code = p.get("status") or p.get("status_code") or 0
        ok = p.get("ok")
        if ok is None:
            ok = isinstance(code, int) and 200 <= code < 400
        out.append({"endpoint": p.get("endpoint") or f"{p.get('method','')} {p.get('path','')}".strip(),
                    "ok": bool(ok), "code": code})
    return out


def _events(h: Path) -> list[dict]:
    evs = _records(_load(h / "eventhub_events.json"))
    evs = sorted(evs, key=lambda e: e.get("created_at") or 0, reverse=True)[:60]
    return [{"id": e.get("id", ""), "source_hub": e.get("source_hub", ""),
             "event_type": e.get("event_type", ""), "priority": e.get("priority", "normal"),
             "payload": e.get("payload") or {}, "created_at": _iso(e.get("created_at"))} for e in evs]


# Approx USD per 1M tokens (input, output) — for an ESTIMATED cost when the runtime
# didn't persist system_token_usage.json and we aggregate from the generation log.
_MODEL_RATES = {
    "gemini-3.1-pro": (1.25, 5.0), "gemini-2.5-pro": (1.25, 5.0), "gemini": (0.5, 1.5),
    "gpt-5": (1.25, 10.0), "gpt": (1.0, 4.0),
    "claude-opus": (15.0, 75.0), "claude-sonnet": (3.0, 15.0), "claude": (3.0, 15.0),
}


def _token_rate(model: str) -> tuple[float, float]:
    m = (model or "").lower()
    for key, rate in _MODEL_RATES.items():
        if key in m:
            return rate
    return (1.0, 3.0)


def _metrics_from_log(gen: Path) -> dict | None:
    """Fallback when system_token_usage.json is absent: aggregate the per-call token
    usage the runtime logs (``[LLM Response] prompt_tokens=.. completion_tokens=..``)
    from the env's generation log, estimating cost via _MODEL_RATES. Counts are
    exact; cost is an estimate."""
    import re
    logs = sorted((gen / "logs").glob("generation_*.log")) if (gen / "logs").is_dir() else []
    if not logs:
        return None
    try:
        text = logs[-1].read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    ins = sum(int(x) for x in re.findall(r"prompt_tokens=(\d+)", text))
    outs = sum(int(x) for x in re.findall(r"completion_tokens=(\d+)", text))
    if ins == 0 and outs == 0:
        return None
    mm = re.search(r"model=([A-Za-z0-9.\-]+-[A-Za-z0-9.\-]+)", text)  # skip model=jwt etc.
    model = mm.group(1) if mm else "?"
    ri, ro = _token_rate(model)
    cost = round(ins / 1e6 * ri + outs / 1e6 * ro, 2)
    return {"total_input": ins, "total_output": outs, "total_cost": cost,
            "by_model": [{"model": model, "input": ins, "output": outs, "cost": cost}]}


def _metrics(h: Path) -> dict:
    data = _load(h / "system_token_usage.json")
    total_in = total_out = 0
    cost = 0.0
    by_model: dict[str, dict] = {}
    for v in data.values():
        if not isinstance(v, dict):
            continue
        total_in += int(v.get("total_input", 0) or 0)
        total_out += int(v.get("total_output", 0) or 0)
        cost += float(v.get("total_cost", 0.0) or 0.0)
        for model, mu in (v.get("by_model") or {}).items():
            slot = by_model.setdefault(model, {"model": model, "input": 0, "output": 0, "cost": 0.0})
            slot["input"] += int(mu.get("input", 0) or 0)
            slot["output"] += int(mu.get("output", 0) or 0)
            slot["cost"] += float(mu.get("cost", 0.0) or 0.0)
    if total_in == 0 and total_out == 0:
        # the runtime didn't persist the usage store — aggregate from the log instead
        fb = _metrics_from_log(h.parent.parent)  # h = <gen>/shared/hubs
        if fb:
            return fb
    return {"total_input": total_in, "total_output": total_out,
            "total_cost": round(cost, 2), "by_model": list(by_model.values())}


def _truncate_jsonable(v, maxlen: int = 300):
    """Bound a literal-eval'd value so the (3s-polled) payload stays small."""
    if isinstance(v, str):
        return v if len(v) <= maxlen else v[:maxlen] + "…"
    if isinstance(v, dict):
        return {str(k): _truncate_jsonable(x, maxlen) for k, x in list(v.items())[:40]}
    if isinstance(v, (list, tuple)):
        return [_truncate_jsonable(x, maxlen) for x in list(v)[:40]]
    if isinstance(v, (int, float, bool)) or v is None:
        return v
    return str(v)[:maxlen]


def _parse_action_entry(e: dict) -> dict:
    """Parse one .agent_logs jsonl line into a structured action for the UI:
    ``{at, type, tool, args, args_obj, result, content}``. ``content`` is usually
    ``toolName({...})``; ``metadata`` carries the tool result (a dict or a
    Python-repr string). ``args_obj`` is the parsed argument object so the UI can
    render it as JSON instead of a raw string."""
    content = str(e.get("content") or "")
    m = re.match(r"\s*([A-Za-z_]\w*)\s*\((.*)\)\s*$", content, re.S)
    tool = m.group(1) if m else ""
    args = m.group(2).strip() if m else ""
    args_obj = None
    if args:
        try:
            parsed_args = ast.literal_eval(args)  # the call is toolName({...}) — a literal
            if isinstance(parsed_args, (dict, list)):
                args_obj = _truncate_jsonable(parsed_args)
        except Exception:
            args_obj = None
    md = e.get("metadata")
    result = ""
    ok = None  # authoritative tool-success flag when the log carries it (None = unknown → UI falls back)
    if isinstance(md, dict):
        result = str(md.get("result", md))
        if "ok" in md:
            ok = bool(md.get("ok"))
    elif isinstance(md, str) and md.strip():
        s = md.strip()
        if s.startswith("{"):
            try:
                parsed = ast.literal_eval(s)
                result = str(parsed.get("result", s)) if isinstance(parsed, dict) else s
            except Exception:
                result = s
        else:
            result = s
    return {"at": str(e.get("timestamp", "")), "type": str(e.get("event_type", "")),
            "tool": tool, "args": args[:400], "args_obj": args_obj,
            "result": result[:400], "content": content[:400], "ok": ok}


def _agent_log_activity(gen: Path, role: str):
    """(last_action, mtime, recent_actions[]) from ``.agent_logs/<role> Agent/*.jsonl``
    — the reliable signal for whether an agent is actually working + its action
    history. Eventhub events are hub-scoped and rarely attributed per-agent, so they
    under-report activity (every agent looked idle)."""
    d = gen / ".agent_logs" / f"{role} Agent"
    if not d.is_dir():
        return None
    files = list(d.glob("*.jsonl"))
    if not files:
        return None
    newest = max(files, key=lambda f: f.stat().st_mtime)
    try:
        lines = [ln for ln in newest.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
    except OSError:
        return None
    acts = []
    for ln in lines[-25:]:
        try:
            e = json.loads(ln)
        except Exception:
            continue
        acts.append(_parse_action_entry(e))
    if not acts:
        return None
    last = acts[-1]
    # Overview shows this as a compact label — keep it to the clean tool/action
    # name only (the full args/result live in the agent drawer's action history).
    label = (last["tool"] or last["type"] or "—")[:80]
    return (label, newest.stat().st_mtime, list(reversed(acts)))


def _agents(h: Path) -> list[dict]:
    """Per-agent status + action history from the AUTHORITATIVE source: each agent's
    own ``.agent_logs/<role> Agent/*.jsonl`` step log. eventhub is deliberately NOT
    used — it is a hub-scoped coordination log (records which HUB emitted an event,
    not which agent), so it cannot attribute activity to an agent. An agent with no
    log is reported idle with no history (honest 'no data', never a guess).

    ``active`` = this lane emitted to its OWN log within 5min — generous enough to span
    a long step (LLM call, docker build, validation) so a genuinely-working lane never
    flickers to ``idle``, yet PER-LANE so a STUCK lane reads ``idle`` even while the
    overall run keeps ticking. (A global run-liveness override briefly hid a frontend
    lane that had been stuck 26min as ``active`` — 2026-06-23; reverted.) Run-liveness
    is conveyed by the orchestrator's OWN status + the env ``generating`` badge, not by
    faking every lane active. ``last_active_at`` shows how long since the lane acted, so
    a stall is visible at a glance."""
    gen = h.parent.parent  # h == <gen>/shared/hubs
    now = datetime.now(timezone.utc).timestamp()
    out = []
    for aid, role in CORE_AGENTS:
        act = _agent_log_activity(gen, role)
        if act:
            label, mtime, recent = act
            out.append({"id": aid, "role": role,
                        "status": "active" if (now - mtime) < 300 else "idle",
                        "last_action": label or "—", "last_active_at": _iso(mtime),
                        "recent_actions": recent})
        else:
            out.append({"id": aid, "role": role, "status": "idle",
                        "last_action": "—", "last_active_at": "", "recent_actions": []})
    return out


def _doc_body(v: dict) -> str:
    """Readable body for a coordination document (kickoff / meeting / retro /
    project). The content lives in ``metadata`` (agenda / requirements /
    decisions / produced_artifacts), not a top-level ``description`` — so a bare
    read showed "No content recorded". Compose the real content here.
    Domain-agnostic: only reads generic metadata keys, gracefully skips absent ones."""
    desc = str(v.get("description") or "").strip()
    if desc:
        return desc[:4000]
    md = v.get("metadata") or {}
    if not isinstance(md, dict):
        return ""
    parts: list[str] = []
    agenda = md.get("agenda")
    if agenda:
        parts.append(str(agenda).strip())
    reqs = md.get("requirements")
    if reqs:
        body = "\n".join(f"- {str(r).strip()}" for r in reqs[:30]) if isinstance(reqs, list) else str(reqs).strip()
        parts.append("Requirements:\n" + body)
    decisions = md.get("decisions")
    if isinstance(decisions, list) and decisions:
        lines = []
        for d in decisions[:30]:
            if not isinstance(d, dict):
                continue
            label = d.get("section") or d.get("kind") or "decision"
            body = d.get("decision") if isinstance(d.get("decision"), dict) else d.get("content")
            summ = ""
            if isinstance(body, dict):
                summ = body.get("summary") or body.get("title") or body.get("chosen") or body.get("rationale") or ""
            elif isinstance(body, str):
                summ = body
            lines.append(f"- {label}" + (f": {str(summ)[:200]}" if summ else ""))
        if lines:
            parts.append(f"Decisions ({len(decisions)}):\n" + "\n".join(lines))
    artifacts = md.get("produced_artifacts")
    if artifacts:
        arts = artifacts if isinstance(artifacts, list) else [artifacts]
        parts.append("Produced artifacts: " + ", ".join(str(a) for a in arts))
    return "\n\n".join(parts)[:4000]


def _pages(h: Path) -> list[dict]:
    # WorkHub's document model calls everything a "page", but ui_page / ui_component
    # docs belong in RegistryHub (shown there) — exclude them so this is only the
    # coordination documents (project / kickoff / retro / meeting notes).
    return [{"id": v.get("id", ""), "title": v.get("title", ""), "kind": v.get("kind", ""),
             "status": v.get("status", ""), "description": _doc_body(v),
             "attendees": [str(a) for a in (v.get("attendees") or [])]}
            for v in _records(_load(h / "workhub_pages.json"))
            if v.get("kind") not in ("ui_page", "ui_component")]


def _milestones(h: Path) -> list[dict]:
    """Port of the monitor's build_milestones: roadmap from milestone_plan
    decisions + per-milestone 'M<n> kickoff' pages + cut releases."""
    import re as _re
    pages = _load(h / "workhub_pages.json")
    plan: list = []
    kickoffs: dict[int, dict] = {}
    for pid, pg in pages.items():
        if pid == "_meta" or not isinstance(pg, dict):
            continue
        m = _re.match(r"M(\d+) kickoff", str(pg.get("title") or ""), _re.IGNORECASE)
        if m:
            kickoffs[int(m.group(1))] = {"status": pg.get("status")}
        for d in ((pg.get("metadata") or {}).get("decisions") or []):
            body = d.get("decision") if isinstance(d.get("decision"), dict) else d
            if not isinstance(body, dict):
                continue
            if str(body.get("kind")) == "milestone_plan" or str(body.get("section")) == "roadmap":
                content = body.get("content") if isinstance(body.get("content"), dict) else body
                cand = content.get("milestones") if isinstance(content, dict) else None
                if isinstance(cand, list) and cand:
                    plan = cand
    released = {str(r.get("tag", tag)): True for tag, r in _load(h / "codehub_releases.json").items()
               if tag != "_meta" and isinstance(r, dict)}
    out = []
    n = max(len(plan), max(kickoffs) if kickoffs else 0)
    for i in range(1, n + 1):
        entry = plan[i - 1] if i <= len(plan) and isinstance(plan[i - 1], dict) else {}
        version = str(entry.get("version") or f"1.{i - 1}.0")
        name = str(entry.get("name") or entry.get("title") or f"M{i}")
        status = "released" if version in released else ("active" if i in kickoffs else "planned")
        out.append({"version": version, "title": name, "status": status})
    return out


def _progress(h: Path, tasks: list[dict]) -> dict:
    done = sum(1 for t in tasks if t.get("status") == "completed")
    pct = round(100 * done / len(tasks)) if tasks else 0
    milestones = _milestones(h)
    current = next((m["title"] for m in milestones if m["status"] == "active"), "")
    return {"percent": pct, "current": current, "milestones": milestones}


def _gates(h: Path, ui_pages: list[dict], chains: list[dict]) -> list[dict]:
    gates = []
    runs = _runs_raw(h)
    if runs:
        last = sorted(runs, key=lambda r: r.get("started_at") or 0)[-1]
        fc = last.get("fail_count")
        gates.append({"name": "api_smoke", "status": "pass" if fc == 0 else "fail",
                      "detail": f"{len(last.get('probes') or [])} probes, {fc} failed"})
    unwired = [p for p in ui_pages if not p["wired"]]
    if ui_pages:
        gates.append({"name": "ui_page_unwired",
                      "status": "fail" if unwired else "pass",
                      "detail": f"{len(unwired)} of {len(ui_pages)} declared pages not wired in App.jsx"})
    failing = [c for c in chains if "fail" in str(c["status"]).lower()]
    if chains:
        gates.append({"name": "business_chain", "status": "fail" if failing else "pass",
                      "detail": f"{len(failing)} of {len(chains)} chains failing"})
    # user-defined custom gates (managed from the UI; design/custom_gates.json)
    cg_path = h.parent.parent / "design" / "custom_gates.json"
    try:
        custom = json.loads(cg_path.read_text(encoding="utf-8")) if cg_path.is_file() else []
    except Exception:
        custom = []
    for g in custom if isinstance(custom, list) else []:
        if isinstance(g, dict) and g.get("name"):
            gates.append({"name": g["name"], "status": g.get("status", "manual"),
                          "detail": g.get("detail", ""), "custom": True})
    return gates


# ── public API ──────────────────────────────────────────────────────────────

def read_state(gen_dir: str | Path) -> dict:
    gen = Path(gen_dir)
    h = _hubs(gen)
    ui_pages = _ui_pages(gen, h)
    chains = _chains(h)
    tasks = _tasks(h)
    return {
        "preview_url": None,
        "progress": _progress(h, tasks),
        "agents": _agents(h),
        "metrics": _metrics(h),
        "endpoints": _endpoints(h),
        "tables": _tables(h),
        "ui_pages": ui_pages,
        "ui_components": _ui_components(gen, h),
        "contract_tests": _contract_tests(h),
        "chains": chains,
        "tasks": tasks,
        "pages": _pages(h),
        "decisions": _decisions(h),
        "commits": _commits(h),
        "prs": _prs(h),
        "probes": _probes(h),
        "events": _events(h),
        "references": _references(gen),
        "gates": _gates(h, ui_pages, chains),
        "knowledge": _knowledge(gen),
        "skills": _skills(gen),
        "chat": [],
    }


def _skill_desc(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":  # YAML frontmatter
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if line.lower().startswith("description:"):
                return line.split(":", 1)[1].strip().strip('"').strip("'")[:240]
    for line in lines:  # first prose line
        s = line.strip()
        if s and not s.startswith("#") and s != "---":
            return s[:240]
    for line in lines:  # else first heading
        s = line.strip().lstrip("#").strip()
        if s:
            return s[:240]
    return ""


def _skills(gen: Path) -> list[dict]:
    out = []
    d = gen / ".agents" / "skills"
    if d.is_dir():
        for sk in sorted(d.iterdir()):
            if not sk.is_dir():
                continue
            md = sk / "SKILL.md"
            desc = ""
            body = ""
            if md.is_file():
                try:
                    txt = md.read_text(encoding="utf-8", errors="ignore")
                    desc = _skill_desc(txt)
                    body = txt[:12000]  # full SKILL.md content (capped) for the detail view
                except Exception:
                    pass
            out.append({"name": sk.name, "description": desc, "body": body})
    return out


def _knowledge(gen: Path) -> list[dict]:
    out = []
    d = gen / ".memory"
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.knowledge.jsonl")):
        agent = f.name.replace(".knowledge.jsonl", "")
        try:
            for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                out.append({"agent": agent, "content": e.get("content", ""),
                            "category": e.get("category", ""),
                            "importance": e.get("importance"),
                            "phase": e.get("phase", ""),
                            "timestamp": _iso(e.get("timestamp"))})
        except Exception:
            pass
    return out


def _references(gen: Path) -> list[dict]:
    from urllib.parse import quote
    env_id = gen.name
    out: list[dict] = []
    seen: set[str] = set()
    img_exts = (".png", ".jpg", ".jpeg", ".webp", ".gif")
    doc_exts = (".md", ".txt", ".html", ".pdf")
    # 1) actual reference FILES staged into the env (screenshots + docs) — served
    #    via the backend's reference endpoint so the UI can show them.
    for sub in ("design/references", "design/reference_images"):
        d = gen / sub
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if not f.is_file() or f.name in seen:
                    continue
                ext = f.suffix.lower()
                if ext in img_exts or ext in doc_exts:
                    seen.add(f.name)
                    out.append({"name": f.name, "screen": f.stem,
                                "kind": "image" if ext in img_exts else "doc",
                                "url": f"/api/env-forge/environments/{env_id}/references/{quote(f.name)}",
                                "route": "", "must_have": []})
    # 2) the compiled reference-spec screens (the must-have checklist) for any
    #    screen not already covered by a staged file.
    spec = _load(gen / "design" / "reference_spec.json")
    for s in (spec.get("screens") or []):
        if isinstance(s, dict) and s.get("name") and s["name"] not in seen:
            seen.add(s["name"])
            out.append({"name": s["name"], "screen": s["name"], "kind": "screen",
                        "route": s.get("route_hint", ""),
                        "must_have": s.get("must_have") or [], "url": ""})
    return out


def env_summary(gen_dir: str | Path) -> dict:
    """Derive the EnvProject summary fields from disk (counts, delivered, status)."""
    gen = Path(gen_dir)
    h = _hubs(gen)
    endpoints = _endpoints(h)
    ui_pages = _ui_pages(gen, h)
    runs = _runs_raw(h)
    delivered = len(_records(_load(h / "codehub_releases.json"))) > 0
    # Liveness: the runtime rewrites the hub stores continuously while it works, so
    # a recent write means the env is still being generated — a failed VALIDATION
    # pass mid-run is normal and must NOT be reported as the env having "failed".
    active = (time.time() - _hub_mtime(h)) < 900  # touched within the last 15 min
    status = "generating"
    if delivered:
        status = "delivered"
    elif active:
        status = "generating"
    elif runs:
        last = sorted(runs, key=lambda r: r.get("started_at") or 0)[-1]
        st = str(last.get("status", "")).lower()
        if st in ("aborted", "failed", "error"):
            status = "failed"      # quiet + last run failed → genuinely dead
        elif st in ("completed", "finished", "ok", "passed"):
            status = "completed"
        else:
            status = "completed" if endpoints else "generating"
    return {"pages": len(ui_pages), "endpoints": len(endpoints),
            "visual_score": None, "delivered": delivered, "status": status,
            "run_count": len(runs)}


def list_runs(gen_dir: str | Path, env_id: str) -> list[dict]:
    h = _hubs(Path(gen_dir))
    out = []
    for r in _runs_raw(h):
        started = r.get("started_at") or 0
        finished = r.get("finished_at") or started
        st = str(r.get("status", "")).lower()
        status = {"aborted": "failed", "failed": "failed", "error": "failed",
                  "completed": "completed", "finished": "completed"}.get(st, "generating")
        probes = [{"endpoint": p.get("endpoint") or f"{p.get('method','')} {p.get('path','')}".strip(),
                   "ok": bool(p.get("ok") if p.get("ok") is not None else (isinstance(p.get("status"), int) and 200 <= p.get("status") < 400)),
                   "code": p.get("status") or p.get("status_code") or 0}
                  for p in (r.get("probes") or []) if isinstance(p, dict)]
        out.append({"run_id": r.get("id", ""), "env_id": env_id, "status": status,
                    "milestone": r.get("milestone"), "coordination_ticks": int(r.get("coordination_ticks", 0) or 0),
                    "wallclock_sec": float(finished) - float(started) if started else 0.0,
                    "fail_count": r.get("fail_count"), "healthcheck": r.get("healthcheck"),
                    "probes": probes, "created_at": _iso(started)})
    return sorted(out, key=lambda x: x["created_at"], reverse=True)
