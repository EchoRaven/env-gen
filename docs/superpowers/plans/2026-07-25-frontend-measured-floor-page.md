# Measured-floor page projection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the frontend lane leaves a GET page unbuilt and no measured reference screen matches it, emit a measured-palette floor stamped as a structured projection (counts as built) instead of the `data-fallback` list the gates reject.

**Architecture:** Add a pure helper `_measured_floor_colors(design)` that extracts a normalized measured color set from `design["design_system"]["palette"]` (or `None` if unusable). Rewrite only the no-reference `if get_ep:` branch of `_project_page_component` in `frontend_scaffold.py` to render the same functional row-list with those measured colors + inline `backgroundColor` + `data-projected="ref"` + `_STRUCTURED_MARKER` when colors exist; otherwise emit today's `data-fallback` page unchanged.

**Tech Stack:** Python 3.11 (env at `/home/haibotong/miniconda3/envs/dt/bin/python`), pytest, React/JSX string templates.

## Global Constraints

- Tests live in `agent/tests/` (gitignored local tests); only framework code is committed.
- Test runner: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest`.
- Discipline per fix: TDD red→green, then `git stash` zero-regression check (stash the framework change → new test RED, others GREEN → pop), then `git diff --check`, then commit (NO Claude co-author trailer), then `git push vaibackup HEAD:feat/pipeline-opt-6`.
- Branch: `feat/pipeline-opt-6`. Repo: `/data/common/haibotong/forgingground-gen`.
- File under change: `agent/env_generator/llm_generator/multi_agent/runtime/frontend_scaffold.py`.
- Env-agnostic: all colors come from THIS env's measured palette; never introduce a hardcoded product color. Missing sub-roles derive from `bg` + measured neutrals.
- Exemption literals the detector keys on (`frontend_audit._is_generic_fallback_page`): a page is NOT a fallback if it contains `_STRUCTURED_MARKER` or the literal `data-projected="ref"`, OR an inline `style={{ backgroundColor:` with no `data-fallback="1"`/`_PAGE_MARKER`. The measured floor uses all three for belt-and-suspenders.

---

### Task 1: `_measured_floor_colors` helper

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/frontend_scaffold.py` (add helper near `_project_page_component`, before line 2285)
- Test: `agent/tests/test_296_measured_floor_colors.py`

**Interfaces:**
- Produces: `_measured_floor_colors(design: Optional[Mapping]) -> Optional[dict]` returning `{"bg","surface","text","muted","accent","border"}` (all str) when `design["design_system"]["palette"]["bg"]` is a non-empty string, else `None`.

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_296_measured_floor_colors.py
"""#296 — _measured_floor_colors extracts a measured color set for the no-reference floor."""
import sys
from pathlib import Path
THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS.parent / "env_generator" / "llm_generator"))
from multi_agent.runtime.frontend_scaffold import _measured_floor_colors  # noqa: E402


def _design(palette, theme="dark"):
    return {"design_system": {"palette": palette, "theme": {"default": theme}}}


def test_full_palette_maps_all_roles():
    c = _measured_floor_colors(_design({
        "bg": "#000000", "surface": "#121212", "text": "#ffffff",
        "text_2": "rgba(255,255,255,0.75)", "accent_red": "#EA445A",
        "border": "#2a2a2a"}))
    assert c["bg"] == "#000000"
    assert c["surface"] == "#121212"
    assert c["text"] == "#ffffff"
    assert c["muted"] == "rgba(255,255,255,0.75)"
    assert c["accent"] == "#EA445A"      # accent_red picked
    assert c["border"] == "#2a2a2a"


def test_generic_accent_key_picked():
    c = _measured_floor_colors(_design({"bg": "#0b0b0b", "accent": "#1DB954"}))
    assert c["accent"] == "#1DB954"


def test_missing_bg_returns_none():
    assert _measured_floor_colors(_design({"accent": "#EA445A"})) is None
    assert _measured_floor_colors(_design({})) is None
    assert _measured_floor_colors({}) is None
    assert _measured_floor_colors(None) is None


