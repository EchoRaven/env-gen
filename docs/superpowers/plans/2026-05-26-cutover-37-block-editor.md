# Cutover 37: WorkHub Block Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Close Cutover 33's deferred item — UI surface for the page block model. Add 3 endpoints (append, update, insert-after) over the existing WorkHub block methods. Frontend: expandable block list per page with inline edit + add-block buttons.

**Architecture:**
- Backend: 3 endpoints. All thin wrappers over `workhub.append_block`, `workhub.update_block`, `workhub.insert_block_after`. Match Cutover 33's `*_call(workspaces_root, project_id, ...)` helper pattern.
- Frontend: extend `WorkHubPanel` in `hub_panels.jsx`. Each Page row gets an "Expand" toggle that reveals a `<BlockList>` showing all blocks for that page (sorted by `ord`). Each block: inline `<textarea>` for content + Save button (PATCH on blur or explicit save). "+ Add block" buttons between blocks (with type dropdown: text/code/heading/quote). No delete (out of scope; WorkHub doesn't expose it).
- Data: blocks are already in `state.hubs.workhub.blocks` (server snapshot includes them). Filter by `page_id` in JSX.

**Tech Stack:** stdlib + React. No new deps.

---

## Test infrastructure conventions

Tests in `agent/tests/` with sys.path boilerplate. Regressions: `python agent/tests/run_regressions.py`. NO `Co-Authored-By: Claude` trailer.

---

## File Structure

**Create:**
- `docs/superpowers/migration-logs/37-block-editor.md`

**Modify:**
- `agent/env_generator/llm_generator/live_monitor_server.py` (3 helpers + 3 routes)
- `agent/tests/test_live_monitor_endpoints.py` (append block-editor tests)
- `agent/env_generator/llm_generator/live_monitor/src/hub_panels.jsx` (block list + add/edit forms)
- `agent/env_generator/llm_generator/live_monitor/styles/hubs.css` (block editor styles)

---

## Task 1: Pre-flight baseline

- [ ] Regressions → 7 OK
- [ ] Pytest collect → ~1112
- [ ] Migration log stub
- [ ] Stage plan
- [ ] Commit: `Cutover 37: record pre-flight baseline`

---

## Task 2: Backend — 3 block endpoints

**Files:**
- Modify: `live_monitor_server.py`
- Modify: `agent/tests/test_live_monitor_endpoints.py` (APPEND)

### TDD Step 1: append failing tests

Append to `agent/tests/test_live_monitor_endpoints.py`:

```python
class TestBlockEditorEndpoints(unittest.TestCase):
    def setUp(self):
        from live_monitor_server import _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        from live_monitor_server import create_project_call, workhub_create_page_call
        result = create_project_call(self.root, {"name": "blocks-test"})
        self.project_id = result["id"]
        page_result = workhub_create_page_call(self.root, self.project_id, {
            "title": "Design Page",
            "agent": "test",
        })
        self.assertNotIn("error", page_result, page_result)
        self.page_id = page_result.get("id")

    def tearDown(self):
        from live_monitor_server import _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp.cleanup()

    def test_append_block_creates_block(self):
        from live_monitor_server import workhub_append_block_call, _resolve_hubs
        result = workhub_append_block_call(self.root, self.project_id, self.page_id, {
            "type": "text", "content": "Hello world", "agent": "alice",
        })
        self.assertNotIn("error", result, result)
        self.assertIn("id", result)
        reg, _ = _resolve_hubs(self.root, self.project_id)
        blocks = reg.workhub.snapshot().get("blocks", {})
        self.assertEqual(len(blocks), 1)
        b = next(iter(blocks.values()))
        self.assertEqual(b["content"], "Hello world")
        self.assertEqual(b["type"], "text")
        self.assertEqual(b["page_id"], self.page_id)

    def test_append_block_unknown_page_returns_error(self):
        from live_monitor_server import workhub_append_block_call
        result = workhub_append_block_call(self.root, self.project_id, "page_nope", {
            "type": "text", "content": "x", "agent": "alice",
        })
        self.assertIn("error", result)

    def test_update_block_replaces_content(self):
        from live_monitor_server import workhub_append_block_call, workhub_update_block_call, _resolve_hubs
        b1 = workhub_append_block_call(self.root, self.project_id, self.page_id, {
            "type": "text", "content": "before", "agent": "alice",
        })
        result = workhub_update_block_call(self.root, self.project_id, b1["id"], {
            "content": "after", "agent": "alice",
        })
        self.assertNotIn("error", result, result)
        self.assertEqual(result["content"], "after")

    def test_update_block_unknown_returns_error(self):
        from live_monitor_server import workhub_update_block_call
        result = workhub_update_block_call(self.root, self.project_id, "block_nope", {
            "content": "x", "agent": "alice",
        })
        self.assertIn("error", result)

    def test_insert_block_after_keeps_order(self):
        from live_monitor_server import workhub_append_block_call, workhub_insert_block_after_call, _resolve_hubs
        b1 = workhub_append_block_call(self.root, self.project_id, self.page_id, {
            "type": "text", "content": "first", "agent": "alice",
        })
        b3 = workhub_append_block_call(self.root, self.project_id, self.page_id, {
            "type": "text", "content": "third", "agent": "alice",
        })
        b2 = workhub_insert_block_after_call(self.root, self.project_id, self.page_id, b1["id"], {
            "type": "text", "content": "second", "agent": "alice",
        })
        self.assertNotIn("error", b2, b2)
        # b2's ord must be between b1 and b3
        self.assertLess(b1["ord"], b2["ord"])
        self.assertLess(b2["ord"], b3["ord"])

    def test_insert_block_unknown_after_appends_at_end(self):
        from live_monitor_server import workhub_append_block_call, workhub_insert_block_after_call, _resolve_hubs
        b1 = workhub_append_block_call(self.root, self.project_id, self.page_id, {
            "type": "text", "content": "first", "agent": "alice",
        })
        result = workhub_insert_block_after_call(self.root, self.project_id, self.page_id, "nope", {
            "type": "text", "content": "should-append", "agent": "alice",
        })
        # WorkHub's insert_block_after appends when after_block_id is unknown.
        self.assertNotIn("error", result, result)
        self.assertGreater(result["ord"], b1["ord"])
```

Run → expect failures.

### TDD Step 2: implement

In `live_monitor_server.py`, add near the other workhub helpers:

```python
def workhub_append_block_call(workspaces_root: Path, project_id: str, page_id: str, body: dict) -> dict:
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    block = {
        "type": (body.get("type") or "text").strip(),
        "content": body.get("content") or "",
        "metadata": body.get("metadata") or {},
    }
    if "id" in body:
        block["id"] = body["id"]
    agent = (body.get("agent") or "ui_user").strip()
    try:
        return reg.workhub.append_block(page_id=page_id, block=block, agent=agent)
    except Exception as e:
        return {"error": str(e)}


def workhub_update_block_call(workspaces_root: Path, project_id: str, block_id: str, body: dict) -> dict:
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    if "content" not in body:
        return {"error": "content required"}
    agent = (body.get("agent") or "ui_user").strip()
    try:
        return reg.workhub.update_block(block_id=block_id, content=body["content"], agent=agent)
    except Exception as e:
        return {"error": str(e)}


def workhub_insert_block_after_call(workspaces_root: Path, project_id: str, page_id: str,
                                    after_block_id: str, body: dict) -> dict:
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    block = {
        "type": (body.get("type") or "text").strip(),
        "content": body.get("content") or "",
        "metadata": body.get("metadata") or {},
    }
    if "id" in body:
        block["id"] = body["id"]
    agent = (body.get("agent") or "ui_user").strip()
    try:
        return reg.workhub.insert_block_after(
            page_id=page_id,
            after_block_id=after_block_id,
            block=block,
            agent=agent,
        )
    except Exception as e:
        return {"error": str(e)}
```

Add 3 routes to `do_POST`. URL patterns (URL-decoded ids):

- `POST /api/projects/<pid>/workhub/pages/<page_id>/blocks` → append_block_call
- `POST /api/projects/<pid>/workhub/blocks/<block_id>` → update_block_call  (POST-as-update; matches Cutover 33 set_priority pattern)
- `POST /api/projects/<pid>/workhub/pages/<page_id>/blocks/<after_id>/after` → insert_block_after_call

Each route uses `urllib.parse.unquote` to handle encoded ids.

Add the routing logic to `do_POST` (somewhere among the workhub branches):

```python
# Cutover 37 block-editor endpoints
import urllib.parse
m_append = re.match(r"^/api/projects/([^/]+)/workhub/pages/([^/]+)/blocks$", parsed.path)
if m_append:
    pid = urllib.parse.unquote(m_append.group(1))
    page_id = urllib.parse.unquote(m_append.group(2))
    self._write_json(workhub_append_block_call(self._workspaces_root, pid, page_id, body))
    return

m_insert = re.match(r"^/api/projects/([^/]+)/workhub/pages/([^/]+)/blocks/([^/]+)/after$", parsed.path)
if m_insert:
    pid = urllib.parse.unquote(m_insert.group(1))
    page_id = urllib.parse.unquote(m_insert.group(2))
    after_id = urllib.parse.unquote(m_insert.group(3))
    self._write_json(workhub_insert_block_after_call(self._workspaces_root, pid, page_id, after_id, body))
    return

m_update = re.match(r"^/api/projects/([^/]+)/workhub/blocks/([^/]+)$", parsed.path)
if m_update:
    pid = urllib.parse.unquote(m_update.group(1))
    block_id = urllib.parse.unquote(m_update.group(2))
    self._write_json(workhub_update_block_call(self._workspaces_root, pid, block_id, body))
    return
```

(Add `import re` at the top of the file if not already imported.)

Run tests → expect 6 PASS.

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor_server.py agent/tests/test_live_monitor_endpoints.py
git commit -m "Cutover 37: WorkHub block editor backend endpoints (append/update/insert-after)"
```

---

## Task 3: Frontend — Block editor in WorkHub panel

**Files:**
- Modify: `agent/env_generator/llm_generator/live_monitor/src/hub_panels.jsx`
- Modify: `agent/env_generator/llm_generator/live_monitor/styles/hubs.css`

### Step 1: BlockEditor component

Add to `hub_panels.jsx` (inside the IIFE that builds the panels). Read the existing structure first; the WorkHubPanel currently renders pages — modify each page row to support an "Expand" toggle.

Sketch:

```jsx
function BlockEditor({ projectId, page, blocks, onRefresh }) {
  const { useState } = React;
  const [editing, setEditing] = useState({});   // {block_id: draftText}
  const [appendDraft, setAppendDraft] = useState("");
  const [appendType, setAppendType] = useState("text");

  const pageBlocks = (Object.values(blocks || {}))
    .filter(b => b.page_id === page.id)
    .sort((a, b) => (a.ord || 0) - (b.ord || 0));

  async function postJson(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(body),
    });
    return r.json();
  }

  async function saveBlock(blockId) {
    const draft = editing[blockId];
    if (draft === undefined) return;
    await postJson(
      `/api/projects/${encodeURIComponent(projectId)}/workhub/blocks/${encodeURIComponent(blockId)}`,
      { content: draft, agent: "ui_user" }
    );
    setEditing(prev => { const c = {...prev}; delete c[blockId]; return c; });
    window.LiveMonitorRefresh?.();
  }

  async function appendBlock() {
    if (!appendDraft.trim()) return;
    await postJson(
      `/api/projects/${encodeURIComponent(projectId)}/workhub/pages/${encodeURIComponent(page.id)}/blocks`,
      { type: appendType, content: appendDraft, agent: "ui_user" }
    );
    setAppendDraft("");
    window.LiveMonitorRefresh?.();
  }

  async function insertAfter(afterBlockId, type) {
    const content = window.prompt(`New ${type} block content:`);
    if (!content) return;
    await postJson(
      `/api/projects/${encodeURIComponent(projectId)}/workhub/pages/${encodeURIComponent(page.id)}/blocks/${encodeURIComponent(afterBlockId)}/after`,
      { type, content, agent: "ui_user" }
    );
    window.LiveMonitorRefresh?.();
  }

  return (
    <div className="block-editor">
      {pageBlocks.length === 0 && <div className="block-empty">(no blocks)</div>}
      {pageBlocks.map((b, i) => (
        <div key={b.id} className={`block block-${b.type || "text"}`}>
          <div className="block-meta">
            <span className="block-type-pill">{b.type || "text"}</span>
            <code className="block-id">{b.id.substr(0, 12)}…</code>
          </div>
          {editing[b.id] !== undefined ? (
            <div className="block-edit">
              <textarea
                value={editing[b.id]}
                onChange={e => setEditing(prev => ({...prev, [b.id]: e.target.value}))}
                rows={Math.max(3, (editing[b.id].split("\n").length))}
              />
              <div className="block-edit-actions">
                <button onClick={() => saveBlock(b.id)} className="block-save-btn">Save</button>
                <button onClick={() => setEditing(prev => { const c = {...prev}; delete c[b.id]; return c; })}
                        className="block-cancel-btn">Cancel</button>
              </div>
            </div>
          ) : (
            <pre className="block-content"
                 onClick={() => setEditing(prev => ({...prev, [b.id]: b.content || ""}))}
                 title="Click to edit">
              {b.content || "(empty)"}
            </pre>
          )}
          <div className="block-insert-after">
            <span>+ Insert after:</span>
            {["text", "code", "heading", "quote"].map(t => (
              <button key={t} onClick={() => insertAfter(b.id, t)} className="block-insert-btn">{t}</button>
            ))}
          </div>
        </div>
      ))}
      <div className="block-append">
        <select value={appendType} onChange={e => setAppendType(e.target.value)}>
          <option value="text">text</option>
          <option value="code">code</option>
          <option value="heading">heading</option>
          <option value="quote">quote</option>
        </select>
        <textarea
          value={appendDraft}
          onChange={e => setAppendDraft(e.target.value)}
          placeholder="New block content…"
          rows={3}
        />
        <button onClick={appendBlock} className="block-append-btn" disabled={!appendDraft.trim()}>
          + Add block
        </button>
      </div>
    </div>
  );
}
```

### Step 2: wire into WorkHubPanel

In the existing `WorkHubPanel`, find where pages are listed. Add a per-page expand state + render the `<BlockEditor>` when expanded:

```jsx
const [expandedPages, setExpandedPages] = useState({});

