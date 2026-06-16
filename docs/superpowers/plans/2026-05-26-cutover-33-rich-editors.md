# Cutover 33: Rich Editors (Task Lifecycle + Comments + Decisions + Plans + APIHub Schema Updates) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Close most of Cutover 30's deferred list:
- **WorkHub task lifecycle**: claim / complete / fail / cancel (4 ops)
- **WorkHub comments**: add comment to any resource (task / page / PR via workhub.comment)
- **WorkHub decisions**: record_decision on a page
- **WorkHub plans**: create_plan + add_task_to_plan
- **APIHub schema refinements**: update_schema (endpoint), deprecate_endpoint, update_table_schema
- **CodeHub inline comments**: extend the existing review endpoint to accept the `comments` and `inline_comments` arrays that `submit_review` already supports

**Architecture:** All backend additions follow the Cutover 28-30 pattern: `<name>_call(workspaces_root, project_id, body) -> dict` plus a `do_POST` route. All target HubRegistry methods already exist; this cutover just exposes them via HTTP + adds UI forms. CodeHub's `submit_review` is enhanced rather than wrapped — the existing endpoint gains optional fields. No backend refactors; no new abstractions.

**Tech Stack:** Same as prior cutovers — Python stdlib HTTP, React UMD frontend.

---

## Test infrastructure conventions

Tests in `agent/tests/` with sys.path boilerplate. Short imports `from live_monitor_server import ...`. Regressions: `python agent/tests/run_regressions.py`. Pytest: `python -m pytest agent/tests/ -q`. No `Co-Authored-By: Claude` trailer.

---

## Task 1: Pre-flight baseline

- [ ] Regressions: 7 OK
- [ ] Pytest collect: ~1062
- [ ] Create migration log stub at `docs/superpowers/migration-logs/33-rich-editors.md`
- [ ] Stage plan file
- [ ] Commit: `Cutover 33: record pre-flight baseline`

---

## Task 2: WorkHub task lifecycle endpoints (4 ops)

**Backend:** Add 4 helpers + 4 routes to `live_monitor_server.py`:

```python
def workhub_claim_task_call(workspaces_root: Path, project_id: str, task_id: str, body: dict) -> dict:
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err: return err
    agent = (body.get("agent") or "ui_user").strip()
    if not agent: return {"error": "agent required"}
    try:
        return reg.workhub.claim_task(task_id=task_id, agent=agent)
    except Exception as e:
        return {"error": str(e)}


def workhub_complete_task_call(workspaces_root: Path, project_id: str, task_id: str, body: dict) -> dict:
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err: return err
    agent = (body.get("agent") or "ui_user").strip()
    try:
        return reg.workhub.complete_task(
            task_id=task_id, agent=agent,
            result=body.get("result") or {}, evidence=body.get("evidence") or {},
        )
    except Exception as e:
        return {"error": str(e)}


def workhub_fail_task_call(workspaces_root: Path, project_id: str, task_id: str, body: dict) -> dict:
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err: return err
    reason = (body.get("reason") or "").strip()
    if len(reason) < 5:
        return {"error": "reason must be at least 5 characters"}
    agent = (body.get("agent") or "ui_user").strip()
    try:
        return reg.workhub.fail_task(task_id=task_id, agent=agent, reason=reason)
    except Exception as e:
        return {"error": str(e)}


def workhub_cancel_task_call(workspaces_root: Path, project_id: str, task_id: str, body: dict) -> dict:
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err: return err
    agent = (body.get("agent") or "ui_user").strip()
    try:
        return reg.workhub.cancel_task(task_id=task_id, agent=agent)
    except Exception as e:
        return {"error": str(e)}
```

**Routes in `do_POST`** (after existing workhub/tasks routes):

```python
# /api/projects/<id>/workhub/tasks/<task_id>/{claim|complete|fail|cancel}
if "/workhub/tasks/" in parsed.path:
    for action in ("claim", "complete", "fail", "cancel"):
        marker = f"/workhub/tasks/"
        suffix = f"/{action}"
        if parsed.path.startswith("/api/projects/") and parsed.path.endswith(suffix):
            head, tail = parsed.path.split(marker, 1)
            pid = head[len("/api/projects/"):]
            tid = tail[:-len(suffix)]
            handler = {
                "claim": workhub_claim_task_call,
                "complete": workhub_complete_task_call,
                "fail": workhub_fail_task_call,
                "cancel": workhub_cancel_task_call,
            }[action]
            self._write_json(handler(self._workspaces_root, pid, tid, body))
            return
```