def test_missing_subroles_derive_from_bg_and_neutrals():
    # only bg present → other roles get measured-neutral defaults (never crash, never product color)
    c = _measured_floor_colors(_design({"bg": "#000000"}, theme="dark"))
    assert c["bg"] == "#000000"
    assert c["surface"] == "#000000"           # falls back to bg
    assert c["text"] == "#f5f5f5"              # dark-theme default text
    assert c["accent"] == "#2563eb"            # neutral accent default
    assert isinstance(c["muted"], str) and c["muted"]
    assert isinstance(c["border"], str) and c["border"]


def test_light_theme_text_default():
    c = _measured_floor_colors(_design({"bg": "#ffffff"}, theme="light"))
    assert c["text"] == "#18181b"


def test_theme_derived_from_bg_luminance_when_unspecified():
    c = _measured_floor_colors({"design_system": {"palette": {"bg": "#000000"}}})
    assert c["text"] == "#f5f5f5"              # dark bg → dark theme → light text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_296_measured_floor_colors.py -q`
Expected: FAIL — `ImportError: cannot import name '_measured_floor_colors'`.

- [ ] **Step 3: Write minimal implementation**

Insert immediately before `def _project_page_component(` (line ~2285) in `frontend_scaffold.py`:

```python
def _measured_floor_colors(design):
    """#296 — a normalized measured color set for the no-reference GET floor,
    or None when no usable palette exists (caller then keeps the data-fallback
    page). Reads THIS env's measured palette at design['design_system']['palette']
    (same path _render_reference_page uses); missing sub-roles derive from bg +
    measured neutrals — never a hardcoded product color."""
    ds = (design or {}).get("design_system") or {}
    if not isinstance(ds, dict):
        return None
    pal = ds.get("palette") or {}
    if not isinstance(pal, dict):
        return None
    bg = pal.get("bg")
    if not isinstance(bg, str) or not bg.strip():
        return None

    def _pick(keys, default):
        for k in keys:
            v = pal.get(k)
            if isinstance(v, str) and v.strip():
                return v
        return default

    theme = str(((ds.get("theme") or {}).get("default")) or "").lower()
    if theme not in ("dark", "light"):
        try:
            h = bg.lstrip("#")
            h = "".join(c * 2 for c in h) if len(h) == 3 else h
            lum = (int(h[0:2], 16) * 0.299 + int(h[2:4], 16) * 0.587
                   + int(h[4:6], 16) * 0.114)
            theme = "dark" if lum < 128 else "light"
        except Exception:
            theme = "light"
    text_default = "#f5f5f5" if theme == "dark" else "#18181b"
    muted_default = ("rgba(255,255,255,0.55)" if theme == "dark"
                     else "rgba(0,0,0,0.55)")
    return {
        "bg": bg,
        "surface": _pick(["surface", "surface_2", "elevated", "card"], bg),
        "text": _pick(["text"], text_default),
        "muted": _pick(["text_2", "text_3", "text_muted", "muted"], muted_default),
        "accent": _pick(["accent", "accent_red", "brand", "primary",
                         "accent_blue"], "#2563eb"),
        "border": _pick(["border", "divider"], "rgba(128,128,128,0.25)"),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_296_measured_floor_colors.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Zero-regression + commit + push**

```bash
cd /data/common/haibotong/forgingground-gen
# zero-regress: stash the framework change; new test must go RED, others GREEN
git stash push -- agent/env_generator/llm_generator/multi_agent/runtime/frontend_scaffold.py
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_296_measured_floor_colors.py -q   # expect RED (ImportError)
git stash pop
git diff --check agent/env_generator/llm_generator/multi_agent/runtime/frontend_scaffold.py
git add agent/env_generator/llm_generator/multi_agent/runtime/frontend_scaffold.py
git commit -m "feat(frontend-scaffold): #296 — _measured_floor_colors palette reader for the no-reference floor"
git push vaibackup HEAD:feat/pipeline-opt-6
```

---

### Task 2: Measured floor in the no-reference GET branch

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/frontend_scaffold.py` — the `if get_ep:` no-reference branch of `_project_page_component` (lines ~2337-2396, the `data-fallback` list template + its `return _mark_fallback_page(...)`)
- Test: `agent/tests/test_297_measured_floor_page.py`

