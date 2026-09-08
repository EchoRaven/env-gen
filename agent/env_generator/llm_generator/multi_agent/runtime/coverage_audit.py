"""Coverage audit (Cutover 19): scan for dead endpoints/tables/source-files.

Pure read-side over HubRegistry + filesystem. No mutation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
import logging
from typing import Dict, List, Set, Tuple


_ENTRY_POINT_BASENAMES = {
    "main.tsx", "main.jsx", "main.ts", "main.js",
    "index.tsx", "index.jsx", "index.ts", "index.js",
    "app.tsx", "app.jsx",  # case-insensitive match below
    "server.ts", "server.js", "server.py",
    "app.py", "main.py", "__main__.py",
    "manage.py", "wsgi.py", "asgi.py",
    "vite.config.ts", "vite.config.js",
    "next.config.js", "tailwind.config.js",
    "package.json", "tsconfig.json",
    "docker-compose.yml", "dockerfile",
}

_SOURCE_EXTS = (".tsx", ".jsx", ".ts", ".js", ".py")
_TEST_PATTERNS = (".test.", ".spec.", "_test.", "_spec.", "/tests/", "/__tests__/")

# Captures imports like:
#   import X from './foo';
#   import { X } from "./foo/bar";
#   import('./lazy/foo')
#   require('./foo')              (commonjs)
_JS_IMPORT_RE = re.compile(
    r"""(?x)
    (?:
      (?:from|import)\s+['"]([^'"]+)['"]
      |
      require\(\s*['"]([^'"]+)['"]\s*\)
      |
      import\(\s*['"]([^'"]+)['"]\s*\)
    )
    """
)
# Python imports:
#   from foo import bar
#   from foo.bar import baz
#   from .foo import bar
#   import foo
#   import foo.bar
_PY_IMPORT_RE = re.compile(
    r"""(?xm)
    ^\s*
    (?:
      from\s+(\.*)([\w\.]*)\s+import\s+([\w\.,\s\*]+)
      |
      import\s+([\w\.]+)(?:\s*,\s*([\w\.]+))*
    )
    """
)


@dataclass
class CoverageReport:
    dead_endpoints: List[dict] = field(default_factory=list)
    dead_tables: List[dict] = field(default_factory=list)
    dead_files: List[dict] = field(default_factory=list)
    dead_mcp_tools: List[dict] = field(default_factory=list)
    # MCP servers registered but with zero tools attached. An MCP server
    # without tools can't actually be consumed — it's an incomplete
    # construction.
    empty_mcp_servers: List[dict] = field(default_factory=list)
    # WorkHub ui_pages whose declared path does not exist on disk.
    pages_without_files: List[dict] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not (self.dead_endpoints or self.dead_tables
                     or self.dead_files or self.dead_mcp_tools
                     or self.empty_mcp_servers
                     or self.pages_without_files)

    @property
    def all_dead_paths(self) -> Set[str]:
        out: Set[str] = set()
        for ep in self.dead_endpoints:
            out.add(f"endpoint:{ep['endpoint_id']}")
        for t in self.dead_tables:
            out.add(f"table:{t['table']}")
        for f in self.dead_files:
            out.add(f"file:{f['path']}")
        for mt in self.dead_mcp_tools:
            out.add(f"mcp_tool:{mt['server']}:{mt['tool']}")
        for s in self.empty_mcp_servers:
            out.add(f"mcp_server:{s['server']}")
        for pg in self.pages_without_files:
            out.add(f"page:{pg['page_id']}")
        return out

    def to_dict(self) -> dict:
        return {
            "dead_endpoints": list(self.dead_endpoints),
            "dead_tables": list(self.dead_tables),
            "dead_files": list(self.dead_files),
            "dead_mcp_tools": list(self.dead_mcp_tools),
            "empty_mcp_servers": list(self.empty_mcp_servers),
            "pages_without_files": list(self.pages_without_files),
            "is_clean": self.is_clean,
        }


def scan_dead_endpoints(hub_registry) -> List[dict]:
    registryhub = getattr(hub_registry, "registryhub", None)
    if registryhub is None or not hasattr(registryhub, "get_endpoints"):
        return []
    eps = registryhub.get_endpoints() or {}
    out = []
    for ep_id, ep in eps.items():
        if (ep.get("status") or "defined") != "defined":
            continue  # deprecated/draft don't count as dead
        consumers = registryhub.get_consumers(ep_id) if hasattr(registryhub, "get_consumers") else []
        if not consumers:
            out.append({
                "endpoint_id": ep_id,
                "method": ep.get("method"),
                "path": ep.get("path"),
                "provider": ep.get("provider"),
            })
    return out


# #1199: `scan_dead_tables` DELETED — the detection never existed in practice.
#
# It called a table dead when `get_table_consumers(name)` came back empty, and
# `registryhub_table_consumers.json` holds 0 records in 172 of 172 corpus runs: nothing, agent
# or framework, has ever registered a table consumer, while endpoint consumers number 1145.
# So the scan returned EVERY table every run (r154: twelve "dead" tables over a database
# serving 60 titles, 57 title_genres, 16 episodes...), feeding a delivery blocker.
#
# #957 announced it; #1023b neutralised it (an empty index returns no dead tables, since
# suppressing a 100%-false-positive verdict can only remove false blockers — #566j's cost a
# 75-minute no-deliver abort). That left a scan that can only ever return [], plus 650
# warnings per run saying so. Measured before removing: r26's delivered app has 13 tables and
# NO dead ones — every table is referenced 5+ times — so a repaired detector would find
# nothing here either.
#
# `dead_tables` stays on the report as a permanently empty list: deliverability reads it for
# `dead_count_by_kind` and it has received [] in every run since #1023b, so the arithmetic and
# the report schema are byte-identical. The registration tool comes off the lane bundles in
# the same change — a tool nobody should call is re-sent in every request that offers it.


def _is_test_file(path_str: str) -> bool:
    return any(p in path_str for p in _TEST_PATTERNS)


# #1085: a `<tool>.config.<ext>` file is DISCOVERED BY NAME by its toolchain — nothing
# imports it, so the consumer graph can never see it and it reads "dead" forever. That policy
# is already in _ENTRY_POINT_BASENAMES (vite/next/tailwind configs); the list just never grew,
# and postcss.config.js — the inseparable sibling of the exempt tailwind.config.js in the same
# setup — is flagged in 67 of 83 generated apps, eslint.config.js in 61. That is 128 of the
# 798 findings left after #1084, all false: deleting either file, which is what "dead
# artifact" asks for, breaks the build. Structural rather than two more names, so the next
# tool's config is covered before anyone hits it.
_TOOL_CONFIG_SUFFIXES_1085 = (".config.js", ".config.cjs", ".config.mjs", ".config.ts")


_FRAMEWORK_OWNED_RE_1088 = re.compile(
    r"framework[- ](?:generated|projected|managed)|edits are overwritten", re.I)
# #1088: across the 554 corpus files carrying a framework marker, the marker starts at
# offset 3 — both the MEDIAN and the p95, i.e. line one, every time that matters. 100
# bytes already covers 546/554 (98.6%) and 400 covers 548 (98.9%); the 6 beyond 400 sit
# as deep as offset 2049, which is a mention in the BODY and precisely what a header
# test must not match. 400 keeps a margin for a licence line above the marker without
# reaching body prose.
_FRAMEWORK_HEADER_CHARS_1088 = 400


def _is_framework_owned_1088(path: Path) -> bool:
    """The file's HEADER declares the framework wrote it — so it is not the lane's dead code.

    `backend/schemas.py` is written by backend_skeleton on every scaffold (`w()` is an
    unconditional write_text) and says so in its own first line: *"Framework-generated
    placeholder. The projected handlers return plain dicts; Pydantic response models are not
    required for the standard-CRUD skeleton."* Nothing imports it — exactly as the docstring
    says — so it was reported dead in 66 of 83 generated apps, the largest entry left after
    #1084/#1085, and the remediation told the lane to "remove or wire" it. Removing is futile
    (the next scaffold writes it back) and wiring a module the framework calls unnecessary is
    make-work: #201's wall, for a file the framework creates and declares. Projected frontend
    stubs state it outright — `// framework-generated page … edits are overwritten`.

    Cannot hide lane work: of the 315 corpus dead files whose header declares this, 311 are
    ≤10 lines (untouched stubs), 3 are projected pages, and exactly one exceeds 60 lines —
    r81's reference-structured FYPFeed.jsx, also framework-written.

    HEADER only. A lane file that mentions the phrase further down is not exempt; #222's
    lesson about markers cuts both ways, and liveness stays the import graph's answer for
    everything the lane owns."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return bool(_FRAMEWORK_OWNED_RE_1088.search(fh.read(_FRAMEWORK_HEADER_CHARS_1088)))
    except OSError:
        return False


