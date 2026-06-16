# Cutover 40: Reference Materials Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Let users upload any reference material into a project — images, MCP `.py` files, OpenAPI specs, markdown docs, sample data — without going through the CLI. Files land in `<workspace>/references/` and are surfaced to agents via an auto-generated `INDEX.md` that lists every file with its category and a short preview.

**Architecture:**
- Storage: `<workspace>/references/` directory. One file per upload, filename preserved.
- Categories auto-detected by extension: `image` (png/jpg/jpeg/webp/gif), `python` (.py — typically MCP server code), `spec` (yaml/yml/json), `doc` (md/txt/rst), `data` (csv/tsv/jsonl), `other`.
- Backend stores files via base64-encoded JSON body (simpler than multipart in stdlib `http.server`). 10MB per-file cap; path-traversal rejected.
- After every upload/delete, rewrite `<workspace>/references/INDEX.md` so the orchestrator's agents can read a single file to discover all references.
- 3 endpoints under `/api/projects/<id>/references`:
  - `GET` → `{files: [{name, category, size, uploaded_at, preview?}]}`
  - `POST` body `{filename, content_base64, content_type?}` → save + regenerate INDEX
  - `DELETE /<filename>` → remove + regenerate INDEX
- Frontend: a `<ReferencesSection>` component in the WorkHubPanel (next to UserGatesSection from Cutover 39). Drop a file → reads via FileReader → POSTs base64; lists existing files with category badges; download/delete buttons.

**Tech Stack:** stdlib `base64`, `mimetypes`. No new deps.

---

## Test infrastructure conventions

Tests in `agent/tests/` with sys.path boilerplate. Regressions: `python agent/tests/run_regressions.py`. NO `Co-Authored-By: Claude` trailer.

---

## File Structure

**Create:**
- `docs/superpowers/migration-logs/40-references.md`
- `agent/tests/test_references.py`

**Modify:**
- `agent/env_generator/llm_generator/live_monitor_server.py` (helpers + 3 endpoints + INDEX.md generator)
- `agent/env_generator/llm_generator/live_monitor/src/hub_panels.jsx` (ReferencesSection)
- `agent/env_generator/llm_generator/live_monitor/styles/hubs.css`

---

## Task 1: Pre-flight baseline

- [ ] Regressions → 7 OK
- [ ] Pytest collect → ~1150
- [ ] Migration log stub
- [ ] Stage plan
- [ ] Commit: `Cutover 40: record pre-flight baseline`

---

## Task 2: Backend — upload/list/delete + INDEX.md autogen

**Files:**
- Modify: `live_monitor_server.py`
- Create: `agent/tests/test_references.py`

### TDD Step 1: failing tests