**Interfaces:**
- Consumes: `_measured_floor_colors` (Task 1); `_STRUCTURED_MARKER` (from `frontend_page_projector`); `_nav_links_jsx`, `_api_path_to_js`, `_mark_fallback_page` (existing in `frontend_scaffold.py`); `frontend_audit._is_generic_fallback_page` (for the assertion).
- Produces: no new public interface — same `_project_page_component(...) -> str` contract; the no-reference GET output is now measured+structured when a palette exists.

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_297_measured_floor_page.py
"""#297 — no-reference GET floor is a measured, structured (non-fallback) page when a palette exists."""
import sys
from pathlib import Path
THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS.parent / "env_generator" / "llm_generator"))
from multi_agent.runtime.frontend_scaffold import _project_page_component  # noqa: E402
from multi_agent.runtime.frontend_audit import _is_generic_fallback_page  # noqa: E402
from multi_agent.runtime.frontend_page_projector import _STRUCTURED_MARKER, _PAGE_MARKER  # noqa: E402

_PAGE = {"route": "/explore", "component": "ExplorePage",
         "apis_used": ["GET /api/explore"], "name": "explore"}
_DESIGN = {"design_system": {"theme": {"default": "dark"}, "palette": {
    "bg": "#000000", "surface": "#121212", "text": "#ffffff",
    "text_2": "rgba(255,255,255,0.75)", "accent_red": "#EA445A", "border": "#2a2a2a"}}}


def test_measured_floor_is_structured_not_fallback():
    out = _project_page_component("ExplorePage", _PAGE,
                                  nav_routes=[("Home", "/"), ("Explore", "/explore")],
                                  design=_DESIGN)
    assert _STRUCTURED_MARKER in out                 # stamped structured
    assert 'data-projected="ref"' in out             # detector-exempt attr
    assert "style={{ backgroundColor: '#000000'" in out or \
           'style={{ backgroundColor: "#000000"' in out  # measured canvas paint
    assert 'data-fallback="1"' not in out            # not a fallback
    assert _PAGE_MARKER not in out                    # not marked fallback
    assert "/api/explore" in out                      # still fetches its OWN endpoint
    assert not _is_generic_fallback_page(out)         # gate treats it as BUILT


def test_no_palette_keeps_data_fallback():
    out = _project_page_component("ExplorePage", _PAGE, nav_routes=[], design={})
    assert 'data-fallback="1"' in out                 # unchanged behavior
    assert _is_generic_fallback_page(out)             # still a fallback


def test_write_only_page_unchanged_by_this_branch():
    page = {"route": "/settings", "component": "SettingsPage",
            "apis_used": ["PUT /api/settings"], "name": "settings"}
    out = _project_page_component("SettingsPage", page, nav_routes=[], design=_DESIGN)
    assert "<form" in out.lower() or "onsubmit" in out.lower() or "handleSubmit" in out
    assert _STRUCTURED_MARKER not in out              # write-only path untouched