**Tests:** Append 4 tests to `agent/tests/test_live_monitor_endpoints.py`:

```python
def test_claim_task(tmp_path):
    _seed_project(tmp_path, "proj_t1", "Tasks")
    from live_monitor_server import workhub_create_task_call, workhub_claim_task_call
    t = workhub_create_task_call(tmp_path, "proj_t1", {"title": "do x", "description": "", "agent": "orchestrator", "domain": "ui", "priority": "P1"})
    result = workhub_claim_task_call(tmp_path, "proj_t1", t["task_id"], {"agent": "backend"})
    assert result.get("status") == "in_progress" or "claimed_by" in result, result


def test_fail_task_requires_reason(tmp_path):
    _seed_project(tmp_path, "proj_t2", "Tasks")
    from live_monitor_server import workhub_create_task_call, workhub_fail_task_call
    t = workhub_create_task_call(tmp_path, "proj_t2", {"title": "x", "description": "", "agent": "o", "domain": "ui", "priority": "P1"})
    result = workhub_fail_task_call(tmp_path, "proj_t2", t["task_id"], {"reason": "", "agent": "o"})
    assert "error" in result


def test_complete_task(tmp_path):
    _seed_project(tmp_path, "proj_t3", "Tasks")
    from live_monitor_server import workhub_create_task_call, workhub_claim_task_call, workhub_complete_task_call
    t = workhub_create_task_call(tmp_path, "proj_t3", {"title": "x", "description": "", "agent": "o", "domain": "ui", "priority": "P1"})
    workhub_claim_task_call(tmp_path, "proj_t3", t["task_id"], {"agent": "backend"})
    result = workhub_complete_task_call(tmp_path, "proj_t3", t["task_id"], {"agent": "backend", "result": {"ok": True}})
    assert "error" not in result, result


def test_cancel_task(tmp_path):
    _seed_project(tmp_path, "proj_t4", "Tasks")
    from live_monitor_server import workhub_create_task_call, workhub_cancel_task_call
    t = workhub_create_task_call(tmp_path, "proj_t4", {"title": "x", "description": "", "agent": "o", "domain": "ui", "priority": "P1"})
    result = workhub_cancel_task_call(tmp_path, "proj_t4", t["task_id"], {"agent": "o"})
    assert "error" not in result, result
```

**Commit:** `Cutover 33: WorkHub task lifecycle endpoints (claim/complete/fail/cancel)`

---

## Task 3: WorkHub comments + decisions + plans

**Backend helpers in `live_monitor_server.py`:**

```python
def workhub_comment_call(workspaces_root: Path, project_id: str, resource_id: str, body: dict) -> dict:
    """Add a comment to any resource (task/page/PR)."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err: return err
    text = (body.get("body") or "").strip()
    if len(text) < 3:
        return {"error": "comment body must be at least 3 characters"}
    agent = (body.get("agent") or "ui_user").strip()
    mentions = body.get("mentions") or []
    try:
        return reg.workhub.comment(resource_id=resource_id, body=text, agent=agent, mentions=mentions)
    except Exception as e:
        return {"error": str(e)}


def workhub_record_decision_call(workspaces_root: Path, project_id: str, page_id: str, body: dict) -> dict:
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err: return err
    title = (body.get("title") or "").strip()
    chosen = (body.get("chosen") or "").strip()
    reason = (body.get("reason") or "").strip()
    options = body.get("options") or []
    if not title or not chosen or not reason or not options:
        return {"error": "title, options, chosen, reason all required"}
    agent = (body.get("agent") or "ui_user").strip()
    try:
        return reg.workhub.record_decision(
            page_id=page_id, title=title, options=options,
            chosen=chosen, reason=reason, agent=agent,
        )
    except Exception as e:
        return {"error": str(e)}


def workhub_create_plan_call(workspaces_root: Path, project_id: str, body: dict) -> dict:
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err: return err
    page_id = body.get("page_id") or ""
    stages = body.get("stages") or []
    tasks = body.get("tasks") or []
    title = body.get("title") or ""
    if not page_id or not stages:
        return {"error": "page_id + stages required"}
    agent = (body.get("agent") or "ui_user").strip()
    try:
        return reg.workhub.create_plan(page_id=page_id, stages=stages, tasks=tasks, agent=agent, title=title)
    except Exception as e:
        return {"error": str(e)}


def workhub_add_task_to_plan_call(workspaces_root: Path, project_id: str, plan_id: str, body: dict) -> dict:
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err: return err
    stage_id = (body.get("stage_id") or "").strip()
    task_dict = body.get("task") or {}
    agent = (body.get("agent") or "ui_user").strip()
    if not stage_id or not task_dict:
        return {"error": "stage_id + task required"}
    try:
        return reg.workhub.add_task_to_plan(plan_id=plan_id, stage_id=stage_id, task_dict=task_dict, agent=agent)
    except Exception as e:
        return {"error": str(e)}
```