_ANY_OF_CACHE_1093: Optional[List[List[str]]] = None


def _finish_gate_any_of_groups_1093() -> List[List[str]]:
    """The frontend `any_of` groups the finish gate requires, read from agents_config.yaml.

    Each group is satisfied when AT LEAST ONE member exists, so the SOLE existing member of a
    group cannot be deleted — the lane's next `finish` would fail the required-files gate.
    Read from the config rather than retyped, so the list cannot quietly stop matching what
    the framework actually mandates (the #1090 drift-guard pattern). Cached; never raises."""
    global _ANY_OF_CACHE_1093
    if _ANY_OF_CACHE_1093 is not None:
        return _ANY_OF_CACHE_1093
    groups: List[List[str]] = []
    try:
        cfg = (Path(__file__).resolve().parents[1] / "agents" /
               "agents_config.yaml").read_text(encoding="utf-8", errors="replace")
        for raw in re.findall(r'^\s*-\s*\[(.*?)\]\s*$', cfg, re.M):
            members = [m[len("app/"):] for m in re.findall(r'"([^"]+)"', raw)
                       if m.startswith("app/frontend/")]
            if len(members) >= 2:
                groups.append(members)
    except Exception:
        groups = []
    _ANY_OF_CACHE_1093 = groups
    return groups