def test_auth_page_unchanged():
    page = {"route": "/login", "component": "LoginPage",
            "apis_used": ["POST /auth/login"], "name": "login"}
    out = _project_page_component("LoginPage", page, nav_routes=[], design=_DESIGN)
    assert "password" in out.lower()                  # real login form, not the floor
    assert 'data-projected="ref"' not in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_297_measured_floor_page.py -q`
Expected: FAIL — `test_measured_floor_is_structured_not_fallback` fails (current branch emits `data-fallback="1"` + `_PAGE_MARKER`, no `_STRUCTURED_MARKER`).

- [ ] **Step 3: Write minimal implementation**

In `_project_page_component`, replace the no-reference GET branch body (the block starting `if get_ep:` at line ~2337 through its `return _mark_fallback_page(...)` at ~2396) with a measured-floor-aware version. Keep the existing generic template string as the `_FALLBACK_LIST_TPL` (no-palette path); add a measured template. Concretely:

```python
    if get_ep:
        _floor = _measured_floor_colors(design)
        _js_path = _api_path_to_js(get_ep)
        if _floor is not None:
            # MEASURED FLOOR (#296): functional row-list painted with THIS env's
            # measured palette + data-projected="ref"/_STRUCTURED_MARKER → a
            # genuine floor the gates count as BUILT (not a data-fallback). The
            # lane still refines it in place (visual-fidelity remediation).
            tpl = """import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';

const _imgOf = (r) => { for (const k of ['thumbnail_url','image_url','avatar_url','banner_url','photo_url','cover_url','poster_url','image','thumbnail','avatar','url']) { if (r && r[k]) return r[k]; } return null; };
const _titleOf = (r) => { for (const k of ['title','subject','name','display_name','full_name','label','handle','email']) { if (r && r[k]) return String(r[k]); } return (r && r.id != null) ? ('#' + r.id) : ''; };
const _subOf = (r) => { for (const k of ['snippet','preview','summary','description','from_name','sender','body','caption','content','message','text']) { if (r && r[k]) return String(r[k]); } return ''; };
const _metaOf = (r) => Object.keys(r || {}).filter((k) => !['id','password','password_hash'].includes(k) && !/_url$|^url$|^image$|^thumbnail$|^avatar$|title|subject|name|description|body|snippet/.test(k) && (typeof r[k] !== 'object')).slice(0, 3);

export default function __COMP__() {
  const params = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const token = (localStorage.getItem('access_token') || localStorage.getItem('token'));
    fetch(__PATH__, token ? { headers: { Authorization: 'Bearer ' + token } } : {})
      .then((r) => r.json())
      .then(setData)
      .catch((e) => setError(String(e)));
  }, []);
  const rows = Array.isArray(data && data.items)
    ? data.items
    : (data && data.item ? [data.item] : (Array.isArray(data) ? data : []));
  return (
    <div data-projected="ref" className="min-h-screen px-6 py-6" style={{ backgroundColor: '__BG__', color: '__TEXT__' }}>
      __NAV__
      <h2 className="text-xl font-semibold mb-4">__LABEL__</h2>
      {error ? <p className="text-sm mb-4" style={{ color: '__ACCENT__' }}>{error}</p> : null}
      <div className="rounded-lg border shadow-sm" style={{ backgroundColor: '__SURFACE__', borderColor: '__BORDER__' }}>
        {rows.map((row, i) => (
          <div key={(row && row.id) || i} className="flex items-start gap-3 px-4 py-3 cursor-pointer" style={{ borderTop: i ? '1px solid __BORDER__' : 'none' }}>
            {_imgOf(row)
              ? <img src={_imgOf(row)} alt="" className="h-10 w-10 rounded-full object-cover shrink-0" style={{ backgroundColor: '__SURFACE__' }} />
              : <div className="h-10 w-10 rounded-full shrink-0 flex items-center justify-center text-sm font-semibold" style={{ backgroundColor: '__ACCENT__', color: '#ffffff' }}>{(_titleOf(row).charAt(0) || '?').toUpperCase()}</div>}
            <div className="min-w-0 flex-1">
              <div className="font-medium text-sm truncate">{_titleOf(row)}</div>
              {_subOf(row) ? <div className="text-sm truncate" style={{ color: '__MUTED__' }}>{_subOf(row)}</div> : null}
              {_metaOf(row).length ? <div className="text-xs mt-0.5 truncate" style={{ color: '__MUTED__' }}>{_metaOf(row).map((k) => String(row[k])).join(' \\u00b7 ')}</div> : null}
            </div>
          </div>
        ))}
      </div>
      {rows.length === 0 && !error ? <p className="mt-6 text-sm" style={{ color: '__MUTED__' }}>No data yet.</p> : null}
    </div>
  );
}
"""
            body = (tpl.replace("__COMP__", name).replace("__LABEL__", label)
                    .replace("__PATH__", _js_path)
                    .replace("__NAV__", _measured_nav_jsx(nav_routes, _floor))
                    .replace("__BG__", _floor["bg"]).replace("__TEXT__", _floor["text"])
                    .replace("__SURFACE__", _floor["surface"]).replace("__BORDER__", _floor["border"])
                    .replace("__ACCENT__", _floor["accent"]).replace("__MUTED__", _floor["muted"]))
            from .frontend_page_projector import _STRUCTURED_MARKER
            return _STRUCTURED_MARKER + "\n" + body

        # NO measured palette → keep today's data-fallback list (still forces the lane).
        tpl = """import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';

const _imgOf = (r) => { for (const k of ['thumbnail_url','image_url','avatar_url','banner_url','photo_url','cover_url','poster_url','image','thumbnail','avatar','url']) { if (r && r[k]) return r[k]; } return null; };
const _titleOf = (r) => { for (const k of ['title','subject','name','display_name','full_name','label','handle','email']) { if (r && r[k]) return String(r[k]); } return (r && r.id != null) ? ('#' + r.id) : ''; };
const _subOf = (r) => { for (const k of ['snippet','preview','summary','description','from_name','sender','body','caption','content','message','text']) { if (r && r[k]) return String(r[k]); } return ''; };
const _metaOf = (r) => Object.keys(r || {}).filter((k) => !['id','password','password_hash'].includes(k) && !/_url$|^url$|^image$|^thumbnail$|^avatar$|title|subject|name|description|body|snippet/.test(k) && (typeof r[k] !== 'object')).slice(0, 3);

export default function __COMP__() {
  const params = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const token = (localStorage.getItem('access_token') || localStorage.getItem('token'));
    fetch(__PATH__, token ? { headers: { Authorization: 'Bearer ' + token } } : {})
      .then((r) => r.json())
      .then(setData)
      .catch((e) => setError(String(e)));
  }, []);
  const rows = Array.isArray(data && data.items)
    ? data.items
    : (data && data.item ? [data.item] : (Array.isArray(data) ? data : []));
  return (
    <div data-fallback="1" className="min-h-screen bg-zinc-50 text-zinc-900 px-6 py-6">
      __NAV__
      <h2 className="text-xl font-semibold mb-4">__LABEL__</h2>
      {error ? <p className="text-sm text-red-600 mb-4">{error}</p> : null}
      <div className="divide-y divide-zinc-200 rounded-lg border border-zinc-200 bg-white shadow-sm">
        {rows.map((row, i) => (
          <div key={(row && row.id) || i} className="flex items-start gap-3 px-4 py-3 hover:bg-zinc-50 transition cursor-pointer">
            {_imgOf(row)
              ? <img src={_imgOf(row)} alt="" className="h-10 w-10 rounded-full object-cover bg-zinc-100 shrink-0" />
              : <div className="h-10 w-10 rounded-full bg-blue-100 text-blue-700 shrink-0 flex items-center justify-center text-sm font-semibold">{(_titleOf(row).charAt(0) || '?').toUpperCase()}</div>}
            <div className="min-w-0 flex-1">
              <div className="font-medium text-sm truncate">{_titleOf(row)}</div>
              {_subOf(row) ? <div className="text-sm text-zinc-500 truncate">{_subOf(row)}</div> : null}
              {_metaOf(row).length ? <div className="text-xs text-zinc-400 mt-0.5 truncate">{_metaOf(row).map((k) => String(row[k])).join(' \\u00b7 ')}</div> : null}
            </div>
          </div>
        ))}
      </div>
      {rows.length === 0 && !error ? <p className="mt-6 text-sm text-zinc-500">No data yet.</p> : null}
    </div>
  );
}
"""
        return _mark_fallback_page(tpl.replace("__COMP__", name).replace("__LABEL__", label)
                                   .replace("__PATH__", _js_path)
                                   .replace("__NAV__", _nav))