**Routes in `do_POST`:**

```python
# /api/projects/<id>/workhub/comments/<resource_id>
if "/workhub/comments/" in parsed.path:
    head, tail = parsed.path.split("/workhub/comments/", 1)
    pid = head[len("/api/projects/"):]
    rid = tail.rstrip("/")
    self._write_json(workhub_comment_call(self._workspaces_root, pid, rid, body))
    return

# /api/projects/<id>/workhub/pages/<page_id>/decisions
if "/workhub/pages/" in parsed.path and parsed.path.endswith("/decisions"):
    head, tail = parsed.path.split("/workhub/pages/", 1)
    pid = head[len("/api/projects/"):]
    page_id = tail[: -len("/decisions")]
    self._write_json(workhub_record_decision_call(self._workspaces_root, pid, page_id, body))
    return

# /api/projects/<id>/workhub/plans
if parsed.path.startswith("/api/projects/") and parsed.path.endswith("/workhub/plans"):
    pid = parsed.path[len("/api/projects/"):-len("/workhub/plans")]
    self._write_json(workhub_create_plan_call(self._workspaces_root, pid, body))
    return

# /api/projects/<id>/workhub/plans/<plan_id>/tasks
if "/workhub/plans/" in parsed.path and parsed.path.endswith("/tasks"):
    head, tail = parsed.path.split("/workhub/plans/", 1)
    pid = head[len("/api/projects/"):]
    plan_id = tail[: -len("/tasks")]
    self._write_json(workhub_add_task_to_plan_call(self._workspaces_root, pid, plan_id, body))
    return
```

**Tests:** Add 4-5 tests for the new helpers (happy + validation error each):

```python
def test_comment_on_task(tmp_path):
    _seed_project(tmp_path, "proj_c1", "Comments")
    from live_monitor_server import workhub_create_task_call, workhub_comment_call
    t = workhub_create_task_call(tmp_path, "proj_c1", {"title": "x", "description": "", "agent": "o", "domain": "ui", "priority": "P1"})
    result = workhub_comment_call(tmp_path, "proj_c1", t["task_id"], {"body": "looks good to me", "agent": "reviewer"})
    assert "error" not in result, result


def test_record_decision_requires_fields(tmp_path):
    _seed_project(tmp_path, "proj_d1", "Decisions")
    from live_monitor_server import workhub_create_page_call, workhub_record_decision_call
    # Stub: directly call workhub to create a page
    from multi_agent.runtime.hub_registry import HubRegistry
    reg = HubRegistry(tmp_path / "proj_d1")
    page = reg.workhub.create_page(title="Design", description="", agent="design", kind="design")
    page_id = page.get("page_id") or page.get("id")
    result = workhub_record_decision_call(tmp_path, "proj_d1", page_id, {"title": "", "options": [], "chosen": "", "reason": ""})
    assert "error" in result
    result2 = workhub_record_decision_call(tmp_path, "proj_d1", page_id, {"title": "DB choice", "options": ["postgres", "mysql"], "chosen": "postgres", "reason": "better json support", "agent": "architect"})
    assert "error" not in result2, result2


def test_create_plan(tmp_path):
    _seed_project(tmp_path, "proj_p1", "Plans")
    from multi_agent.runtime.hub_registry import HubRegistry
    reg = HubRegistry(tmp_path / "proj_p1")
    page = reg.workhub.create_page(title="Backlog", description="", agent="o", kind="plan")
    page_id = page.get("page_id") or page.get("id")
    from live_monitor_server import workhub_create_plan_call
    result = workhub_create_plan_call(tmp_path, "proj_p1", {
        "page_id": page_id, "title": "Sprint 1",
        "stages": [{"id": "s1", "name": "design"}],
        "tasks": [], "agent": "o",
    })
    assert "error" not in result, result
```

**Commit:** `Cutover 33: WorkHub comments + decisions + plans endpoints`

---