def _is_undeletable_gate_file_1093(rel: str, app_root: Path) -> bool:
    """``rel`` is the ONLY member of its finish-gate group that exists, so it cannot be removed.

    r95, generated by today's framework: the lane routes /login to its own LoginModalPage and
    leaves the MANDATED `components/TenantPicker.jsx` with zero references. The coverage audit
    then reports it dead and the remediation says "remove or wire up" — deleting it makes the
    lane's own finish fail. #201's wall, for a file the framework COMPELS the lane to write
    (#1088 covered the ones it writes itself).

    Measured over the corpus, of the 359 dead files left after #1088: 43 are the sole existing
    member of a group (TenantPicker.jsx 40, pages/LoginPage.jsx 3); 38 sit in a group where
    another member also exists, and deleting one of THOSE is legal, so they keep reporting.

    The signal is routed, not lost: #1090 registers the mandated picker and #1089 reports an
    unmounted component with advice the lane can act on."""
    for group in _finish_gate_any_of_groups_1093():
        if rel not in group:
            continue
        try:
            present = [m for m in group if (app_root / m).exists()]
        except OSError:
            return False
        return len(present) == 1
    return False


def _is_entry_point(path: Path) -> bool:
    name = path.name.lower()
    if name.endswith(_TOOL_CONFIG_SUFFIXES_1085):
        return True
    return name in _ENTRY_POINT_BASENAMES


def _collect_source_files(app_root: Path) -> List[Path]:
    files: List[Path] = []
    for p in app_root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix not in _SOURCE_EXTS:
            continue
        rel = str(p.relative_to(app_root))
        # Skip node_modules, .venv, build outputs
        if any(seg in rel for seg in ("node_modules", ".venv", "venv/",
                                       "dist/", "build/", ".next/", "__pycache__/")):
            continue
        files.append(p)
    return files