```python
# agent/tests/test_references.py
import base64
import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))


class TestReferences(unittest.TestCase):
    def setUp(self):
        from live_monitor_server import _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        from live_monitor_server import create_project_call
        self.project_id = create_project_call(self.root, {"name": "refs-test"})["id"]
        self.workspace = self.root / self.project_id

    def tearDown(self):
        from live_monitor_server import _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp.cleanup()

    def _b64(self, raw: bytes) -> str:
        return base64.b64encode(raw).decode("ascii")

    def test_list_references_empty(self):
        from live_monitor_server import list_references_call
        result = list_references_call(self.root, self.project_id)
        self.assertEqual(result, {"files": []})

    def test_upload_text_file_saves_and_lists(self):
        from live_monitor_server import upload_reference_call, list_references_call
        result = upload_reference_call(self.root, self.project_id, {
            "filename": "spec.md",
            "content_base64": self._b64(b"# Design Spec\n\nHello world\n"),
        })
        self.assertNotIn("error", result, result)
        self.assertEqual(result["name"], "spec.md")
        self.assertEqual(result["category"], "doc")
        listed = list_references_call(self.root, self.project_id)["files"]
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["name"], "spec.md")
        self.assertIn("preview", listed[0])
        self.assertIn("Design Spec", listed[0]["preview"])

    def test_upload_python_categorized_as_python(self):
        from live_monitor_server import upload_reference_call
        result = upload_reference_call(self.root, self.project_id, {
            "filename": "mcp_server.py",
            "content_base64": self._b64(b"def hello(): return 'world'\n"),
        })
        self.assertEqual(result["category"], "python")

    def test_upload_image_categorized_as_image(self):
        from live_monitor_server import upload_reference_call
        result = upload_reference_call(self.root, self.project_id, {
            "filename": "screenshot.png",
            "content_base64": self._b64(b"\x89PNG\r\n\x1a\nfake-png-bytes"),
        })
        self.assertEqual(result["category"], "image")

    def test_upload_yaml_categorized_as_spec(self):
        from live_monitor_server import upload_reference_call
        result = upload_reference_call(self.root, self.project_id, {
            "filename": "openapi.yaml",
            "content_base64": self._b64(b"openapi: 3.0.0\n"),
        })
        self.assertEqual(result["category"], "spec")

    def test_upload_rejects_path_traversal(self):
        from live_monitor_server import upload_reference_call
        for bad in ["../escape.txt", "subdir/file.txt", "/absolute.txt"]:
            result = upload_reference_call(self.root, self.project_id, {
                "filename": bad,
                "content_base64": self._b64(b"x"),
            })
            self.assertIn("error", result, f"Should reject {bad}: {result}")

    def test_upload_rejects_empty_filename(self):
        from live_monitor_server import upload_reference_call
        result = upload_reference_call(self.root, self.project_id, {
            "filename": "  ",
            "content_base64": self._b64(b"x"),
        })
        self.assertIn("error", result)

    def test_upload_size_cap_enforced(self):
        from live_monitor_server import upload_reference_call
        big = b"x" * (11 * 1024 * 1024)  # 11 MB
        result = upload_reference_call(self.root, self.project_id, {
            "filename": "big.bin",
            "content_base64": self._b64(big),
        })
        self.assertIn("error", result)
        self.assertIn("size", result["error"].lower())

    def test_delete_reference_removes_file(self):
        from live_monitor_server import upload_reference_call, delete_reference_call, list_references_call
        upload_reference_call(self.root, self.project_id, {
            "filename": "to-delete.md", "content_base64": self._b64(b"bye"),
        })
        result = delete_reference_call(self.root, self.project_id, "to-delete.md")
        self.assertNotIn("error", result, result)
        self.assertEqual(list_references_call(self.root, self.project_id)["files"], [])

    def test_delete_unknown_returns_error(self):
        from live_monitor_server import delete_reference_call
        result = delete_reference_call(self.root, self.project_id, "nope.md")
        self.assertIn("error", result)

    def test_upload_regenerates_index_md(self):
        from live_monitor_server import upload_reference_call
        upload_reference_call(self.root, self.project_id, {
            "filename": "a.md", "content_base64": self._b64(b"file a"),
        })
        upload_reference_call(self.root, self.project_id, {
            "filename": "b.py", "content_base64": self._b64(b"# file b\n"),
        })
        index = self.workspace / "references" / "INDEX.md"
        self.assertTrue(index.exists())
        content = index.read_text()
        self.assertIn("a.md", content)
        self.assertIn("b.py", content)
        self.assertIn("python", content)
        self.assertIn("doc", content)

    def test_delete_regenerates_index_md(self):
        from live_monitor_server import upload_reference_call, delete_reference_call
        upload_reference_call(self.root, self.project_id, {
            "filename": "x.md", "content_base64": self._b64(b"x"),
        })
        delete_reference_call(self.root, self.project_id, "x.md")
        index = self.workspace / "references" / "INDEX.md"
        # INDEX.md still exists but is empty (or notes "no references")
        if index.exists():
            content = index.read_text()
            self.assertNotIn("x.md", content)

    def test_overwrite_existing_filename(self):
        from live_monitor_server import upload_reference_call, list_references_call
        upload_reference_call(self.root, self.project_id, {
            "filename": "spec.md", "content_base64": self._b64(b"v1 content"),
        })
        upload_reference_call(self.root, self.project_id, {
            "filename": "spec.md", "content_base64": self._b64(b"v2 content"),
        })
        files = list_references_call(self.root, self.project_id)["files"]
        self.assertEqual(len(files), 1)
        self.assertIn("v2", files[0]["preview"])
```

Run → expect failures.

### TDD Step 2: implement

In `live_monitor_server.py`, add:

