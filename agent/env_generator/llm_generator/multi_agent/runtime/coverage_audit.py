"""Coverage audit (Cutover 19): scan for dead endpoints/tables/source-files.

Pure read-side over HubRegistry + filesystem. No mutation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set


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


def scan_dead_tables(hub_registry) -> List[dict]:
    schema_hub = getattr(hub_registry, "schema_hub", None)
    if schema_hub is None or not hasattr(schema_hub, "list_tables"):
        return []
    tables = schema_hub.list_tables() or {}
    # PR 5 Q3: ``get_table_consumers(table_name)`` is the same shape as
    # ``RegistryHub.get_consumers(endpoint_id)`` — iterate tables and ask
    # SchemaHub directly instead of reaching into the private store.
    out = []
    for name, table in tables.items():
        if schema_hub.get_table_consumers(name):
            continue
        out.append({"table": name, "provider": table.get("provider")})
    return out


def _is_test_file(path_str: str) -> bool:
    return any(p in path_str for p in _TEST_PATTERNS)


def _is_entry_point(path: Path) -> bool:
    return path.name.lower() in _ENTRY_POINT_BASENAMES


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
    """Return list of (level, module, imported_names) tuples from a Python file.

    - `from .foo import bar, baz` -> (1, 'foo', ['bar', 'baz'])
    - `from foo.bar import baz`   -> (0, 'foo.bar', ['baz'])
    - `import foo` / `import foo.bar` -> (0, 'foo', [])  /  (0, 'foo.bar', [])
    - `import foo, bar` -> two tuples.
    """
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


def compute_coverage(hub_registry, app_root) -> CoverageReport:
    app_root = Path(app_root)
    return CoverageReport(
        dead_endpoints=scan_dead_endpoints(hub_registry),
        dead_tables=scan_dead_tables(hub_registry),
        dead_files=scan_dead_files(app_root),
        dead_mcp_tools=scan_dead_mcp_tools(hub_registry),
        empty_mcp_servers=scan_empty_mcp_servers(hub_registry),
        pages_without_files=scan_pages_without_files(hub_registry, app_root),
    )


__all__ = [
    "CoverageReport", "compute_coverage",
    "scan_dead_endpoints", "scan_dead_tables", "scan_dead_files",
    "scan_dead_mcp_tools", "scan_empty_mcp_servers",
    "scan_pages_without_files",
]