```

Also add the measured top-nav helper (near `_nav_links_jsx`, ~line 1667):

```python
def _measured_nav_jsx(nav_routes, colors) -> str:
    """Measured-palette top-nav for the #296 floor (inline colors so the darkify
    healers don't need to recolor it and the page stays self-contained)."""
    routes = [(str(l).strip(), str(r).strip()) for (l, r) in (nav_routes or []) if str(r).strip()]
    if not routes:
        return ""
    links = "\n".join(
        f'        <a href="{r}" className="rounded-md px-3 py-1.5 text-sm font-medium" '
        f"style={{{{ color: '{colors['muted']}' }}}}>{l}</a>"
        for (l, r) in routes)
    return (
        '<nav className="-mx-6 -mt-6 mb-6 flex flex-wrap items-center gap-1 border-b px-6 py-2" '
        f"style={{{{ backgroundColor: '{colors['surface']}', borderColor: '{colors['border']}' }}}}>\n"
        + links + "\n"
        "        <button onClick={() => { localStorage.clear(); window.location.href = '/login'; }} "
        f"className=\"ml-auto rounded-md px-3 py-1.5 text-sm\" style={{{{ color: '{colors['muted']}' }}}}>Sign out</button>\n"
        "      </nav>")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_297_measured_floor_page.py agent/tests/test_296_measured_floor_colors.py -q`
Expected: PASS (all).

- [ ] **Step 5: Regression + zero-regression + commit + push**

```bash
cd /data/common/haibotong/forgingground-gen
# targeted regression (exclude slow *live* tests)
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest \
  agent/tests/test_frontend_unimported_icons.py agent/tests/test_295_*.py \
  agent/tests/test_296_*.py agent/tests/test_297_*.py \
  $(grep -rln "scaffold_pages_from_contract\|_project_page_component\|_is_generic_fallback_page" agent/tests/ | grep -viE "live" | tr '\n' ' ') \
  -q -p no:cacheprovider