def _normalize_js_import(source_file: Path, raw: str) -> List[str]:
    """Return possible absolute paths the import could resolve to."""
    if raw.startswith("."):
        base = (source_file.parent / raw).resolve()
        candidates = [base]
        if base.suffix == "":
            for ext in _SOURCE_EXTS:
                candidates.append(base.with_suffix(ext))
            for ext in _SOURCE_EXTS:
                candidates.append(base / f"index{ext}")
        return [str(c) for c in candidates]
    return []  # bare module import — not a local file


def _py_module_candidates(module: str, search_roots: List[Path]) -> List[Path]:
    """Given a dotted module name (e.g. 'routes.feed') and search roots,
    return candidate file paths it could resolve to."""
    parts = module.split(".") if module else []
    if not parts:
        return []
    out: List[Path] = []
    for root in search_roots:
        if not root or not root.is_dir():
            continue
        target = root.joinpath(*parts)
        out.append(target.with_suffix(".py"))
        out.append(target / "__init__.py")
    return out


def _normalize_py_import(source_file: Path, module: str, level: int,
                          imported_names: List[str], app_root: Path) -> List[str]:
    """Translate a Python import to candidate file paths.

    For `from routes.feed import router`, module='routes.feed', level=0,
    imported_names=['router'] — we resolve 'routes.feed' AND
    'routes.feed.router' (in case 'router' is a submodule).

    Search roots: source_file's dir, its ancestors up to app_root, app_root
    itself, and immediate children of app_root (common: app_root/backend
    contains the package).
    """
    src_dir = source_file.parent

    # Build search roots
    search_roots: List[Path] = []
    if level > 0:
        # Relative import: walk up `level` directories from source dir
        base = src_dir
        for _ in range(level - 1):
            base = base.parent
        search_roots.append(base)
    else:
        # Absolute: search from source's dir, walk up to app_root, and
        # also each immediate child of app_root.
        cur = src_dir
        try:
            cur.relative_to(app_root)
            walking = True
        except ValueError:
            walking = False
        if walking:
            while True:
                search_roots.append(cur)
                if cur == app_root:
                    break
                parent = cur.parent
                if parent == cur:
                    break
                cur = parent
        else:
            search_roots.append(src_dir)
        # Also try immediate subdirs of app_root (e.g. app_root/backend,
        # app_root/frontend) so an absolute `from routes.feed import` from
        # app_root/backend/app.py resolves correctly.
        if app_root.is_dir():
            search_roots.append(app_root)
            for child in app_root.iterdir():
                if child.is_dir():
                    search_roots.append(child)

    candidates: List[Path] = []
    if module:
        candidates.extend(_py_module_candidates(module, search_roots))

    # Also: `from pkg import name` — `name` might itself be a submodule
    # (e.g. `from routes import feed` -> feed.py). Try module + name.
    for name in imported_names:
        name = name.strip()
        if not name or name == "*":
            continue
        if module:
            candidates.extend(_py_module_candidates(f"{module}.{name}", search_roots))
        else:
            candidates.extend(_py_module_candidates(name, search_roots))

    # De-dupe; return as string paths
    seen: Set[str] = set()
    out: List[str] = []
    for c in candidates:
        s = str(c)
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _scan_py_imports(text: str) -> List[tuple]:
    # #1081's ratchet caught this docstring the moment it was written: it quotes the regex
    # character class, so it has to be RAW.
    r"""Return list of (level, module, imported_names) tuples from a Python file.

    - `from .foo import bar, baz` -> (1, 'foo', ['bar', 'baz'])
    - `from foo.bar import baz`   -> (0, 'foo.bar', ['baz'])
    - `import foo` / `import foo.bar` -> (0, 'foo', [])  /  (0, 'foo.bar', [])
    - `import foo, bar` -> two tuples.

    #1084: PARSED, not matched. `_PY_IMPORT_RE`'s name class is `[\w\.,\s\*]+` and `\s`
    matches NEWLINES, so one `from x import a, b, c` runs on through every import line after
    it. In the backend main.py every generated app ships, the opening
    `from fastapi import Depends, FastAPI, HTTPException, Query` swallowed
    `from database import ...`, `from auth_dependency import ...` and `import models` into
    its own name list — so those three were never seen as imports and `scan_dead_files`
    called them DEAD, modules the app cannot start without. (A parenthesised multi-line
    import fails the other way: the class excludes `(`, so the names come back empty.)

    Measured over the 83 generated backends: parsing removes 212 of 1010 dead-file findings,
    and every path it removes was false in 100% of the runs it appeared in —
    oauth_routes.py 83/83, auth_dependency.py 58, database.py 53, jwt_manager.py 17. It
    removes nothing true: schemas.py (66 runs) stays flagged and is genuinely imported by
    nobody. Feeds `deliverability_dead_artifacts`, 660 occurrences across 201 run logs.

    The regex stays as the fallback for a file that does not parse — a half-written module
    mid-run is exactly when this audit runs."""
    try:
        import ast as _ast
        tree = _ast.parse(text)
    except Exception:
        pass                      # unparseable → regex fallback below
    else:
        parsed: List[tuple] = []
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Import):
                for alias in node.names:
                    parsed.append((0, alias.name, []))
            elif isinstance(node, _ast.ImportFrom):
                parsed.append((node.level or 0, node.module or "",
                               [a.name for a in node.names]))
        return parsed
    out: List[tuple] = []
    for m in _PY_IMPORT_RE.finditer(text):
        dots, mod_from, names_str, mod_imp1, mod_imp2 = (
            m.group(1), m.group(2), m.group(3), m.group(4), m.group(5))
        if mod_from is not None or dots:
            level = len(dots or "")
            mod = (mod_from or "").strip()
            names = []
            if names_str:
                # Strip "as" aliases and split by comma
                for tok in names_str.split(","):
                    tok = tok.strip()
                    if not tok:
                        continue
                    # Strip "X as Y" -> "X"
                    base = tok.split(" as ")[0].strip()
                    if base:
                        names.append(base)
            out.append((level, mod, names))
        elif mod_imp1:
            out.append((0, mod_imp1, []))
            if mod_imp2:
                out.append((0, mod_imp2, []))
    return out