```python
# ---------------------------------------------------------------------------
# Cutover 40: Reference materials
# ---------------------------------------------------------------------------

_REFERENCE_MAX_BYTES = 10 * 1024 * 1024  # 10 MB

_REFERENCE_CATEGORY = {
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image", ".gif": "image", ".svg": "image",
    ".py": "python",
    ".yaml": "spec", ".yml": "spec", ".json": "spec",
    ".md": "doc", ".txt": "doc", ".rst": "doc",
    ".csv": "data", ".tsv": "data", ".jsonl": "data", ".ndjson": "data",
}


def _references_dir(workspace: Path) -> Path:
    return Path(workspace) / "references"


def _categorize_file(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return _REFERENCE_CATEGORY.get(ext, "other")


def _safe_reference_path(workspace: Path, filename: str) -> Optional[Path]:
    """Return absolute path inside <workspace>/references/, or None if unsafe."""
    name = (filename or "").strip()
    if not name:
        return None
    # Reject any path separators or parent-directory components
    if "/" in name or "\\" in name or name.startswith("."):
        return None
    if ".." in Path(name).parts:
        return None
    refs_dir = _references_dir(workspace)
    target = refs_dir / name
    try:
        target_resolved = target.resolve()
        refs_resolved = refs_dir.resolve()
        target_resolved.relative_to(refs_resolved)
    except Exception:
        return None
    return target


def _file_preview(path: Path, max_chars: int = 400) -> Optional[str]:
    """Return a short text preview for non-binary files."""
    try:
        if not path.exists() or path.stat().st_size > 1024 * 1024:
            return None
        # Heuristic: skip binary
        with path.open("rb") as f:
            head = f.read(2048)
        if b"\0" in head:
            return None
        try:
            text = head.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            text = head.decode("utf-8", errors="replace")
        return text[:max_chars]
    except Exception:
        return None


def _regenerate_references_index(workspace: Path) -> None:
    refs_dir = _references_dir(workspace)
    refs_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for child in refs_dir.iterdir():
        if not child.is_file() or child.name == "INDEX.md":
            continue
        files.append(child)
    files.sort(key=lambda p: p.name)
    lines = [
        "# References Index",
        "",
        "Files in this directory are reference materials provided by the operator.",
        "Agents should read this index to discover available references and consult",
        "the matching file when their task aligns with the reference content.",
        "",
        "| File | Category | Size |",
        "|------|----------|------|",
    ]
    for p in files:
        try:
            size = p.stat().st_size
        except Exception:
            size = 0
        lines.append(f"| `{p.name}` | {_categorize_file(p.name)} | {size}B |")
    if not files:
        lines.append("| _(no references yet)_ | | |")
    (refs_dir / "INDEX.md").write_text("\n".join(lines) + "\n")


def list_references_call(workspaces_root: Path, project_id: str) -> dict:
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    refs_dir = _references_dir(workspace)
    if not refs_dir.exists():
        return {"files": []}
    out = []
    for child in sorted(refs_dir.iterdir(), key=lambda p: p.name):
        if not child.is_file() or child.name == "INDEX.md":
            continue
        try:
            stat = child.stat()
        except Exception:
            continue
        out.append({
            "name": child.name,
            "category": _categorize_file(child.name),
            "size": stat.st_size,
            "uploaded_at": stat.st_mtime,
            "preview": _file_preview(child),
        })
    return {"files": out}


def upload_reference_call(workspaces_root: Path, project_id: str, body: dict) -> dict:
    import base64 as _b64
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    filename = (body.get("filename") or "").strip()
    target = _safe_reference_path(workspace, filename)
    if target is None:
        return {"error": f"invalid filename: {filename!r}"}
    content_b64 = body.get("content_base64") or ""
    if not content_b64:
        return {"error": "content_base64 required"}
    try:
        raw = _b64.b64decode(content_b64, validate=True)
    except Exception as e:
        return {"error": f"invalid base64: {e}"}
    if len(raw) > _REFERENCE_MAX_BYTES:
        return {"error": f"file size {len(raw)} exceeds cap {_REFERENCE_MAX_BYTES}"}
    refs_dir = _references_dir(workspace)
    refs_dir.mkdir(parents=True, exist_ok=True)
    try:
        target.write_bytes(raw)
    except Exception as e:
        return {"error": f"write failed: {e}"}
    _regenerate_references_index(workspace)
    return {
        "name": target.name,
        "category": _categorize_file(target.name),
        "size": len(raw),
    }


def delete_reference_call(workspaces_root: Path, project_id: str, filename: str) -> dict:
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    target = _safe_reference_path(workspace, filename)
    if target is None or not target.exists():
        return {"error": f"file not found: {filename}"}
    try:
        target.unlink()
    except Exception as e:
        return {"error": f"unlink failed: {e}"}
    _regenerate_references_index(workspace)
    return {"ok": True, "deleted": filename}
```