## Task 4: APIHub schema refinements (3 ops)

**Backend helpers:**

```python
def apihub_update_endpoint_schema_call(workspaces_root: Path, project_id: str, endpoint_id: str, body: dict) -> dict:
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err: return err
    request = body.get("request")
    response = body.get("response")
    agent = (body.get("agent") or "ui_user").strip()
    try:
        return reg.apihub.update_schema(endpoint_id=endpoint_id, request=request, response=response, agent=agent)
    except Exception as e:
        return {"error": str(e)}


def apihub_deprecate_endpoint_call(workspaces_root: Path, project_id: str, endpoint_id: str, body: dict) -> dict:
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err: return err
    replacement_id = body.get("replacement_id")
    sunset_date = body.get("sunset_date")
    agent = (body.get("agent") or "ui_user").strip()
    try:
        return reg.apihub.deprecate_endpoint(
            endpoint_id=endpoint_id, replacement_id=replacement_id,
            sunset_date=sunset_date, agent=agent,
        )
    except Exception as e:
        return {"error": str(e)}


def apihub_update_table_schema_call(workspaces_root: Path, project_id: str, table_name: str, body: dict) -> dict:
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err: return err
    schema = body.get("schema") or {}
    if not schema:
        return {"error": "schema required"}
    agent = (body.get("agent") or "ui_user").strip()
    try:
        return reg.apihub.update_table_schema(name=table_name, schema=schema, agent=agent)
    except Exception as e:
        return {"error": str(e)}
```

**Routes in `do_POST`:**

```python
# /api/projects/<id>/apihub/endpoints/<endpoint_id>/schema
if "/apihub/endpoints/" in parsed.path and parsed.path.endswith("/schema"):
    head, tail = parsed.path.split("/apihub/endpoints/", 1)
    pid = head[len("/api/projects/"):]
    eid = tail[: -len("/schema")]
    self._write_json(apihub_update_endpoint_schema_call(self._workspaces_root, pid, eid, body))
    return

# /api/projects/<id>/apihub/endpoints/<endpoint_id>/deprecate
if "/apihub/endpoints/" in parsed.path and parsed.path.endswith("/deprecate"):
    head, tail = parsed.path.split("/apihub/endpoints/", 1)
    pid = head[len("/api/projects/"):]
    eid = tail[: -len("/deprecate")]
    self._write_json(apihub_deprecate_endpoint_call(self._workspaces_root, pid, eid, body))
    return

# /api/projects/<id>/apihub/tables/<table_name>/schema
if "/apihub/tables/" in parsed.path and parsed.path.endswith("/schema"):
    head, tail = parsed.path.split("/apihub/tables/", 1)
    pid = head[len("/api/projects/"):]
    name = tail[: -len("/schema")]
    self._write_json(apihub_update_table_schema_call(self._workspaces_root, pid, name, body))
    return
```

**Tests:** 3 tests for the new helpers.

```python
def test_apihub_update_endpoint_schema(tmp_path):
    _seed_project(tmp_path, "proj_a1", "ApiUpdate")
    from multi_agent.runtime.hub_registry import HubRegistry
    reg = HubRegistry(tmp_path / "proj_a1")
    ep = reg.apihub.register_endpoint("GET", "/users", schema={}, provider="backend", agent="backend")
    from live_monitor_server import apihub_update_endpoint_schema_call
    result = apihub_update_endpoint_schema_call(tmp_path, "proj_a1", ep["endpoint_id"], {
        "request": {"query": {}}, "response": {"200": {"users": "array"}}, "agent": "backend",
    })
    assert "error" not in result, result


def test_apihub_deprecate_endpoint(tmp_path):
    _seed_project(tmp_path, "proj_a2", "ApiDeprecate")
    from multi_agent.runtime.hub_registry import HubRegistry
    reg = HubRegistry(tmp_path / "proj_a2")
    ep = reg.apihub.register_endpoint("GET", "/old", schema={}, provider="backend", agent="backend")
    from live_monitor_server import apihub_deprecate_endpoint_call
    result = apihub_deprecate_endpoint_call(tmp_path, "proj_a2", ep["endpoint_id"], {"agent": "backend"})
    assert "error" not in result, result


def test_apihub_update_table_schema(tmp_path):
    _seed_project(tmp_path, "proj_a3", "TableUpdate")
    from multi_agent.runtime.hub_registry import HubRegistry
    reg = HubRegistry(tmp_path / "proj_a3")
    reg.apihub.register_table(name="users", schema={"columns": ["id"]}, provider="database", agent="database")
    from live_monitor_server import apihub_update_table_schema_call
    result = apihub_update_table_schema_call(tmp_path, "proj_a3", "users", {
        "schema": {"columns": ["id", "email"]}, "agent": "database",
    })
    assert "error" not in result, result
```