def scan_dead_files(app_root: Path) -> List[dict]:
    app_root = Path(app_root)
    if not app_root.exists() or not app_root.is_dir():
        return []
    files = _collect_source_files(app_root)
    if not files:
        return []
    file_set = {str(f.resolve()) for f in files}

    # Build consumer graph: file -> set of files it imports
    imported: Set[str] = set()
    for src in files:
        try:
            text = src.read_text(errors="replace")
        except OSError:
            continue
        if src.suffix == ".py":
            for level, mod, names in _scan_py_imports(text):
                for cand in _normalize_py_import(src, mod, level, names, app_root):
                    if cand in file_set:
                        imported.add(cand)
                        # Implicit: when a module inside a package is imported,
                        # every package's __init__.py up to app_root is loaded.
                        cand_path = Path(cand)
                        parent = cand_path.parent
                        while True:
                            init = parent / "__init__.py"
                            init_str = str(init)
                            if init_str in file_set:
                                imported.add(init_str)
                            try:
                                if parent.resolve() == app_root.resolve():
                                    break
                            except OSError:
                                break
                            new_parent = parent.parent
                            if new_parent == parent:
                                break
                            parent = new_parent
        else:
            for m in _JS_IMPORT_RE.finditer(text):
                raw = m.group(1) or m.group(2) or m.group(3)
                for cand in _normalize_js_import(src, raw):
                    if cand in file_set:
                        imported.add(cand)

    # A test file ALWAYS counts as a valid consumer of whatever it imports.
    # But test files themselves shouldn't be flagged dead — they're entry-leaf nodes.
    out: List[dict] = []
    for src in files:
        abs_str = str(src.resolve())
        rel_str = str(src.relative_to(app_root))
        if _is_test_file(rel_str) or _is_test_file(abs_str):
            continue  # tests are never flagged dead
        if _is_entry_point(src):
            continue
        if _is_framework_owned_1088(src):
            continue   # #1088: the framework wrote it and rewrites it — not the lane's to remove
        if _is_undeletable_gate_file_1093(rel_str, app_root):
            continue   # #1093: the finish gate requires this exact file to exist
        if abs_str in imported:
            continue
        out.append({"path": rel_str})
    return out