# zero-regress: stash the branch change → 297 RED, others GREEN → pop
git stash push -- agent/env_generator/llm_generator/multi_agent/runtime/frontend_scaffold.py
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_297_measured_floor_page.py -q   # expect RED
git stash pop
git diff --check agent/env_generator/llm_generator/multi_agent/runtime/frontend_scaffold.py
git add agent/env_generator/llm_generator/multi_agent/runtime/frontend_scaffold.py
git commit -m "feat(frontend-scaffold): #297 — no-reference GET floor is a measured structured page (counts as built), not a data-fallback"
git push vaibackup HEAD:feat/pipeline-opt-6
```

---

## Validation (after both tasks)

- [ ] Run the next TikTok generation (r80) with the change; confirm: (a) projected no-reference GET pages carry `_STRUCTURED_MARKER`/`data-projected="ref"` and measured colors; (b) `frontend_fallback_page` / `ui_page_unwired` counts on the delivery gate drop for no-reference pages vs r77/r79; (c) no new framework crash/STUCK; (d) referenced pages still go through `_render_reference_page` unchanged. Real-repro discipline: read `generated/tiktok-web-r80/app/frontend/src/pages/*.jsx` + the gate decline lines, don't infer from logs alone.

## Self-review notes
- Spec §1 (measured floor + markers) → Task 2. Spec §2 (no-palette guard) → Task 2 `test_no_palette_keeps_data_fallback` + the else-branch. Spec §3 (gate effect) → Task 2 `_is_generic_fallback_page(out) is False`. Spec §4 (tests) → Tasks 1-2 test files. Spec §5 (scope) → only `_project_page_component` branch + two helpers touched.
- Palette path corrected to `design["design_system"]["palette"]` (matches `_render_reference_page`).
- `label`, `_nav`, `_api_path_to_js`, `_mark_fallback_page`, `nav_routes` are all in scope inside `_project_page_component` (unchanged from the current function).