**Commit:** `Cutover 33: APIHub schema refinements (update endpoint, deprecate, update table)`

---

## Task 5: CodeHub inline-comments support on existing review endpoint

**Modify** `codehub_submit_review_call` in `live_monitor_server.py` to pass through `comments` and `inline_comments` fields from the body:

```python
def codehub_submit_review_call(workspaces_root: Path, project_id: str, pr_id: str, body: dict) -> dict:
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err: return err
    reviewer = (body.get("reviewer") or "ui_user").strip()
    state = (body.get("state") or "comment").strip()
    reason = (body.get("reason") or "").strip()
    inline_comments = body.get("inline_comments") or []
    comments = body.get("comments") or []
    considered_alternatives = body.get("considered_alternatives") or []
    if state in {"request_changes", "approve"} and len(reason) < 20:
        return {"error": "reason must be ≥20 chars for request_changes/approve"}
    # Normalize "comments" list: accept simple [{body}] strings/dicts
    norm_comments: list = []
    for c in comments:
        if isinstance(c, str) and c.strip():
            norm_comments.append({"body": c.strip()})
        elif isinstance(c, dict) and (c.get("body") or "").strip():
            norm_comments.append(c)
    try:
        return reg.codehub.submit_review(
            pr_id=pr_id, reviewer=reviewer, state=state,
            comments=norm_comments,
            inline_comments=inline_comments,
            considered_alternatives=considered_alternatives,
        )
    except Exception as e:
        return {"error": str(e)}
```

**Tests:** Append 2 tests:

```python
def test_submit_review_with_inline_comments(tmp_path):
    _seed_project(tmp_path, "proj_r1", "ReviewInline")
    from multi_agent.runtime.hub_registry import HubRegistry
    reg = HubRegistry(tmp_path / "proj_r1")
    pr = reg.codehub.open_pull_request(branch="feat/x", agent_id="dev", title="t", description="d")
    pr_id = pr.get("pr_id") or pr.get("id")
    from live_monitor_server import codehub_submit_review_call
    result = codehub_submit_review_call(tmp_path, "proj_r1", pr_id, {
        "reviewer": "reviewer1", "state": "comment",
        "comments": ["overall good"],
        "inline_comments": [{"file": "src/x.py", "line": 1, "body": "consider X"}],
    })
    assert "error" not in result, result
    assert len(result.get("inline_comments") or []) == 1


def test_submit_review_approve_requires_inline(tmp_path):
    _seed_project(tmp_path, "proj_r2", "ReviewApprove")
    from multi_agent.runtime.hub_registry import HubRegistry
    reg = HubRegistry(tmp_path / "proj_r2")
    pr = reg.codehub.open_pull_request(branch="feat/y", agent_id="dev", title="t", description="d")
    pr_id = pr.get("pr_id") or pr.get("id")
    from live_monitor_server import codehub_submit_review_call
    result = codehub_submit_review_call(tmp_path, "proj_r2", pr_id, {
        "reviewer": "r", "state": "approve",
        "reason": "this is a sufficiently long reason to pass the gate",
        "inline_comments": [],
    })
    assert "error" in result
```

**Commit:** `Cutover 33: CodeHub review endpoint accepts comments + inline_comments`

---

## Task 6: Frontend — task lifecycle buttons + comment form + decision form + plan form + endpoint edit + inline review form

**Modify `hub_panels.jsx`:**

1. **WorkHub kanban — task lifecycle buttons:**
   - Each task card gets a row of small buttons: `[Claim]`, `[Complete]`, `[Fail]`, `[Cancel]` — only render relevant ones based on `task.status` (e.g. show `Claim` only if `status === "pending"`).
   - Each button POSTs to `/api/projects/<projectId>/workhub/tasks/<task_id>/<action>` then calls `onRefresh()`.
   - `Fail` opens a small prompt for reason (≥5 chars).

2. **Task comments thread:**
   - Add a small `<details>` block inside each task card: "Comments (N)" — when expanded, shows existing comments + a textarea + send button.
   - On send: POST to `/api/projects/<projectId>/workhub/comments/<task_id>`.
   - Comments are read from `hubs.workhub.comments` (existing snapshot field, filter by `resource_id`).