def scan_dead_mcp_tools(hub_registry) -> List[dict]:
    mcp_registry = getattr(hub_registry, "mcp_registry", None)
    if mcp_registry is None or not hasattr(mcp_registry, "get_mcp_tools"):
        return []
    tools = mcp_registry.get_mcp_tools() or {}
    out = []
    for key, tool in tools.items():
        if (tool.get("status") or "defined") != "defined":
            continue
        server = tool.get("server_name")
        tool_name = tool.get("tool_name")
        consumers = mcp_registry.get_mcp_consumers(server_name=server, tool_name=tool_name)
        if not consumers:
            out.append({
                "server": server,
                "tool": tool_name,
                "provider": tool.get("provider"),
            })
    return out


def _page_file_exists_1202hc(app_root, rel) -> bool:
    """Does a ui_page's declared `path` point at a real file under EITHER base?

    #1202fn had to pick one base for this scan and chose the OUTPUT ROOT, which is right for
    most of the corpus and wrong for the rest. Measured over every registered page on this
    machine: 1757 resolve under the output root only, 101 under the app tree only, 8 under
    both, and 80 under neither. r102 is entirely in the 101 -- every page registered as
    `frontend/src/pages/X.jsx`, every file at `app/frontend/src/pages/X.jsx` -- so all eleven
    read as missing and the lane was told to MOVE files that were already correct.

    Both conventions are present in the data, so accepting either is not a guess. A page is
    still reported when it resolves under NEITHER, which is the 80 genuine cases.
    """
    try:
        rel_p = Path(str(rel))
    except Exception:
        return False
    if not str(rel or "").strip():
        return False
    exts = (".tsx", ".jsx", ".ts", ".js", ".vue", ".svelte")
    roots = [Path(app_root)]
    _app = Path(app_root) / "app"
    if _app.is_dir():
        roots.append(_app)
    for root in roots:
        cand = rel_p if rel_p.is_absolute() else (root / rel_p)
        try:
            if cand.exists():
                return True
            for ext in exts:
                if cand.with_suffix(ext).exists():
                    return True
        except Exception:
            continue
    return False


def scan_pages_without_files(hub_registry, app_root) -> List[dict]:
    """Return RegistryHub ui_pages whose declared ``path`` does not point at
    an existing file under ``app_root``.

    A page registration without a corresponding source file is a lie —
    typical when an agent registers a ui_page first and never follows
    through on the implementation. Each returned entry carries
    enough context for the caller to either fix the path or remove the
    page.

    Pages without a ``path`` field at all are silently ignored — the
    schema allows path-less placeholders during design phase.
    """
    registryhub = getattr(hub_registry, "registryhub", None)
    if registryhub is None:
        return []
    app_root = Path(app_root)
    try:
        pages = registryhub.list_ui_pages() or {}
    except Exception:
        return []
    out: List[dict] = []
    for page_key, page in pages.items():
        path = page.get("path")
        if not path:
            continue
        # Resolve relative to app_root. If the page declared an absolute
        # path, take it as-is. Treat *both* the literal path and the
        # path-with-each-source-extension as acceptable (covers the
        # frontend convention of registering ``Login`` and shipping
        # ``Login.tsx``).
        # #1202hc: try the app tree as well as the output root -- both conventions exist.
        if _page_file_exists_1202hc(app_root, path):
            continue
        p_abs = Path(path)
        if not p_abs.is_absolute():
            p_abs = app_root / p_abs
        if p_abs.exists():
            continue
        # Try common source-file extensions
        found = False
        for ext in (".tsx", ".jsx", ".ts", ".js", ".vue", ".svelte"):
            if p_abs.with_suffix(ext).exists():
                found = True
                break
        if found:
            continue
        out.append({
            "page_id": page.get("id") or page_key,
            "title": page.get("name"),
            "declared_path": path,
            "owned_by": page.get("_updated_by") or page.get("created_by"),
        })
    return out