### Routes

In `do_GET`, near the user_gates GET:

```python
m = re.match(r"^/api/projects/([^/]+)/references$", parsed.path)
if m:
    pid = urllib.parse.unquote(m.group(1))
    self._write_json(list_references_call(self._workspaces_root, pid))
    return
```

In `do_POST`:

```python
m = re.match(r"^/api/projects/([^/]+)/references$", parsed.path)
if m:
    pid = urllib.parse.unquote(m.group(1))
    self._write_json(upload_reference_call(self._workspaces_root, pid, body))
    return
```

In `do_DELETE`:

```python
m = re.match(r"^/api/projects/([^/]+)/references/([^/]+)$", parsed.path)
if m:
    pid = urllib.parse.unquote(m.group(1))
    fname = urllib.parse.unquote(m.group(2))
    self._write_json(delete_reference_call(self._workspaces_root, pid, fname))
    return
```

Run tests → expect 12 PASS.

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor_server.py agent/tests/test_references.py
git commit -m "Cutover 40: references upload/list/delete + auto INDEX.md generation"
```

---

## Task 3: Frontend — ReferencesSection in WorkHubPanel

**Files:**
- Modify: `live_monitor/src/hub_panels.jsx`
- Modify: `live_monitor/styles/hubs.css`

### Step 1: ReferencesSection

Add to `hub_panels.jsx` (next to UserGatesSection from Cutover 39):

```jsx
function ReferencesSection({ projectId }) {
  const { useEffect, useState, useRef } = React;
  const [files, setFiles] = useState([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const fileInputRef = useRef(null);

  async function refresh() {
    if (!projectId) return;
    try {
      const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/references`,
                            { credentials: "include" });
      const data = await r.json();
      setFiles(data.files || []);
      setError("");
    } catch (e) {
      setError(String(e));
    }
  }
  useEffect(() => { refresh(); }, [projectId]);

  function handleFile(file) {
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) {
      setError(`${file.name} exceeds 10MB cap`);
      return;
    }
    setPending(true); setError("");
    const reader = new FileReader();
    reader.onload = async (ev) => {
      try {
        const dataUrl = ev.target.result;  // e.g. "data:image/png;base64,iVBOR..."
        const b64 = dataUrl.split(",")[1] || "";
        const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/references`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ filename: file.name, content_base64: b64 }),
        });
        const data = await r.json();
        if (data.error) { setError(data.error); }
        else { refresh(); }
      } catch (e) {
        setError(String(e));
      } finally {
        setPending(false);
      }
    };
    reader.onerror = () => { setError("file read failed"); setPending(false); };
    reader.readAsDataURL(file);
  }

  function onFileChange(e) {
    const f = e.target.files?.[0];
    if (f) handleFile(f);
    e.target.value = "";  // allow re-uploading same file
  }

  async function deleteFile(name) {
    if (!window.confirm(`Delete reference '${name}'?`)) return;
    await fetch(`/api/projects/${encodeURIComponent(projectId)}/references/${encodeURIComponent(name)}`,
                { method: "DELETE", credentials: "include" });
    refresh();
  }

  function fmtSize(n) {
    if (n < 1024) return `${n}B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}KB`;
    return `${(n / (1024 * 1024)).toFixed(1)}MB`;
  }

  return (
    <div className="references-section">
      <div className="references-header">
        <strong>References</strong>
        <input type="file" ref={fileInputRef} onChange={onFileChange} style={{ display: "none" }} />
        <button onClick={() => fileInputRef.current?.click()} className="ref-upload-btn" disabled={pending}>
          {pending ? "Uploading…" : "+ Upload"}
        </button>
      </div>
      {error && <div className="ref-error">{error}</div>}
      {files.length === 0 && <div className="ref-empty">(no reference files)</div>}
      {files.map(f => (
        <div key={f.name} className={"ref-file ref-cat-" + f.category}>
          <div className="ref-file-row">
            <span className={"ref-cat-pill cat-" + f.category}>{f.category}</span>
            <code className="ref-name">{f.name}</code>
            <span className="ref-size">{fmtSize(f.size)}</span>
            <button className="ref-delete-btn" onClick={() => deleteFile(f.name)}>×</button>
          </div>
          {f.preview && (
            <details className="ref-preview-details">
              <summary>preview</summary>
              <pre className="ref-preview">{f.preview}</pre>
            </details>
          )}
        </div>
      ))}
    </div>
  );
}
```

Mount `<ReferencesSection projectId={projectId} />` inside `WorkHubPanel`, right after `<UserGatesSection />`.

### Step 2: CSS

Append to `hubs.css`:

```css
.references-section { background: #14202c; border: 1px solid #2d3a4d; border-radius: 6px; padding: 10px; margin-bottom: 12px; }
.references-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.ref-upload-btn { background: #4070d0; color: #fff; border: none; border-radius: 3px; padding: 4px 10px; font-size: 11px; cursor: pointer; }
.ref-upload-btn:disabled { background: #354054; cursor: wait; }
.ref-empty { color: #889; padding: 8px; font-style: italic; font-size: 12px; }
.ref-error { background: #4a1f1f; color: #ffaaaa; padding: 6px 10px; font-size: 11px; border-radius: 3px; margin-bottom: 6px; }
.ref-file { background: #1a2538; border-left: 3px solid; border-radius: 3px; padding: 6px 8px; margin-bottom: 4px; }
.ref-cat-image { border-left-color: #6cc; }
.ref-cat-python { border-left-color: #cca; }
.ref-cat-spec { border-left-color: #cac; }
.ref-cat-doc { border-left-color: #cdd; }
.ref-cat-data { border-left-color: #8c8; }
.ref-cat-other { border-left-color: #888; }
.ref-file-row { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.ref-cat-pill { font-size: 10px; padding: 1px 6px; border-radius: 3px; font-weight: 600; }
.cat-image { background: #1a3a5a; color: #6cc; }
.cat-python { background: #3a3a1a; color: #cca; }
.cat-spec { background: #3a1a3a; color: #cac; }
.cat-doc { background: #2a2a2a; color: #cdd; }
.cat-data { background: #1a3a1a; color: #8c8; }
.cat-other { background: #2a2a2a; color: #888; }
.ref-name { color: #cdd; font-family: monospace; flex: 1; }
.ref-size { color: #889; font-size: 10px; }
.ref-delete-btn { background: transparent; color: #faa; border: none; cursor: pointer; font-size: 14px; }
.ref-preview-details { margin-top: 4px; }
.ref-preview-details summary { cursor: pointer; color: #889; font-size: 10px; }
.ref-preview {
  background: #0a1018; color: #cdd;
  font-family: monospace; font-size: 11px;
  padding: 6px; border-radius: 3px;
  white-space: pre-wrap; word-break: break-word;
  margin: 4px 0 0; max-height: 200px; overflow: auto;
}
```

### Step 3: Manual smoke

```bash
mkdir -p /tmp/c40_ws
/home/haibotong/miniconda3/envs/dt/bin/python agent/env_generator/llm_generator/live_monitor_server.py --workspaces-root /tmp/c40_ws --port 4403 &
SERVER_PID=$!
sleep 1
PID=$(curl -sS -X POST http://127.0.0.1:4403/api/projects -H "Content-Type: application/json" -d '{"name":"refs-demo"}' | python -c "import json,sys;print(json.load(sys.stdin)['id'])")
B64=$(echo -n "Hello from spec doc" | base64)
curl -sS -X POST http://127.0.0.1:4403/api/projects/$PID/references -H "Content-Type: application/json" -d "{\"filename\":\"spec.md\",\"content_base64\":\"$B64\"}"
echo
curl -sS http://127.0.0.1:4403/api/projects/$PID/references | python -m json.tool | head -10
cat /tmp/c40_ws/$PID/references/INDEX.md
kill $SERVER_PID 2>/dev/null
```

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor/src/hub_panels.jsx \
        agent/env_generator/llm_generator/live_monitor/styles/hubs.css
git commit -m "Cutover 40: ReferencesSection frontend (upload/list/preview/delete)"
```

---

## Task 4: Migration log + push + ff-merge

### Step 1: full sweep

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_references.py -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_user_gates.py agent/tests/test_user_gates_endpoints.py agent/tests/test_live_monitor_endpoints.py -q 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
```

### Step 2: migration log

Overwrite `docs/superpowers/migration-logs/40-references.md`:

```markdown
# Cutover 40: Reference Materials Upload

**Branch:** `haibotong-cutover-40-references`
**Date:** 2026-05-26

## What

Users upload arbitrary reference materials into a project via the UI.
Files land in `<workspace>/references/<filename>` and are auto-indexed
in `<workspace>/references/INDEX.md` so agents can discover them.

Six categories detected by file extension:
- `image` (png/jpg/jpeg/webp/gif/svg)
- `python` (.py — typically MCP server source)
- `spec` (yaml/yml/json — OpenAPI etc.)
- `doc` (md/txt/rst)
- `data` (csv/tsv/jsonl/ndjson)
- `other` (anything else)

10MB per-file cap. Path-traversal rejected (no `/`, `\`, `..`, leading
`.`, or absolute paths). Same-name uploads overwrite.

## Commits

- (SHA) Cutover 40: record pre-flight baseline
- (SHA) Cutover 40: references upload/list/delete + auto INDEX.md generation
- (SHA) Cutover 40: ReferencesSection frontend (upload/list/preview/delete)
- (this) Cutover 40: migration log

## Test deltas
- Regressions: 7 OK → 7 OK
- Pytest collect: 1150 → ~1162 (+12 new tests)

## New surfaces

### Backend
- `_references_dir(workspace)`, `_categorize_file(name)`, `_safe_reference_path`, `_file_preview`, `_regenerate_references_index`
- `list_references_call(workspaces_root, project_id)` → `{files: [...]}` with category/size/uploaded_at/preview
- `upload_reference_call(workspaces_root, project_id, body)` body `{filename, content_base64}`
- `delete_reference_call(workspaces_root, project_id, filename)`
- `GET /api/projects/<id>/references` — list
- `POST /api/projects/<id>/references` — upload (base64 in body)
- `DELETE /api/projects/<id>/references/<filename>` — remove
- `INDEX.md` auto-generated on every upload + delete

### Frontend
- `<ReferencesSection projectId />` in `WorkHubPanel`
- Upload via hidden `<input type="file">` + `FileReader.readAsDataURL` → base64 POST
- Per-file: category badge, size, expandable text preview, delete button (with confirm)

## Agent integration

Agents can read `<workspace>/references/INDEX.md` to discover all uploaded
files and their categories. The orchestrator's existing
`--reference-images` mechanism (Cutover 34) already scans the workspace
for screenshots; this cutover does NOT auto-wire references into that
flow, but the INDEX.md is the single discovery point for agents that
choose to consult them.

## Known limits

- Base64 upload doubles transferred bytes (intentional — stdlib HTTP
  server doesn't parse multipart). Fine for typical reference sizes
  (≤10MB).
- No directory uploads. To upload a multi-file MCP server, zip it or
  upload one file at a time.
- Categories are extension-based only. A `.txt` file containing JSON
  is categorized as `doc`. Future cutover could sniff content.
- INDEX.md format is fixed (markdown table). Future may extend with
  content fingerprints / hash for caching.
- No content scanning / validation per category (e.g., we don't check
  that a `.yaml` is valid YAML).
- The previous `--reference-images` CLI flag is unchanged; uploading
  via the new endpoint does NOT auto-add to that list. For Cutover
  34 generations, the orchestrator must opt-in to reading the
  references directory (planned for a future cutover).
```

### Step 3: commit + push + ff-merge

```bash
git add docs/superpowers/migration-logs/40-references.md docs/superpowers/plans/2026-05-26-cutover-40-references.md
git commit -m "Cutover 40: migration log"
git push -u red-env-gen haibotong-cutover-40-references
cd /data/common/haibotong/env-gen
git fetch . haibotong-cutover-40-references
git merge --ff-only haibotong-cutover-40-references
git push red-env-gen haibotong-0521-pipeline-web-tools
```