// In the pages list render:
{Object.values(workhub.pages || {}).map(p => (
  <div key={p.id} className="page-card">
    <div className="page-row">
      <strong>{p.title || "(untitled)"}</strong>
      <code className="page-id">{p.id.substr(0, 12)}…</code>
      <button onClick={() => setExpandedPages(prev => ({...prev, [p.id]: !prev[p.id]}))}
              className="page-expand-btn">
        {expandedPages[p.id] ? "▼ Hide blocks" : "▶ Show blocks"}
      </button>
    </div>
    {expandedPages[p.id] && (
      <BlockEditor projectId={projectId} page={p} blocks={workhub.blocks || {}} />
    )}
  </div>
))}
```

(Adapt to existing component structure.)

### Step 3: styles

Append to `hubs.css`:

```css
.block-editor {
  background: #0e1626; border-top: 1px solid #2d3a4d;
  padding: 10px; margin-top: 4px;
  display: flex; flex-direction: column; gap: 8px;
}
.block-empty { color: #889; font-style: italic; padding: 6px; }
.block {
  background: #14202c; border: 1px solid #2d3a4d;
  border-radius: 4px; padding: 8px;
}
.block-meta { display: flex; gap: 8px; font-size: 11px; color: #889; margin-bottom: 4px; }
.block-type-pill {
  background: #1a3a5a; color: #6cc;
  border-radius: 999px; padding: 1px 8px; font-size: 10px;
}
.block-code .block-type-pill { background: #3a3a1a; color: #cca; }
.block-heading .block-type-pill { background: #3a1a3a; color: #cac; }
.block-quote .block-type-pill { background: #1a3a1a; color: #8c8; }
.block-id { color: #556; font-family: monospace; font-size: 10px; }
.block-content {
  margin: 0; padding: 6px 0;
  font-family: monospace; font-size: 12px;
  color: #cdd; white-space: pre-wrap; word-break: break-word;
  cursor: pointer;
  min-height: 1em;
}
.block-content:hover { background: rgba(255,255,255,0.02); }
.block-edit textarea {
  width: 100%; background: #0a1018; color: #cdd;
  border: 1px solid #4070d0; border-radius: 4px;
  padding: 6px; font-family: monospace; font-size: 12px;
  resize: vertical;
}
.block-edit-actions { display: flex; gap: 6px; margin-top: 4px; }
.block-save-btn { background: #4070d0; color: #fff; border: none; border-radius: 3px; padding: 4px 12px; font-size: 11px; cursor: pointer; }
.block-cancel-btn { background: transparent; color: #aab; border: 1px solid #354054; border-radius: 3px; padding: 4px 12px; font-size: 11px; cursor: pointer; }
.block-insert-after {
  display: flex; gap: 4px; align-items: center;
  margin-top: 6px; padding-top: 6px;
  border-top: 1px dashed #2d3a4d;
  font-size: 10px; color: #667;
}
.block-insert-btn {
  background: transparent; color: #aab;
  border: 1px solid #354054; border-radius: 3px;
  padding: 2px 8px; font-size: 10px; cursor: pointer;
}
.block-insert-btn:hover { color: #fff; border-color: #4070d0; }
.block-append {
  background: #1a2538; border-top: 2px dashed #354054;
  padding: 8px; margin-top: 8px;
  display: flex; flex-direction: column; gap: 6px;
}
.block-append textarea {
  background: #0a1018; color: #cdd;
  border: 1px solid #354054; border-radius: 4px;
  padding: 6px; font-family: monospace; font-size: 12px;
  resize: vertical;
}
.block-append select { align-self: flex-start; background: #0e1626; color: #ddd; border: 1px solid #354054; border-radius: 4px; padding: 4px 8px; }
.block-append-btn { background: #4070d0; color: #fff; border: none; border-radius: 4px; padding: 6px 14px; font-weight: 600; cursor: pointer; align-self: flex-start; }
.block-append-btn:disabled { background: #354054; cursor: not-allowed; }
.page-expand-btn { background: transparent; color: #aab; border: 1px solid #354054; border-radius: 3px; padding: 2px 8px; font-size: 11px; cursor: pointer; margin-left: auto; }
.page-expand-btn:hover { color: #fff; border-color: #4070d0; }
```

### Step 4: Manual smoke

```bash
mkdir -p /tmp/c37_ws
/home/haibotong/miniconda3/envs/dt/bin/python agent/env_generator/llm_generator/live_monitor_server.py --workspaces-root /tmp/c37_ws --port 4401 &
SERVER_PID=$!
sleep 1
PID=$(curl -sS -X POST http://127.0.0.1:4401/api/projects -H "Content-Type: application/json" -d '{"name":"blocks-demo"}' | python -c "import json,sys;print(json.load(sys.stdin)['id'])")
PAGE=$(curl -sS -X POST http://127.0.0.1:4401/api/projects/$PID/workhub/pages -H "Content-Type: application/json" -d '{"title":"Design","agent":"alice"}' | python -c "import json,sys;print(json.load(sys.stdin)['id'])")
echo "page: $PAGE"
# Append block
curl -sS -X POST "http://127.0.0.1:4401/api/projects/$PID/workhub/pages/$PAGE/blocks" -H "Content-Type: application/json" -d '{"type":"text","content":"Hello world","agent":"alice"}' | python -m json.tool | head -5
# List via state
curl -sS http://127.0.0.1:4401/api/projects/$PID/state | python -c "import sys,json; d=json.load(sys.stdin); print('blocks:', d['hubs']['workhub'].get('blocks',{}))"
kill $SERVER_PID 2>/dev/null
```

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor/src/hub_panels.jsx \
        agent/env_generator/llm_generator/live_monitor/styles/hubs.css
git commit -m "Cutover 37: WorkHub block editor frontend (expandable page block lists)"
```

---

## Task 4: Migration log + push + ff-merge

### Step 1: full sweep

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_live_monitor_endpoints.py -q 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
```

Expect: 79 endpoint tests pass (73 prior + 6 new); regressions 7 OK.

### Step 2: migration log

Overwrite `docs/superpowers/migration-logs/37-block-editor.md` with the full template:

```markdown
# Cutover 37: WorkHub Block Editor

**Branch:** `haibotong-cutover-37-block-editor`
**Date:** 2026-05-26

## What

Closes Cutover 33's deferred WorkHub block editor.

Backend: 3 endpoints over the existing `workhub.append_block` /
`update_block` / `insert_block_after` methods.

Frontend: each page row in `WorkHubPanel` gains an Expand toggle that
reveals a `<BlockEditor>` showing every block (sorted by `ord`), with
inline-click-to-edit, "+ Insert after" buttons of each block (with
type dropdown text/code/heading/quote), and a sticky "Add block" form
at the bottom.

## Commits

- (SHA) Cutover 37: record pre-flight baseline
- (SHA) Cutover 37: WorkHub block editor backend endpoints (append/update/insert-after)
- (SHA) Cutover 37: WorkHub block editor frontend (expandable page block lists)
- (this) Cutover 37: migration log

## Test deltas
- Regressions: 7 OK → 7 OK
- Pytest collect: 1112 → ~1118 (+6 block-editor tests)

## New surfaces

### Backend
- `workhub_append_block_call(workspaces_root, project_id, page_id, body)` → `workhub.append_block`
- `workhub_update_block_call(workspaces_root, project_id, block_id, body)` → `workhub.update_block`
- `workhub_insert_block_after_call(workspaces_root, project_id, page_id, after_block_id, body)` → `workhub.insert_block_after`
- `POST /api/projects/<id>/workhub/pages/<page_id>/blocks`
- `POST /api/projects/<id>/workhub/blocks/<block_id>` (POST-as-update; matches Cutover 33 set_priority pattern)
- `POST /api/projects/<id>/workhub/pages/<page_id>/blocks/<after_id>/after`

### Frontend
- `<BlockEditor projectId page blocks />` component in `hub_panels.jsx`
- Per-page Expand toggle in `WorkHubPanel`
- Click-to-edit content (textarea); Save/Cancel buttons
- "+ Insert after" prompts for content (via `window.prompt`); 4 type buttons
- "+ Add block" at bottom with type dropdown + textarea

## Known limits

- No delete operation — WorkHub doesn't expose `delete_block`. Users
  can clear the content to "(empty)" but the block record stays.
- No reorder by drag — to reorder, use Insert After + clear original.
- No rich text — content is plain text (textarea). Markdown/HTML
  rendering is a future cutover.
- Block ord rebalancing not exposed: heavy insert-after activity may
  eventually exhaust integer gaps (WorkHub uses 1024-step ords, so
  thousands of inserts are needed before this matters).
- `+ Insert after` uses `window.prompt` (one-line input). Multi-line
  block content via insert-after needs the future drag-or-modal flow.
```

### Step 3: commit + push + ff-merge

```bash
git add docs/superpowers/migration-logs/37-block-editor.md docs/superpowers/plans/2026-05-26-cutover-37-block-editor.md
git commit -m "Cutover 37: migration log"
git push -u red-env-gen haibotong-cutover-37-block-editor
cd /data/common/haibotong/env-gen
git fetch . haibotong-cutover-37-block-editor
git merge --ff-only haibotong-cutover-37-block-editor
git push red-env-gen haibotong-0521-pipeline-web-tools
```