3. **Page decision form:**
   - Each design/visual page row gets a `[+ Decision]` button that opens an inline form with: title, options (comma-sep), chosen, reason.
   - On submit: POST to `/api/projects/<projectId>/workhub/pages/<page_id>/decisions`.

4. **Plan form:**
   - Below the Pages list, add a `[+ Plan]` button + form (page_id selector, title, stages CSV).
   - On submit: POST to `/api/projects/<projectId>/workhub/plans`.

5. **APIHub endpoint edit:**
   - Each endpoint row gets a `[Edit]` button + an inline edit form (request JSON / response JSON / agent field).
   - On save: POST to `/api/projects/<projectId>/apihub/endpoints/<endpoint_id>/schema`.
   - Each endpoint row also gets a `[Deprecate]` button with confirm + optional replacement_id input → POST to `.../deprecate`.

6. **APIHub table edit:**
   - Each table row gets a `[Edit schema]` button + inline JSON textarea.
   - On save: POST to `/api/projects/<projectId>/apihub/tables/<table_name>/schema`.

7. **Inline review form (extend existing CodeHub PR review):**
   - In the existing `SubmitReviewForm` (Cutover 30), add fields for `comments` (textarea, one comment per line) and `inline_comments` (a small repeating block: file / line / body). The plan agent's Cutover 30 marked these as TODO; close them now.
   - The form already POSTs to the same endpoint; just pass the new fields through.

**Smoke test:**

```bash
mkdir -p /tmp/cutover33_ws
/home/haibotong/miniconda3/envs/dt/bin/python -c "
import sys; sys.path.insert(0, 'agent'); sys.path.insert(0, 'agent/env_generator/llm_generator')
from pathlib import Path
from multi_agent.runtime.hub_registry import HubRegistry
reg = HubRegistry(Path('/tmp/cutover33_ws/proj_demo'), project_id='proj_demo', project_name='Demo')
t = reg.workhub.create_task(task_id='task_1', title='do x', description='', agent='o', domain='ui', priority='P1')
reg.apihub.register_endpoint('GET','/users', schema={}, provider='backend', agent='backend')
print(t.get('task_id'))
"
/home/haibotong/miniconda3/envs/dt/bin/python agent/env_generator/llm_generator/live_monitor_server.py --workspaces-root /tmp/cutover33_ws --port 4291 &
SERVER_PID=$!
sleep 1

# Claim task
curl -s -X POST http://127.0.0.1:4291/api/projects/proj_demo/workhub/tasks/task_1/claim \
  -H 'Content-Type: application/json' -d '{"agent":"backend"}' | python -m json.tool | head -10

# Comment on task
curl -s -X POST http://127.0.0.1:4291/api/projects/proj_demo/workhub/comments/task_1 \
  -H 'Content-Type: application/json' -d '{"body":"looks great","agent":"reviewer"}' | python -m json.tool | head -5

# Update endpoint schema
curl -s http://127.0.0.1:4291/api/projects/proj_demo/state | python -c "
import sys,json
d = json.load(sys.stdin)
endpoints = d['hubs']['apihub'].get('endpoints', {})
print('endpoint ids:', list(endpoints.keys()))
"

kill $SERVER_PID 2>/dev/null
```

Expected: claim returns `status=in_progress`; comment returns success; endpoint list shows the registered endpoint.

**Commit:** `Cutover 33: frontend task lifecycle + comments + decisions + plans + endpoint edit + inline review`

---

## Task 7: Migration log + push

- [ ] Write full migration log with commit SHAs, test counts (~1062 → ~1082, +20)
- [ ] Targeted sweep: `pytest agent/tests/test_live_monitor_endpoints.py -q` → ~80 passed
- [ ] Regressions: 7 OK
- [ ] Commit migration log + push branch + ff-merge into parent

---

## Known limits

- Task lifecycle is invokable by UI; no per-action permission gating (any "ui_user" can claim+complete).
- Comments display assumes you read them from `hubs.workhub.comments` snapshot — UI does no separate fetch.
- Plan editor is minimal (stages CSV); future cutovers may add a drag-reorder UI.
- Inline-review form lets you specify file/line/body; there's no diff viewer to click-and-anchor yet.
- APIHub `update_schema` doesn't currently re-trigger breaking-change detection in the UI.
- WorkHub page-block editor (Notion-style rich text) is still deferred.
