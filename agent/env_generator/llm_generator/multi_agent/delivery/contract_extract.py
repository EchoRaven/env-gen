"""
Contract extraction for the delivery gate — reverse-engineers the generated app's
endpoints / DB tables / SQL refs / pages from source so they can be checked against
the design spec (contract alignment).

STACK ASSUMPTION (important): these extractors are hardcoded to the generator's
default output stack:
  - Backend: Express (``backend/src/server.js`` mounts + ``backend/src/routes/*.js``
    with ``router.<method>(...)``)
  - Database: PostgreSQL DDL (``CREATE TABLE ...``) under the database dir
  - SQL refs: SQL embedded in JS string/template literals

If the generated stack ever changes (different backend framework, non-SQL store,
different file layout), these become silently wrong (a real route reads as
"missing endpoint"). When that happens, make these pluggable per target stack
rather than editing the regexes in place. This module is the single place that
encodes that assumption.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Set


def normalize_api_path(path: str) -> str:
    if not path:
        return ""
    path = re.sub(r"//+", "/", path)
    path = re.sub(r"\{([a-zA-Z_][\w]*)\}", r":\1", path)
    if not path.startswith("/"):
        path = "/" + path
    return path.rstrip("/") or "/"


def extract_sql_tables(db_dir: Path) -> Dict[str, set]:
    """Tables + columns from Postgres CREATE TABLE statements under db_dir."""
    tables: Dict[str, set] = {}
    if not db_dir.exists():
        return tables
    sql_text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in db_dir.glob("**/*.sql"))
    for match in re.finditer(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z_][\w]*)\s*\((.*?)\);", sql_text, re.IGNORECASE | re.DOTALL):
        table = match.group(1)
        body = match.group(2)
        columns = set()
        for line in body.splitlines():
            stripped = line.strip().strip(",")
            if not stripped or stripped.startswith("--"):
                continue
            first = stripped.split()[0].strip('"')
            if first.upper() in {"CONSTRAINT", "PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "INDEX"}:
                continue
            columns.add(first)
        tables[table] = columns
    return tables


def extract_backend_sql_refs(backend_dir: Path) -> Dict[str, set]:
    """Table/column references found in SQL embedded in backend JS literals."""
    refs: Dict[str, set] = {}
    if not backend_dir.exists():
        return refs
    sql_context = re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE)\s+([a-zA-Z_][\w]*)\b", re.IGNORECASE)
    alias_context = re.compile(r"\b(?:FROM|JOIN)\s+([a-zA-Z_][\w]*)\s+(?:AS\s+)?([a-zA-Z_][\w]*)\b", re.IGNORECASE)
    col_ref = re.compile(r"\b([a-zA-Z_][\w]*)\.([a-zA-Z_][\w]*)\b")
    for path in backend_dir.glob("**/*.js"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        sql_chunks = [
            chunk
            for chunk in re.findall(r"`([^`]*(?:SELECT|INSERT|UPDATE|DELETE|FROM|JOIN)[^`]*)`", text, re.IGNORECASE | re.DOTALL)
        ]
        sql_chunks.extend(
            chunk
            for chunk in re.findall(r"['\"]([^'\"]*(?:SELECT|INSERT|UPDATE|DELETE|FROM|JOIN)[^'\"]*)['\"]", text, re.IGNORECASE | re.DOTALL)
        )
        if not sql_chunks:
            continue
        sql_text = "\n".join(sql_chunks)
        aliases: Dict[str, str] = {}
        for table, alias in alias_context.findall(sql_text):
            aliases[alias] = table
        for table in sql_context.findall(sql_text):
            refs.setdefault(table, set())
        for alias, column in col_ref.findall(sql_text):
            table = aliases.get(alias, alias)
            refs.setdefault(table, set()).add(column)
    return refs


def param_agnostic(method_path: str) -> str:
    """Normalize a 'METHOD /path' so path-param NAME + form ({id} / :id) don't
    matter for matching: every param segment becomes ':p'. Used to compare
    registered endpoints vs implemented routes vs frontend calls."""
    parts = method_path.split(" ", 1)
    if len(parts) != 2:
        return method_path
    method, path = parts[0].upper(), normalize_api_path(parts[1])
    # Segment-based normalization (robust): a path PARAM appears in many forms a
    # regex-per-form misses — ``{id}`` / ``:id`` / ``${id}`` and, from JS template
    # literals, ``${encodeURIComponent(postId)}`` (which the frontend extractor
    # leaves as ``:encodeURIComponent(postId)`` — the old ``:[A-Za-z_]\w*`` regex
    # only ate ``:encodeURIComponent`` and left ``:p(postId)`` → false "unregistered
    # endpoint"). Treat any segment that is NOT a plain literal path word as ``:p``.
    segs = []
    for s in path.split("/"):
        if s == "" or re.fullmatch(r"[A-Za-z0-9._~-]+", s):
            segs.append(s)
        else:
            segs.append(":p")
    return f"{method} {'/'.join(segs)}"


def detect_backend_stack(backend_dir: Path) -> str:
    """Return 'fastapi' | 'express' | 'unknown' from the generated backend."""
    if not backend_dir.exists():
        return "unknown"
    main_py = backend_dir / "main.py"
    if main_py.exists():
        t = main_py.read_text(encoding="utf-8", errors="ignore").lower()
        if "fastapi" in t:
            return "fastapi"
    if (backend_dir / "src" / "server.js").exists():
        return "express"
    for p in backend_dir.glob("**/*.py"):
        if re.search(r"@\w+\.(get|post|put|patch|delete)\(", p.read_text(encoding="utf-8", errors="ignore")):
            return "fastapi"
    if (backend_dir / "package.json").exists():
        return "express"
    return "unknown"


def _extract_fastapi_routes(backend_dir: Path) -> Set[str]:
    """HTTP routes from FastAPI decorators (@app.get('/p') / @router.post('/p'))."""
    routes: Set[str] = set()
    for path in backend_dir.glob("**/*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for method, route in re.findall(
            r"@\w+\.(get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]", text
        ):
            routes.add(f"{method.upper()} {normalize_api_path(route)}")
    return routes


def _extract_express_routes(backend_dir: Path) -> Set[str]:
    """HTTP routes from an Express backend (server.js mounts + routes/*.js)."""
    routes: Set[str] = set()
    server_text = ""
    server_path = backend_dir / "src/server.js"
    if server_path.exists():
        server_text = server_path.read_text(encoding="utf-8", errors="ignore")

    mount_by_route_file: Dict[str, str] = {}
    for mount, var in re.findall(r"app\.use\(['\"]([^'\"]+)['\"],\s*([a-zA-Z_][\w]*)\)", server_text):
        import_match = re.search(rf"import\s+{re.escape(var)}\s+from\s+['\"]([^'\"]+)['\"]", server_text)
        if import_match:
            imported = import_match.group(1)
            route_file = Path(imported).name.replace(".js", "")
            mount_by_route_file[route_file] = mount.rstrip("/")

    for path in (backend_dir / "src/routes").glob("*.js"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        mount = mount_by_route_file.get(path.stem, f"/api/{path.stem}")
        for method, route in re.findall(r"router\.(get|post|put|patch|delete)\(['\"]([^'\"]+)['\"]", text):
            routes.add(f"{method.upper()} {normalize_api_path(mount + '/' + route.lstrip('/'))}")
    return routes


def extract_backend_routes(backend_dir: Path) -> set:
    """HTTP routes from the generated backend, dispatched by detected stack.
    (Was Express-only; now stack-pluggable — FastAPI is the retarget default.)"""
    if not backend_dir.exists():
        return set()
    stack = detect_backend_stack(backend_dir)
    if stack == "fastapi":
        return _extract_fastapi_routes(backend_dir)
    if stack == "express":
        return _extract_express_routes(backend_dir)
    # unknown → union both rather than silently miss real routes
    return _extract_fastapi_routes(backend_dir) | _extract_express_routes(backend_dir)


def extract_frontend_calls(frontend_dir: Path) -> Set[str]:
    """METHOD+path API calls extracted from generated frontend source.

    Recognizes the generated ``api.js`` ``request('<path>', {method})`` wrapper
    and raw ``fetch('<path>', {method})`` with a literal leading-'/' path.
    Template params ``${id}`` become ``:id`` (normalized to ':p' for matching).
    Dynamic/computed paths are skipped (best-effort, like the other extractors)."""
    calls: Set[str] = set()
    if not frontend_dir.exists():
        return calls
    call_re = re.compile(
        r"\b(?:request|fetch)\(\s*[`'\"](/[^`'\"]+)[`'\"]\s*(?:,\s*\{([^{}]*)\})?",
    )
    method_re = re.compile(r"method\s*:\s*['\"](\w+)['\"]")
    for ext in ("js", "jsx", "ts", "tsx"):
        for path in frontend_dir.glob(f"**/*.{ext}"):
            if "node_modules" in str(path):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for raw_path, opts in call_re.findall(text):
                m = method_re.search(opts or "")
                method = (m.group(1) if m else "GET").upper()
                p = re.sub(r"\$\{([^}]+)\}", r":\1", raw_path)   # ${id} -> :id (param_agnostic normalizes at match)
                calls.add(f"{method} {normalize_api_path(p)}")
    return calls


def extract_api_endpoints(spec: Dict[str, Any]) -> set:
    """METHOD+path endpoints declared in a design spec."""
    endpoints: Set[str] = set()
    for ep in spec.get("endpoints", []) if isinstance(spec.get("endpoints"), list) else []:
        if not isinstance(ep, dict):
            continue
        method = str(ep.get("method", "")).upper().strip()
        path = normalize_api_path(str(ep.get("path", "")).strip())
        if method and path:
            endpoints.add(f"{method} {path}")
    return endpoints


def extract_spec_pages(spec: Dict[str, Any]) -> set:
    """Page names declared in a design spec (dict or list form)."""
    pages: Set[str] = set()
    raw_pages = spec.get("pages")
    if isinstance(raw_pages, dict):
        iterable = raw_pages.items()
    elif isinstance(raw_pages, list):
        iterable = ((p.get("name") or p.get("id") or p.get("route") or p.get("path"), p) for p in raw_pages if isinstance(p, dict))
    else:
        iterable = []
    for raw_name, page in iterable:
        name = str(raw_name or "").strip()
        if name and isinstance(page, dict):
            pages.add(name)
    return pages
