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
    # #954: the identifier may be QUOTED, and schema-qualified. `([a-zA-Z_][\w]*)` allows
    # neither, so `CREATE TABLE IF NOT EXISTS "titles" (` was invisible while
    # `CREATE TABLE IF NOT EXISTS tenants (` matched.
    #
    # Across the corpus: **1132 quoted CREATE TABLEs against 564 unquoted, in 141 runs.** The
    # framework's own spine tables are unquoted and every lane-authored schema quotes, so this
    # check has been comparing the contract against roughly a THIRD of the tables that exist —
    # for the whole history of the project. r154 reports `expected_tables=12, sql_tables=4`, and
    # the four are exactly the spine's (`tenants`, `users`, `oauth_clients`,
    # `oauth_authorization_codes`); its `errors` list is empty because the comparison never saw
    # the other eight.
    #
    # Column parsing already stripped quotes (`first.strip('"')`) — the knowledge was in the
    # function, one loop down, and the table name never got it.
    for match in re.finditer(
            r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?'
            r'(?:"?[a-zA-Z_][\w]*"?\s*\.\s*)?'          # optional schema qualifier
            r'"?([a-zA-Z_][\w]*)"?\s*\((.*?)\);',
            sql_text, re.IGNORECASE | re.DOTALL):
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


_CALL_HEAD_1202ge = re.compile(r"\b(?:request|fetch)\(\s*([`\'\"])(/)")


def _template_path_1202ge(text: str, start: int, quote: str) -> str:
    """#1202ge -- read a call's path literal WITHOUT stopping inside a `${...}`.

    The old pattern was ``(/[^`'\"]+)``: a path is "anything that is not a quote". A
    template literal whose interpolation contains a NESTED template breaks that, and the
    generated api.js writes exactly one::

        fetch(`/api/search${qs ? `?${qs}` : ''}`)

    The capture stopped at the inner backtick and yielded ``/api/search${qs ? `` -- half an
    expression, offered to the delivery gate as a path. r97 delivered its milestone and then
    failed the final gate on it: "Frontend calls unregistered endpoint(s): GET
    /api/search${qs ? ", which nobody can register because it is not a path.

    #1202dn ruled on the consumer side of this and the ruling stands: reconstructing a
    truncated path there would be guessing, and a guess that happens to match a registered
    prefix turns a false positive into a false NEGATIVE that hides real drift. "The defect
    belongs to the extractor." This is the extractor: track `${` depth so the literal is read
    whole, and let the caller see what was actually written.
    """
    depth = 0
    i = start
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if text.startswith("${", i):
            depth += 1
            i += 2
            continue
        if c == "}" and depth:
            depth -= 1
            i += 1
            continue
        if c == quote and depth == 0:
            return text[start:i]
        i += 1
    return ""            # unterminated literal: read nothing rather than half of it


def _path_before_computed_1202ge(raw: str) -> str:
    """#1202ge -- keep the path, drop a computed SUFFIX.

    An interpolation that fills a whole segment is a path param (``/api/users/${id}/follow``
    -> param_agnostic makes it ``/api/users/:p/follow``). One GLUED to a literal
    (``/api/search${qs ...}``) is not part of the path at all -- in the generated code it
    builds a query string, and #494 already established that a query does not define a new
    endpoint. Cut there, keeping the literal prefix.
    """
    i = raw.find("${")
    while i > 0:
        if raw[i - 1] != "/":                 # glued to a literal -> computed suffix
            return raw[:i].rstrip("/") or raw[:i]
        j = raw.find("}", i)
        if j < 0:
            return raw[:i].rstrip("/") or raw[:i]
        i = raw.find("${", j)
    return raw


_UNKNOWN_METHOD_1203C3 = "?"
"""#1203c3 — no options object could be read, so the method is unknown.

NOT "GET". The alignment check matches on PATH and ignores the method, so an unknown one costs
that check nothing; what it buys is an error message that stops telling a lane to register a
method the source contradicts. A call written `request('/x')` with no options at all is a GET by the wrapper's own
default and still reads as one -- this sentinel is ONLY for an options object that starts and
never closes inside the scan window.
"""


def _options_object_1203c3(tail: str, max_len: int = 400):
    """The options literal that follows a call's path, read with BRACE-DEPTH tracking. #1203c3

    The old reading was `re.match(r"[`\'\"]\\s*,\\s*\\{([^{}]*)\\}", tail)`, and `[^{}]*` cannot
    cross a nested brace: `{method:'POST',body:{}}` and
    `{method:'POST',headers:{'Content-Type':'application/json'}}` both failed to match, so the
    method fell back to GET. 791 of the corpus's 1543 extracted calls (51%, 153 runs) carry a
    nested brace, and the invented GET reached lane-facing text 320 times in 17 runs -- five
    endpoints were then registered with it.

    THREE outcomes, and conflating the first two is a defect I wrote and caught by diffing the
    extracted set: `""` when the call has NO options object at all (`request('/x')` -- a GET by
    the wrapper's own default), the object's INNER TEXT when it reads cleanly, and None when an
    options object STARTS but does not terminate inside the window (genuinely unknown). My first
    draft returned None for the first case too, which turned four of r146's plain GET calls into
    `? /api/search`, `? /api/videos/feed` ... -- the opposite of the point.

    Depth tracking mirrors `#1202ge`'s reading of the path literal a few lines above, so this
    function has one style of scanner, not two.
    """
    import re as _re1203c3
    m = _re1203c3.match(r"[`'\"]\s*,\s*\{", tail)
    if not m:
        return ""          # no options object -> the wrapper's default method applies
    depth = 0
    for i in range(m.end() - 1, min(len(tail), max_len)):
        ch = tail[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return tail[m.end():i]
    return None        # started and never closed in the window -> unknown, not GET


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
            # #1202ge: read each literal with `${}` depth tracking so a nested template
            # cannot truncate it mid-expression; then look up the options object the old
            # single regex used to capture in the same pass.
            for hm in _CALL_HEAD_1202ge.finditer(text):
                quote = hm.group(1)
                raw_path = _template_path_1202ge(text, hm.end(1), quote)
                if not raw_path.startswith("/"):
                    continue
                tail = text[hm.end(1) + len(raw_path):hm.end(1) + len(raw_path) + 200]
                # #1203c3: depth-tracked, so `body:{...}` / `headers:{...}` no longer hide
                # the method -- and when there is no readable options object the method is
                # UNKNOWN, not GET. The alignment check is method-tolerant by design (its own
                # comment: a static scan cannot tell a fetch's method from a route path), but
                # its error TEXT prints what it is given, and five endpoints across r133/r135/
                # r138/r146 were registered with the GET this used to invent.
                _opts1203c3 = _options_object_1203c3(tail)
                if _opts1203c3 is None:
                    method = _UNKNOWN_METHOD_1203C3   # an options object we could not close
                else:
                    _m1203c3 = method_re.search(_opts1203c3)
                    method = _m1203c3.group(1).upper() if _m1203c3 else "GET"
                raw_path = _path_before_computed_1202ge(raw_path)
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