def scan_empty_mcp_servers(hub_registry) -> List[dict]:
    """Return MCP servers that have **zero** registered tools.

    A server entry on its own is meaningless — the agent has to also
    register at least one tool before the construction is consumable.
    Catches the "I registered the server then moved on" mistake that's
    easy to make on a long-context run.
    """
    mcp_registry = getattr(hub_registry, "mcp_registry", None)
    if mcp_registry is None or not hasattr(mcp_registry, "get_mcp_servers"):
        return []
    servers = mcp_registry.get_mcp_servers() or {}
    tools = mcp_registry.get_mcp_tools() or {}
    tools_by_server: Dict[str, int] = {}
    for tool in tools.values():
        s = tool.get("server_name")
        if not s:
            continue
        tools_by_server[s] = tools_by_server.get(s, 0) + 1
    out = []
    for name, srv in servers.items():
        if tools_by_server.get(name, 0) > 0:
            continue
        out.append({
            "server": name,
            "provider": srv.get("provider"),
            "status": srv.get("status"),
        })
    return out


def _coverage_bases_1202fn(app_root: Path) -> Tuple[Path, Path]:
    """#1202fn -- return ``(tree_root, decl_root)``: the two DIFFERENT bases the scans
    below need, derived from whichever one the caller happened to hand us.

    ``compute_coverage`` took a single ``app_root`` and gave it to both scans, but they
    do not want the same directory:

    * ``scan_dead_files`` walks a tree, so it wants the APP TREE. Given the output root
      it also walks ``worktrees/`` -- five lane copies of the same app.
    * ``scan_pages_without_files`` resolves ui_page ``path`` values, and those are
      declared relative to the OUTPUT ROOT (``app/frontend/src/pages/X.jsx``). Given the
      app dir it joins the ``app/`` segment twice.

    So each of the two callers was correct about one scan and wrong about the other, and
    neither could fix it from its side. Measured on tiktok-r96, same hub, same tree:

        base                    pages_without_files      dead_files
        <root>      (coverage)            0  correct     50  (25 phantoms in worktrees/)
        <root>/app  (delivery)           19  ALL FALSE   25  correct

    The 19 was not cosmetic: ``deliverability_check`` publishes it as a delivery blocker,
    so the gate reported "N pages_without_files for the declared app/frontend/src/pages/*"
    against pages whose files were all present -- permanently, since re-running the scan
    reproduces it. r96 spent its last ticks being told delivery was blocked by this while
    ``coverage_audit_check`` -- the same scan over the same hub, from the other caller --
    reported clean in the very same message.

    Ambiguous input (neither layout recognisable, e.g. a bare tmp dir in a unit test)
    returns the argument for both, i.e. exactly the previous behaviour: we only ever
    override a base we can positively identify.
    """
    p = Path(app_root)
    _is_tree = lambda d: (d / "backend").is_dir() or (d / "frontend").is_dir()
    cand = p / "app"
    if cand.is_dir() and _is_tree(cand):        # given the OUTPUT ROOT
        return cand, p
    if p.name == "app" and _is_tree(p):         # given the APP TREE
        return p, p.parent
    return p, p


def compute_coverage(hub_registry, app_root) -> CoverageReport:
    tree_root, decl_root = _coverage_bases_1202fn(Path(app_root))
    return CoverageReport(
        dead_endpoints=scan_dead_endpoints(hub_registry),
        dead_tables=[],   # #1199: detection removed; see the note above
        dead_files=scan_dead_files(tree_root),
        dead_mcp_tools=scan_dead_mcp_tools(hub_registry),
        empty_mcp_servers=scan_empty_mcp_servers(hub_registry),
        pages_without_files=scan_pages_without_files(hub_registry, decl_root),
    )


__all__ = [
    "CoverageReport", "compute_coverage",
    "scan_dead_endpoints", "scan_dead_files",
    "scan_dead_mcp_tools", "scan_empty_mcp_servers",
    "scan_pages_without_files",
]
