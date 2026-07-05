"""Frontend api.js export-completion — FIX #37.

The frontend lane writes ``src/services/api.js`` (the API client) AND the
components that import from it INDEPENDENTLY, so they drift on names: e.g. a
component does ``import { registerAccount }`` while api.js exports ``register``.
Rollup then fails the build ("registerAccount is not exported by api.js") → the
frontend docker image won't build → ``docker compose up --build`` fails →
api_smoke docker_up FAIL → NO DELIVERY, even though the backend is perfect.

This deterministically reconciles them — the frontend analog of the DDL projector
([[feedback_envgen_api_consistency_by_construction]]): every name a component
imports from api.js MUST resolve. For each missing export, alias it to the
best-matching existing export (name-normalized), or — if no match — emit a
throwing stub so the BUILD always succeeds (one unimplemented call beats a dead
app that won't build at all).
"""

import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

_EXPORT_RE = re.compile(
    r"export\s+(?:async\s+)?(?:function|const|let|var)\s+([A-Za-z0-9_$]+)"
)
_EXPORT_BRACE_RE = re.compile(r"export\s*\{([^}]*)\}")
_IMPORT_API_RE = re.compile(
    r"import\s*\{([^}]*)\}\s*from\s*['\"][^'\"]*services/api(?:\.js)?['\"]"
)
_FRONT_EXTS = (".js", ".jsx", ".ts", ".tsx", ".mjs")
_STOPWORDS = ("account", "user", "users", "current", "data", "info",
              "details", "request", "api", "async", "the")

# ── ESCAPED-BACKTICK repair (2026-06-30, outlook run-13) ─────────────────────
# The frontend LLM lane intermittently emits template-literal DELIMITERS as
# ESCAPED backticks — ``className={\`...\`}`` instead of ``className={`...`}`` —
# which is NOT valid JSX/JS (a ``\``` is only legal INSIDE a template string as a
# literal backtick), so esbuild/Vite fails the transform ("Invalid or unexpected
# token") → ``npm run build`` fails → api_smoke docker_up FAIL → the validation
# loop WEDGES, and the lane clears it one file at a time over many cycles (run-13:
# MessageRow.jsx → FolderList.jsx → Tabs.jsx → InboxPage.jsx, same error each round).
# Deterministically un-escape a backslash-backtick ONLY when it sits in a template-
# literal DELIMITER position — right after a JS/JSX structural token (OPEN) or right
# before a structural close (CLOSE) — so a legitimately-escaped backtick inside
# displayed TEXT (ordinary characters on both sides) is LEFT UNTOUCHED. Env-agnostic,
# best-effort, idempotent. Complements the safe-icon/api.js build-integrity repairs.
_TICK_OPEN_RE = re.compile(r"((?:[={(\[,:?]|=>|&&|\|\||\?\?|\breturn)\s*)\\(?=`)")
_TICK_CLOSE_RE = re.compile(r"\\(?=`[)}\];,])")

# Same escaped-character damage family (outlook run-29, 2026-07-01): the lane emitted a
# LITERAL ``\n`` between statements — ``}\n\nexport function CalendarsPage() {`` — a
# backslash outside a string is a JS syntax error → vite build fails → docker_up WEDGES
# (run-29: 6/6 validation attempts, STUCK escalation; the lane never fixed the file).
# Un-escape ONLY at a STATEMENT BOUNDARY: after ``}``/``;``, before a top-level keyword
# (export/import/function/const/let/var/class/async) or a comment. A legit ``\n`` inside
# a string (``split('\n')``, ``"a\nb"``) never sits in that shape — the char after the
# ``\n`` run is a quote/paren, not a declaration keyword — so it is left untouched (and
# inside a TEMPLATE literal a real newline is semantically identical anyway).
_LITNL_BOUNDARY_RE = re.compile(
    r"([};])(?:\\n)+(?=\s*(?:export\b|import\b|function\b|const\b|let\b|var\b|class\b"
    r"|async\b|//|/\*))")


def _unescape_statement_boundary_newlines(src: str) -> str:
    """Replace a literal ``\\n`` run at a statement boundary with real newlines."""
    if "\\n" not in src:
        return src
    return _LITNL_BOUNDARY_RE.sub(lambda m: m.group(1) + "\n\n", src)


# Third shape of the same damage family (outlook run-36, 2026-07-02): a literal ``\n``
# INSIDE a template-literal interpolation — ``className={`... ${\n cond ? 'a' : 'b'\n}`}``.
# The ``${...}`` region is EXPRESSION context, so the backslash is a hard esbuild syntax
# error ("Syntax error \"n\"") → vite build fails → docker_up STUCK-abort (run-36 died
# in 7 cycles on MessageList.jsx:94). Trigger precisely on ``${\n``; on such a line,
# un-escape every ``\n`` that is NOT inside a single/double-quoted substring (a quoted
# ``'\n'`` — e.g. split('\n') — is legitimate data and stays).
_TPL_EXPR_NL_TRIGGER = re.compile(r"\$\{\\n")


def _unescape_template_expr_newlines(src: str) -> str:
    if not _TPL_EXPR_NL_TRIGGER.search(src):
        return src
    out_lines: List[str] = []
    for line in src.split("\n"):
        if not _TPL_EXPR_NL_TRIGGER.search(line):
            out_lines.append(line)
            continue
        res: List[str] = []
        i, n = 0, len(line)
        quote = None
        while i < n:
            ch = line[i]
            if quote:
                if ch == "\\" and i + 1 < n:        # escape inside a quoted string
                    res.append(line[i:i + 2]); i += 2; continue
                if ch == quote:
                    quote = None
                res.append(ch); i += 1; continue
            if ch in ("'", '"'):
                quote = ch; res.append(ch); i += 1; continue
            if ch == "\\" and i + 1 < n and line[i + 1] == "n":
                res.append("\n"); i += 2; continue   # code context → real newline
            res.append(ch); i += 1
        out_lines.append("".join(res))
    return "\n".join(out_lines)


def _unescape_delimiter_backticks(src: str) -> str:
    """Un-escape template-literal delimiter backticks. The OPEN/CLOSE regexes are used as a
    per-LINE malformation DETECTOR: a line carrying a ``\``` in a delimiter position — right
    after a structural token (``{ ( [ = , : ? => && || ?? return``) or right before a
    structural close (``) } ] ; ,``) — is the lane's escaped-delimiter bug, so every
    ``\``` on THAT line is un-escaped (this also catches a mid-expression delimiter like a
    ternary branch ``? \`a\` : \`b\```). A line whose only ``\``` sits between ordinary text
    characters (a legitimately-escaped literal backtick) matches NEITHER detector and is
    left untouched — the safety property."""
    if "\\`" not in src:
        return src
    out = []
    for line in src.splitlines(keepends=True):
        if "\\`" in line and (_TICK_OPEN_RE.search(line) or _TICK_CLOSE_RE.search(line)):
            line = line.replace("\\`", "`")
        out.append(line)
    return "".join(out)


# escaped JSX ATTRIBUTE double-quotes (outlook run-57, live): the lane JSON-escaped a
# whole JSX file, emitting ``className=\"min-h-screen bg-[#fff]\"`` instead of
# ``className="..."`` → esbuild/Vite "Unexpected token" → npm run build fails → docker_up
# wedged 7 cycles → STUCK-ABORT (the lane repaired it ONE FILE AT A TIME, too slow for the
# budget). PRECISE + SAFE: only ``identifier=\"value\"`` where the value carries no other
# quote or backslash (a Tailwind/class string). A legitimately-escaped quote INSIDE a
# string literal (its value would contain a ``\`` or ``"``) does NOT match ``[^"\\]*`` and
# is left untouched — the same safety property as the backtick repair.
_JSX_ESCQ_RE = re.compile(r'([A-Za-z_][\w-]*=)\\"([^"\\]*)\\"')


def _unescape_jsx_attr_quotes(src: str) -> str:
    if '\\"' not in src:
        return src
    return _JSX_ESCQ_RE.sub(r'\1"\2"', src)


def repair_frontend_escaped_backticks(frontend_dir) -> Dict[str, object]:
    """Un-escape template-literal delimiter backticks, escaped newlines, AND escaped JSX
    attribute quotes across the frontend source so an LLM-emitted ``className={\`...\`}`` /
    ``className=\"...\"`` can't break the esbuild/Vite build (and thus wedge the api_smoke
    docker_up gate). Deterministic + best-effort: only touches a file that actually contains
    an escape artifact, and only rewrites delimiter/attribute positions. Returns
    ``{"repaired": [relative paths]}``."""
    repaired: List[str] = []
    try:
        src_dir = Path(frontend_dir) / "src"
        if not src_dir.is_dir():
            return {"repaired": repaired}
        for f in src_dir.rglob("*"):
            if f.suffix not in _FRONT_EXTS or not f.is_file():
                continue
            try:
                txt = f.read_text(encoding="utf-8")
            except Exception:
                continue
            # fast path: no escape damage anywhere
            if "\\`" not in txt and "\\n" not in txt and '\\"' not in txt:
                continue
            fixed = _unescape_delimiter_backticks(txt)
            fixed = _unescape_statement_boundary_newlines(fixed)
            fixed = _unescape_template_expr_newlines(fixed)
            fixed = _unescape_jsx_attr_quotes(fixed)
            if fixed != txt:
                try:
                    f.write_text(fixed, encoding="utf-8")
                    repaired.append(str(f.relative_to(src_dir)))
                except Exception:
                    pass
    except Exception:
        pass
    return {"repaired": repaired}


# ── UNIMPORTED-JSX-IDENTIFIER repair (outlook run-33, 2026-07-02) ─────────────
# The lane uses an icon in JSX (`<Mail className=…/>`) without importing it. The BUILD
# passes — a free JSX identifier compiles to a runtime global lookup — and the page then
# CRASHES at render (`ReferenceError: Mail is not defined` → blank page + console error →
# browser-gate deferral churn; run-33 M1 burned 3 re-test cycles on messages/events pages).
# Deterministic repair: add every capitalized JSX tag that is neither imported nor locally
# defined to a `lucide-react` import. The safe-icon Vite plugin routes ALL lucide imports
# through its virtual module (real icon when it exists, placeholder SVG otherwise), so this
# is CRASH-PROOF by construction: a real icon renders, a wrongly-caught name degrades to a
# visible placeholder the visual gate can flag — strictly better than a dead page.
_JSX_TAG_RE = re.compile(r"<([A-Z][A-Za-z0-9_]*)[\s/>]")
_IMPORT_NAMES_RE = re.compile(r"import\s+(?:([A-Za-z_$][\w$]*)\s*,?\s*)?(?:\{([^}]*)\})?\s*from", re.S)
_LOCAL_DEF_RE = re.compile(r"(?:^|\n)\s*(?:export\s+)?(?:default\s+)?"
                           r"(?:function|class|const|let|var)\s+([A-Z][A-Za-z0-9_]*)")
_REACT_BUILTINS = {"Fragment", "StrictMode", "Suspense", "Profiler", "ErrorBoundary"}


def _unimported_jsx_tags(src: str) -> List[str]:
    used = set(_JSX_TAG_RE.findall(src))
    if not used:
        return []
    known: Set[str] = set(_REACT_BUILTINS)
    for m in _IMPORT_NAMES_RE.finditer(src):
        if m.group(1):
            known.add(m.group(1).strip())
        for part in (m.group(2) or "").split(","):
            part = part.strip()
            if part:
                known.add(part.split(" as ")[-1].strip())  # the LOCAL binding
    known.update(_LOCAL_DEF_RE.findall(src))
    return sorted(used - known)


def repair_frontend_unimported_icons(frontend_dir) -> Dict[str, object]:
    """Import every capitalized JSX tag that is used but neither imported nor locally
    defined, via lucide-react (safe-icon plugin guarantees no crash either way).
    Idempotent; returns {"repaired": [relpath, ...]}."""
    repaired: List[str] = []
    try:
        src_dir = Path(frontend_dir) / "src"
        if not src_dir.is_dir():
            return {"repaired": repaired}
        for f in src_dir.rglob("*"):
            if f.suffix not in (".jsx", ".tsx") or not f.is_file():
                continue
            try:
                txt = f.read_text(encoding="utf-8")
            except Exception:
                continue
            missing = _unimported_jsx_tags(txt)
            if not missing:
                continue
            add = "import { " + ", ".join(missing) + " } from 'lucide-react';\n"
            lines = txt.split("\n")
            last_import = max((i for i, l in enumerate(lines)
                               if l.lstrip().startswith("import ")), default=-1)
            lines.insert(last_import + 1, add.rstrip("\n"))
            try:
                f.write_text("\n".join(lines), encoding="utf-8")
                repaired.append(str(f.relative_to(src_dir)))
            except Exception:
                pass
    except Exception:
        pass
    return {"repaired": repaired}


# ── DEFAULT-EXPORT WRAPPER repair (outlook run-35, 2026-07-02) ────────────────
# api.js declares `export const api = {...}` then ends `export default { api };` — the
# default export is a WRAPPER OBJECT, so every default-import consumer
# (`import api from '../services/api'; api.getMessages(...)`) hits
# `TypeError: api.getMessages is not a function` → the page renders BLANK (run-35 /inbox,
# live). The author plainly meant to re-export the object itself: rewrite
# `export default { <name> };` to `export default <name>;` when <name> is a SINGLE
# identifier that IS a top-level export const/let/var/function in the same file.
_DEFAULT_WRAPPER_RE = re.compile(r"export\s+default\s*\{\s*([A-Za-z_$][\w$]*)\s*\}\s*;?")


def repair_frontend_default_export_wrapper(frontend_dir) -> Dict[str, object]:
    repaired: List[str] = []
    try:
        src_dir = Path(frontend_dir) / "src"
        if not src_dir.is_dir():
            return {"repaired": repaired}
        for f in src_dir.rglob("*"):
            if f.suffix not in (".js", ".jsx", ".ts", ".tsx") or not f.is_file():
                continue
            try:
                txt = f.read_text(encoding="utf-8")
            except Exception:
                continue
            m = _DEFAULT_WRAPPER_RE.search(txt)
            if not m:
                continue
            name = m.group(1)
            if not re.search(r"export\s+(?:const|let|var|function)\s+" + re.escape(name)
                             + r"\b", txt):
                continue  # wrapper of a non-exported local — intent unclear, leave it
            fixed = _DEFAULT_WRAPPER_RE.sub(f"export default {name};", txt, count=1)
            if fixed != txt:
                try:
                    f.write_text(fixed, encoding="utf-8")
                    repaired.append(str(f.relative_to(src_dir)))
                except Exception:
                    pass
    except Exception:
        pass
    return {"repaired": repaired}


# ── FIX #75b: neutralize EXTERNAL stock-photo backgrounds on CONTENT/authed pages ──────
# A lane decorates a content surface (inbox reading-pane / feed / dashboard) with a full-
# bleed EXTERNAL photo — style={{ backgroundImage: 'url("https://images.unsplash.com/…")' }}
# (outlook run-62 OutlookInboxPage:71, a mountain) OR a shared CSS class (index.css
# `.outlook-bg { background-image: url('https://…') }`). Harms: (a) it does NOT match the
# clean reference (a random stock photo, not the app's own surface); (b) it is an EXTERNAL
# network dep in the offline sandbox — the request hangs and a page mid-hydration over a
# pending image is exactly the blank 0.00 the visual gate captures. Replace with a subtle
# neutral gradient in the app's OWN palette. SAFETY (delivery-critical — this runs before
# every docker build): the token is CASE-SENSITIVE lowercase ``url(`` with a
# ``(?<![\w$.])`` lookbehind so it can NEVER match the ``URL(`` of ``new URL("http…")`` nor
# the ``Url(`` of ``avatarUrl("http…")`` (which would corrupt JS → the Vite build fails →
# no delivery); and only a url() sitting in a background/mask CONTEXT is rewritten (never a
# font ``src``/cursor). An <img> is untouched by construction (url() never appears in
# ``<img src>``). Intended hero backgrounds are preserved: a landing/marketing/auth code
# file is skipped wholesale, and a CSS rule whose selector names a hero is left alone.
_EXT_URL_RE = re.compile(
    r"(?<![\w$.])url\(\s*(['\"]?)\s*((?:https?:)?//[^'\")\s]+)\s*\1\s*\)")
_TW_EXT_BG_RE = re.compile(
    r"bg-\[\s*url\(\s*(['\"]?)\s*(?:https?:)?//[^\]]*?\1\s*\)\s*\]")
_BG_CTX_RE = re.compile(r"background|\bmask\b|bg-\[", re.I)
_SURFACE_HEX_RE = re.compile(
    r"(?:background-?color\s*:\s*['\"]?|bg-\[)#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})", re.I)
_DARK_ROOT_RE = re.compile(r"\bbg-(?:black|(?:zinc|slate|gray|neutral|stone)-9\d0)\b")
_MARKETING_NAME_RE = re.compile(
    r"landing|welcome|hero|splash|marketing|login|sign[-_]?in|sign[-_]?up|signin|signup|register|onboard",
    re.I)
# <a href="/login"> / <Link to="/signup">; the (?<![.\w]) lookbehind rejects a JS
# window.location.href = '/login' sign-out, so a CONTENT page is not mistaken for landing.
_ENTRY_CTA_RE = re.compile(
    r"""(?<![.\w])(?:href|to)\s*=\s*['"]/(?:login|signin|sign-in|signup|sign-up|register)\b""",
    re.I)


def _is_marketing_or_auth_context(path: Path, src: str) -> bool:
    names = [path.stem] + re.findall(
        r"(?:export\s+default\s+)?(?:function|const|class)\s+([A-Za-z_]\w*)", src)
    if any(_MARKETING_NAME_RE.search(n or "") for n in names):
        return True
    return bool(_ENTRY_CTA_RE.search(src))


def _mix_hex(r: int, g: int, b: int, tr: int, tg: int, tb: int, amt: float) -> str:
    return "#%02x%02x%02x" % (round(r + (tr - r) * amt), round(g + (tg - g) * amt),
                              round(b + (tb - b) * amt))


def _neutral_gradient_for(scan: str, at: int) -> str:
    base = None
    for m in _SURFACE_HEX_RE.finditer(scan):
        if m.start() < at:
            base = m.group(1)
        else:
            break
    if base is None:
        base = "1f2937" if _DARK_ROOT_RE.search(scan) else "f1f5f9"
    base6 = base if len(base) == 6 else "".join(c * 2 for c in base)
    try:
        r, g, b = int(base6[0:2], 16), int(base6[2:4], 16), int(base6[4:6], 16)
    except Exception:
        r, g, b = 31, 41, 55
    lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
    c2 = _mix_hex(r, g, b, 255, 255, 255, 0.14) if lum < 0.5 else _mix_hex(r, g, b, 0, 0, 0, 0.06)
    return f"linear-gradient(160deg, #{base6} 0%, {c2} 100%)"


def neutralize_frontend_external_backgrounds(frontend_dir) -> Dict[str, object]:
    """Replace EXTERNAL CSS background images on content/authed surfaces with a neutral
    in-palette gradient (self-contained + reference-matching). Best-effort, idempotent
    (the result has no ``url(``), never raises. See the block comment above for safety."""
    result: Dict[str, object] = {"neutralized": []}
    try:
        src_dir = Path(frontend_dir) / "src"
        if not src_dir.is_dir():
            return result
        touched: List[str] = []
        for f in src_dir.rglob("*"):
            if f.suffix not in (".jsx", ".tsx", ".js", ".ts", ".css", ".scss") or not f.is_file():
                continue
            try:
                txt = f.read_text(encoding="utf-8")
            except Exception:
                continue
            if "url(" not in txt or not _EXT_URL_RE.search(txt):
                continue  # fast path: no external CSS background
            is_code = f.suffix in (".jsx", ".tsx", ".js", ".ts")
            if is_code and _is_marketing_or_auth_context(f, txt):
                continue  # intended landing/marketing/auth hero — leave it
            dark = bool(_DARK_ROOT_RE.search(txt))
            # Tailwind arbitrary bg first (replace the WHOLE bg-[url()] token with a class),
            # so the generic url() pass never double-processes it.
            new = _TW_EXT_BG_RE.sub("bg-slate-800" if dark else "bg-slate-100", txt)
            scan = new  # bind so the callback reads the SAME string it scans

            def _repl(m):
                start = m.start()
                if not _BG_CTX_RE.search(scan[max(0, start - 60):start]):
                    return m.group(0)  # not a background/mask (font src, cursor, stray url) → keep
                if not is_code and _MARKETING_NAME_RE.search(scan[max(0, start - 200):start]):
                    return m.group(0)  # CSS rule for a hero-named selector → preserve
                return _neutral_gradient_for(scan, start)

            new = _EXT_URL_RE.sub(_repl, new)
            if new != txt:
                try:
                    f.write_text(new, encoding="utf-8")
                    touched.append(str(f.relative_to(src_dir)))
                except Exception:
                    pass
        result["neutralized"] = sorted(touched)
    except Exception as exc:  # never break generation/validation
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _exported_names(api_src: str) -> Set[str]:
    names: Set[str] = set(_EXPORT_RE.findall(api_src))
    for body in _EXPORT_BRACE_RE.findall(api_src):
        for part in body.split(","):
            part = part.strip()
            if not part:
                continue
            m = re.match(r"[A-Za-z0-9_$]+\s+as\s+([A-Za-z0-9_$]+)", part)
            names.add(m.group(1) if m else part)
    return names


def _imported_api_names(src: str) -> Set[str]:
    out: Set[str] = set()
    for body in _IMPORT_API_RE.findall(src):
        for part in body.split(","):
            part = part.strip()
            if not part:
                continue
            # within braces, `a as b` imports the source name `a`
            m = re.match(r"([A-Za-z0-9_$]+)\s+as\s+[A-Za-z0-9_$]+", part)
            out.add(m.group(1) if m else part)
    return out


def _norm(name: str) -> str:
    s = re.sub(r"[^a-z0-9]", "", name.lower())
    for w in _STOPWORDS:
        s = s.replace(w, "")
    return s


def _best_match(missing: str, exported: Set[str]) -> Optional[str]:
    target = _norm(missing)
    if not target:
        return None
    for e in exported:                       # exact normalized match
        if _norm(e) == target:
            return e
    cands = [e for e in exported if _norm(e) and (_norm(e) in target or target in _norm(e))]
    if cands:
        cands.sort(key=lambda e: abs(len(_norm(e)) - len(target)))
        return cands[0]
    return None


def repair_frontend_api_exports(frontend_dir) -> Dict[str, object]:
    """Ensure every name imported from api.js is exported by it. Mutates api.js
    in place (appends aliases/stubs). Returns a report dict; best-effort and
    never raises on a malformed tree."""
    try:
        frontend_dir = Path(frontend_dir)
        api_js = frontend_dir / "src" / "services" / "api.js"
        if not api_js.exists():
            cands = (list(frontend_dir.glob("src/**/services/api.*"))
                     or list(frontend_dir.glob("src/**/api.js")))
            if not cands:
                return {"repaired": False, "reason": "no api.js"}
            api_js = cands[0]
        api_src = api_js.read_text(encoding="utf-8")
        exported = _exported_names(api_src)

        imported: Set[str] = set()
        for f in frontend_dir.glob("src/**/*"):
            if f.suffix.lower() in _FRONT_EXTS and f.resolve() != api_js.resolve():
                try:
                    imported |= _imported_api_names(f.read_text(encoding="utf-8"))
                except Exception:
                    continue
        missing: List[str] = sorted(n for n in imported if n and n not in exported)
        # apiGet/apiPost are PROJECTOR-OWNED: the page projector's
        # _ensure_api_helpers appends the real implementations. Stubbing them
        # here (live 1.2.0, 2026-06-10) made every projected page throw
        # "apiGet not implemented (auto-stub)" AND blocked the projector's
        # bail-check from ever installing the real ones. Delegate instead.
        if any(n in ("apiGet", "apiPost") for n in missing):
            try:
                from .frontend_page_projector import _ensure_api_helpers
                _ensure_api_helpers(api_js)
                api_src = api_js.read_text(encoding="utf-8")
                exported = _exported_names(api_src)
                missing = sorted(n for n in imported if n and n not in exported)
            except Exception:
                missing = [n for n in missing if n not in ("apiGet", "apiPost")]
        if not missing:
            return {"repaired": False, "missing": []}

        lines = ["", "// auto-reconciled api.js exports (component import/export drift)."]
        aliased, stubbed, reexported = [], [], []
        for name in missing:
            # If `name` is ALREADY a top-level binding in this module (e.g. a
            # component does `import { api }` but api.js has `const api = {...};
            # export default api;`), appending `export const api = ...` is a
            # DUPLICATE declaration → vite "Identifier 'api' has already been
            # declared" → build fail → docker_up FAIL → cascade gate failure (outlook
            # run-5 M2 2026-06-30). Re-export the EXISTING binding instead — the
            # named import then resolves to the REAL value, not an alias/stub.
            if re.search(r"\b(?:const|let|var|function|class)\s+" + re.escape(name) + r"\b",
                         api_src):
                lines.append(f"export {{ {name} }};")
                reexported.append(name)
                continue
            match = _best_match(name, exported)
            if match:
                lines.append(f"export const {name} = {match};")
                aliased.append((name, match))
            else:
                lines.append(
                    f"export const {name} = async (...args) => {{ "
                    f"throw new Error('{name} not implemented (auto-stub)'); }};"
                )
                stubbed.append(name)
        api_js.write_text(
            api_src.rstrip() + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
        return {"repaired": True, "aliased": aliased, "stubbed": stubbed,
                "reexported": reexported, "api_js": str(api_js)}
    except Exception as exc:  # never break generation/validation
        return {"repaired": False, "error": f"{type(exc).__name__}: {exc}"}


_DEFAULT_IMPORT_RE = re.compile(
    r"""import\s+([A-Za-z_$][\w$]*)\s+from\s+['"]([^'"]*services/api(?:\.js)?)['"]""")
_HAS_DEFAULT_EXPORT_RE = re.compile(r"export\s+default\b")


def repair_frontend_default_api_import(frontend_dir) -> Dict[str, object]:
    """A component does ``import api from '.../services/api'`` (DEFAULT import) but api.js
    exports only NAMED members (no ``export default``) → Rollup HARD-fails ("default is not
    exported by src/services/api.js") → the frontend image won't build → docker_up FAIL → no
    delivery (outlook M2, 2026-06-29: OutlookComposeReply/OutlookReadEmail). ``repair_frontend_
    api_exports`` reconciles NAMED imports; this is the INVERSE: when ANY file default-imports
    the api module AND api.js has no default export, append ``export default { …all named
    exports… }`` so the default import resolves to an object carrying every api function
    (``api.getMessages(...)`` works). GENERAL, idempotent, best-effort; never raises."""
    try:
        frontend_dir = Path(frontend_dir)
        api_js = frontend_dir / "src" / "services" / "api.js"
        if not api_js.exists():
            cands = list(frontend_dir.glob("src/**/services/api.*"))
            if not cands:
                return {"repaired": False, "reason": "no api.js"}
            api_js = cands[0]
        # does any component DEFAULT-import the api module?
        wants_default = False
        for f in frontend_dir.glob("src/**/*"):
            if f.suffix.lower() in _FRONT_EXTS and f.resolve() != api_js.resolve():
                try:
                    if _DEFAULT_IMPORT_RE.search(f.read_text(encoding="utf-8")):
                        wants_default = True
                        break
                except Exception:
                    continue
        if not wants_default:
            return {"repaired": False, "reason": "no default import of api"}
        api_src = api_js.read_text(encoding="utf-8")
        if _HAS_DEFAULT_EXPORT_RE.search(api_src):
            return {"repaired": False, "reason": "api.js already has a default export"}
        names = sorted(n for n in _exported_names(api_src) if n.isidentifier())
        if not names:
            # nothing to aggregate — still satisfy the import with an empty object so the
            # build resolves (a call would no-op, far better than a hard build break).
            body = "\nexport default {};\n"
        else:
            body = "\n// auto-added: a component default-imports this module; aggregate the\n" \
                   "// named exports so `import api from './services/api'` resolves.\n" \
                   "export default { " + ", ".join(names) + " };\n"
        api_js.write_text(api_src.rstrip() + "\n" + body, encoding="utf-8")
        return {"repaired": True, "default_export_added": names, "api_js": str(api_js)}
    except Exception as exc:  # never break generation/validation
        return {"repaired": False, "error": f"{type(exc).__name__}: {exc}"}


_API_CALL_PATH_RE = re.compile(r"(\b(?:request|fetch)\(\s*[`'\"])(/[A-Za-z0-9_\-/]+)([`'\"])")


def reconcile_frontend_api_paths(frontend_dir, registered_paths) -> Dict[str, object]:
    """Rewrite frontend api-call PATHS that match NO registered endpoint to the
    unique registered path the lane clearly meant. The lane hand-authors api.js and
    routinely drifts a path from the contract (instagram_v5: it wrote
    ``request('/api/posts/feed')`` while the contract serves ``/api/feed`` →
    runtime 404 on the feed/explore/reels pages AND the delivery-gate
    ``frontend calls unregistered endpoint`` hard-block). repair_frontend_api_exports
    only reconciles export NAMES, never the request PATHS — so the drift survived.

    Conservative + GENERAL (no env-specific paths): only a STATIC (param-less) called
    path that is unregistered AND has EXACTLY ONE static registered path whose segments
    are a subsequence of it AND share its last segment is rewritten (the lane inserted
    extra segments, e.g. ``posts``). Deterministic; never raises.

    ``registered_paths``: set of param-agnostic registered PATHS (no method)."""
    result: Dict[str, object] = {"rewritten": []}
    try:
        fe = Path(frontend_dir)
        if not fe.exists():
            return result
        reg_set = set(registered_paths or ())
        def _segs(p: str):
            return [s for s in p.strip("/").split("/") if s]
        reg_static = [p for p in reg_set if "{" not in p and ":" not in p and "/" in p]
        def _is_subseq(short, long):
            it = iter(long)
            return all(s in it for s in short)
        rewrites = []
        for ext in ("js", "jsx", "ts", "tsx"):
            for fpath in fe.glob(f"**/*.{ext}"):
                if "node_modules" in str(fpath):
                    continue
                try:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                local = []
                def _sub(m):
                    pre, called, post = m.group(1), m.group(2), m.group(3)
                    if called in reg_set:           # already a registered path
                        return m.group(0)
                    cs = _segs(called)
                    if not cs:
                        return m.group(0)
                    cands = sorted({
                        r for r in reg_static
                        if _segs(r) and _segs(r)[-1] == cs[-1]
                        and _is_subseq(_segs(r), cs) and r != called
                    })
                    if len(cands) == 1:
                        local.append((called, cands[0], fpath.name))
                        return pre + cands[0] + post
                    return m.group(0)
                new = _API_CALL_PATH_RE.sub(_sub, text)
                if local:
                    fpath.write_text(new, encoding="utf-8")
                    rewrites.extend(local)
        result["rewritten"] = rewrites
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


# A hardcoded ABSOLUTE origin pointing at a dev / in-container host (localhost,
# 127.0.0.1, or 0.0.0.0 — any or no port) inside a string/template literal. In
# SHIPPED browser code such an origin is ALWAYS wrong: the SPA is served by nginx,
# which same-origin-proxies /api, /auth, /oauth, /.well-known to the backend (see
# nginx.conf.template below), so the browser must call RELATIVE paths. When a lane
# hardcodes ``const API_BASE = 'http://localhost:8082'`` (outlook MM, 2026-06-29)
# the browser hits the HOST's :8082 directly — bypassing the proxy AND using the
# IN-CONTAINER port (the published host port differs, e.g. ``8000:8082``) → every
# request, login included, fails → the SPA can never authenticate → every protected
# route renders the login form ("hollow preview" that the test-user captures as a
# wall of identical Sign-in pages). The negative lookahead ``(?![\w.\-:])`` ensures
# we only strip a bare local origin (``localhost``/``localhost:PORT``), never a host
# that merely starts with it (``localhost.example.com`` is left untouched).
_ABS_LOCAL_ORIGIN_RE = re.compile(
    r"""(['"`])https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?(?![\w.\-:])""")


def normalize_frontend_api_base(frontend_dir) -> Dict[str, object]:
    """Rewrite hardcoded absolute localhost / 127.0.0.1 / 0.0.0.0 origins in the
    frontend source to same-origin RELATIVE URLs, so browser requests flow through
    the nginx reverse proxy (which routes /api, /auth, /oauth, /.well-known to the
    backend) regardless of the published host port.

    Only the ORIGIN PREFIX inside a string/template literal is removed; the path is
    preserved — ``'http://localhost:8082/api/x'`` -> ``'/api/x'`` and a bare
    ``'http://localhost:8082'`` (the common ``API_BASE`` constant) -> ``''`` so that
    ``${API_BASE}/auth/login`` becomes ``/auth/login``. GENERAL (no env-specific
    paths, no port list), idempotent (relative URLs carry no origin to strip), and
    best-effort — never raises on a malformed tree."""
    result: Dict[str, object] = {"normalized": []}
    try:
        fe = Path(frontend_dir)
        src = fe / "src"
        if not src.is_dir():
            return result
        changed: List[str] = []
        for f in src.rglob("*"):
            if (f.suffix.lower() not in _FRONT_EXTS or not f.is_file()
                    or "node_modules" in str(f)):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            new = _ABS_LOCAL_ORIGIN_RE.sub(r"\1", text)
            if new != text:
                f.write_text(new, encoding="utf-8")
                changed.append(str(f.relative_to(fe)))
        result["normalized"] = sorted(changed)
    except Exception as exc:  # never break generation/validation
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


_REL_NAMED_IMPORT_RE = re.compile(
    r"import\s+(?:[A-Za-z0-9_$]+\s*,\s*)?\{([^}]*)\}\s*from\s*['\"](\.\.?/[^'\"]+)['\"]")


def _resolve_local_module(importer: Path, rel: str):
    """Resolve a relative import specifier to an on-disk module file, or None."""
    base = importer.parent / rel
    if base.suffix and base.exists():
        return base
    for ext in (".jsx", ".js", ".tsx", ".ts"):
        c = base.with_name(base.name + ext) if not base.suffix else base.with_suffix(ext)
        if c.exists():
            return c
    for ext in (".jsx", ".js", ".tsx", ".ts"):
        c = base / ("index" + ext)
        if c.exists():
            return c
    return None


def repair_frontend_missing_local_exports(frontend_dir) -> Dict[str, object]:
    """Build-integrity: a NAMED import from a LOCAL module that EXISTS but doesn't
    export that name HARD-fails the Rollup/Vite build ('X is not exported by Y' →
    findVariable error → frontend container won't build → docker_up FAIL → NO
    successful validation run → no delivery; instagram_v5: the lane imported
    ``PlusSquareIcon`` an icons module never exported). repair_frontend_api_exports
    does this only for ``api.js``; generalize it to ANY local module.

    For each genuinely-missing export, append a stub to the TARGET module — a no-op
    component ``() => null`` for a Capitalized name (component/icon — safe to RENDER,
    unlike a throw-stub), else a throw-fn. MAXIMALLY conservative: only stub a name
    that appears NOWHERE in the target module's source (so a parser miss can never
    cause a duplicate-declaration build break). GENERAL, idempotent; never raises."""
    result: Dict[str, object] = {"repaired": []}
    try:
        fe = Path(frontend_dir)
        src_dir = fe / "src"
        if not src_dir.exists():
            return result
        to_add: Dict[Path, set] = {}
        to_reexport: Dict[Path, set] = {}
        for f in src_dir.glob("**/*"):
            if f.suffix.lower() not in _FRONT_EXTS or "node_modules" in str(f):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for names_blob, rel in _REL_NAMED_IMPORT_RE.findall(text):
                target = _resolve_local_module(f, rel)
                # a MISSING module is scaffold_missing_local_pages' job, not ours
                if target is None or target.resolve() == f.resolve():
                    continue
                names = [n.strip().split(" as ")[0].strip() for n in names_blob.split(",")]
                names = [n for n in names if n and n.isidentifier()]
                if not names:
                    continue
                try:
                    tgt_src = target.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                exported = _exported_names(tgt_src)
                for n in names:
                    if n in exported:
                        continue
                    # ALREADY DECLARED in the target (e.g. `const AuthContext =
                    # createContext()` but not exported) → re-export the EXISTING
                    # binding. A stub would be a duplicate-declaration build break;
                    # SKIPPING (the old behavior) leaves the named import unresolved
                    # → "X is not exported by Y" → vite fail → docker_up wedge → run
                    # abort (outlook run-7 AuthContext from App.jsx, 2026-06-30).
                    if re.search(r"\b(?:const|let|var|function|class)\s+"
                                 + re.escape(n) + r"\b", tgt_src):
                        to_reexport.setdefault(target, set()).add(n)
                    # appears NOWHERE → safe to stub (conservative; a parser miss
                    # can never cause a duplicate-declaration build break)
                    elif not re.search(r"\b" + re.escape(n) + r"\b", tgt_src):
                        to_add.setdefault(target, set()).add(n)
        for target, names in to_add.items():
            try:
                tgt_src = target.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            add = sorted(n for n in names
                         if not re.search(r"\b" + re.escape(n) + r"\b", tgt_src))
            if not add:
                continue
            lines = ["", "// auto-reconciled missing exports (lane import/export drift)."]
            for n in add:
                if n[:1].isupper():
                    lines.append(f"export const {n} = (props) => null;  // auto-stub component")
                else:
                    lines.append(
                        f"export const {n} = (...args) => {{ "
                        f"throw new Error('{n} not implemented (auto-stub)'); }};")
            target.write_text(tgt_src.rstrip() + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
            result["repaired"].append((target.name, add))
        # Re-export existing-but-unexported local bindings (e.g. a Context the lane
        # declared with `const X = createContext()` and imported { X } elsewhere).
        for target, names in to_reexport.items():
            try:
                tgt_src = target.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            exported = _exported_names(tgt_src)
            reexp = sorted(
                n for n in names if n not in exported
                and re.search(r"\b(?:const|let|var|function|class)\s+"
                              + re.escape(n) + r"\b", tgt_src))
            if not reexp:
                continue
            lines = ["", "// auto-reconciled missing exports (re-export existing local bindings)."]
            lines += [f"export {{ {n} }};" for n in reexp]
            target.write_text(tgt_src.rstrip() + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
            result.setdefault("reexported", []).append((target.name, reexp))
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


_LOCAL_DEFAULT_IMPORT = re.compile(
    r"""import\s+([A-Za-z_$][\w$]*)\s+from\s+['"](\.[^'"]+)['"]""")
# A <Route> whose element is an INLINE placeholder <div> (e.g.
# `element={<div>Login Page Stub</div>}`) instead of a real page component. The lane
# sometimes inlines a stub div rather than routing to the page the framework already
# projected — outlook run #9: /login -> "Login Page Stub" (login DEAD) while the
# functional LoginPage.jsx sat unrouted. Captures: (1) prefix incl path + element={,
# (2) the route path, (3) the closing }.
_INLINE_STUB_ROUTE = re.compile(
    r'(<Route\b[^>]*?\bpath\s*=\s*["\']([^"\']+)["\'][^>]*?\belement\s*=\s*\{\s*)'
    r'<div\b[^>]*>[^<}]{0,60}</div>(\s*\}\s*/?>)')
_COMPONENT_DIR = re.compile(r"/(pages|components|views|screens|routes)/")
_LOCAL_NAMED_IMPORT = re.compile(
    r"""import\s*\{([^}]*)\}\s*from\s*(['"])(\.[^'"]+)\2""")
_HAS_DEFAULT_EXPORT = re.compile(r"export\s+default\b")


def repair_frontend_named_default_imports(frontend_dir) -> Dict[str, object]:
    """A page does ``import { NavBar } from '../components/NavBar'`` (NAMED) but the
    target only ``export default NavBar`` → Rollup HARD-fails the build ("NavBar is
    not exported by NavBar.jsx") → frontend image won't build → docker_up FAIL → no
    delivery (live smoke-notes 2026-06-20). The frontend twin of
    repair_frontend_api_exports for LOCAL component/page imports: when a SINGLE
    named import isn't exported by its target AND the target has a default export,
    rewrite that import to a default import. Build-integrity is framework-owned;
    best-effort, never raises."""
    try:
        frontend_dir = Path(frontend_dir)
        src = frontend_dir / "src"
        if not src.is_dir():
            return {"repaired": False, "reason": "no src/"}
        info: Dict[Path, Tuple[Set[str], bool]] = {}

        def _target_info(p: Path) -> Tuple[Set[str], bool]:
            if p not in info:
                try:
                    t = p.read_text(encoding="utf-8")
                    info[p] = (_exported_names(t), bool(_HAS_DEFAULT_EXPORT.search(t)))
                except Exception:
                    info[p] = (set(), False)
            return info[p]

        def _resolve(importer: Path, rel: str) -> Optional[Path]:
            base = (importer.parent / rel)
            for e in _FRONT_EXTS:
                cand = base.with_suffix(e)
                if cand.is_file():
                    return cand
            for e in _FRONT_EXTS:
                idx = base / f"index{e}"
                if idx.is_file():
                    return idx
            return None

        fixed: List[str] = []
        for f in src.rglob("*"):
            if f.suffix.lower() not in _FRONT_EXTS or not f.is_file():
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except Exception:
                continue
            state = {"changed": False}

            def _repl(m: "re.Match") -> str:
                body, quote, rel = m.group(1), m.group(2), m.group(3)
                names = [n.strip() for n in body.split(",") if n.strip()]
                if len(names) != 1 or " as " in body:
                    return m.group(0)
                tgt = _resolve(f, rel)
                if tgt is None:
                    return m.group(0)
                exported, has_default = _target_info(tgt)
                name = names[0]
                if name not in exported and has_default:
                    state["changed"] = True
                    return f"import {name} from {quote}{rel}{quote}"
                return m.group(0)

            new_text = _LOCAL_NAMED_IMPORT.sub(_repl, text)
            if state["changed"] and new_text != text:
                f.write_text(new_text, encoding="utf-8")
                fixed.append(str(f.relative_to(frontend_dir)))
        return {"repaired": bool(fixed), "fixed": fixed}
    except Exception as exc:
        return {"repaired": False, "error": f"{type(exc).__name__}: {exc}"}


def _stub_page_component(name: str) -> str:
    """A minimal default-exported React component (JSX automatic runtime — no
    React import needed, matching the lane's pages). Used for build-integrity
    stubs of UNDECLARED local imports; carries NO flagged placeholder marker so a
    declared page never trips the stub-detector on it."""
    label = re.sub(r"(?<!^)(?=[A-Z])", " ", name).replace("Page", "").strip() or name
    return (
        f"export default function {name}() {{\n"
        f"  return (\n"
        f'    <div className="min-h-screen bg-zinc-50 text-zinc-900 px-8 py-16 text-center">\n'
        f'      <h2 className="text-xl font-semibold">{label}</h2>\n'
        f"    </div>\n"
        f"  );\n"
        f"}}\n"
    )


def _api_path_to_js(path: str) -> str:
    """'/api/notes' -> "'/api/notes'"; '/api/notes/:id' (or {id}) ->
    "'/api/notes/' + (params.id || '')" — a route-param-aware fetch target."""
    m = re.search(r"[:{]([a-zA-Z_]\w*)[}]?", path)
    if not m:
        return "'" + path + "'"
    expr = "'" + path[:m.start()] + "' + (params." + m.group(1) + " || '')"
    post = path[m.end():]
    if post:
        expr += " + '" + post + "'"
    return expr


def _is_auth_page(name: str, page: Mapping[str, Any]) -> bool:
    """True for the login/signup page — by route, id, or component name. The
    framework universally owns /auth/register + /auth/login, so a login/signup page
    must project a REAL functional auth form (not the generic single-input POST stub
    or the inert no-api stub). youtube run #20 shipped a dead <h2>Login</h2> card
    because the kickoff-derived login_page had no apis_used → fell to the inert stub
    → the test-user signup/login walkthrough found no submit button."""
    route = str((page or {}).get("route") or "").strip().lower().rstrip("/")
    pid = str((page or {}).get("id") or "").strip().lower()
    n = str(name or "").lower()
    return (route in ("/login", "/signin", "/signup", "/register")
            or pid in ("login_page", "signup_page", "login", "signup", "register_page", "auth_page")
            or "login" in n or "signup" in n or n == "authpage")


def _is_landing_page(name: str, page: Mapping[str, Any]) -> bool:
    """A marketing/landing entry page (welcome → sign in/create account). Keyed on
    the NAME/id/route saying 'landing'/'welcome' — NOT on route=='/' alone, since a
    content app's home FEED also lives at '/' (and it has apis_used → a real list)."""
    pid = str((page or {}).get("id") or "").strip().lower()
    n = str(name or "").lower()
    route = str((page or {}).get("route") or "").strip().lower().rstrip("/")
    if (page or {}).get("apis_used"):
        return False  # a data-driven home page is a list, not a marketing splash
    return ("landing" in n or "welcome" in n or "landing" in pid or "welcome" in pid
            or "landing" in route or "welcome" in route)


# A real landing/entry page: app wordmark + hero + WORKING nav to /login and /signup
# (plain <a> so it works with any router). Fixes "stuck on a dead 'Landing' heading
# with no way in" — the no-api stub used to render just <h2>Landing</h2>. No
# placeholder marker → counts as a real authored entry page.
_LANDING_TEMPLATE = """export default function __COMP__() {
  return (
    <div className="min-h-screen bg-white text-zinc-900 flex flex-col">
      <header className="flex items-center justify-between px-6 sm:px-10 py-4 border-b border-zinc-200">
        <div className="text-lg font-semibold text-blue-700">__APP__</div>
        <nav className="flex items-center gap-2">
          <a href="/login" className="rounded-md px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100">Sign in</a>
          <a href="/signup" className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">Create free account</a>
        </nav>
      </header>
      <main className="flex flex-1 flex-col items-center justify-center px-6 text-center">
        <h1 className="max-w-2xl text-4xl sm:text-5xl font-bold tracking-tight">__APP__</h1>
        <p className="mt-4 max-w-xl text-lg text-zinc-500">Sign in to connect, organize, and get things done.</p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <a href="/login" className="rounded-lg bg-blue-600 px-6 py-3 font-medium text-white hover:bg-blue-700">Sign in</a>
          <a href="/signup" className="rounded-lg border border-zinc-300 px-6 py-3 font-medium text-zinc-700 hover:bg-zinc-50">Create a free account</a>
        </div>
      </main>
    </div>
  );
}
"""


def _is_register_mode(name: str, page: Mapping[str, Any]) -> bool:
    route = str((page or {}).get("route") or "").strip().lower()
    pid = str((page or {}).get("id") or "").strip().lower()
    n = str(name or "").lower()
    return ("signup" in route or "register" in route
            or "signup" in pid or "register" in pid
            or "signup" in n or "register" in n)


# A self-contained, functional auth form (no dependency on the lane's api.js shape):
# real email/password inputs + submit, POSTs to the framework-universal /auth/login
# and /auth/register, stores the access_token under BOTH localStorage keys the
# projected pages read, and redirects. No placeholder marker → passes the stub gate.
_AUTH_PAGE_TEMPLATE = """import { useState } from 'react';

export default function __COMP__() {
  const [isRegister, setIsRegister] = useState(__IS_REGISTER__);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const onSubmit = async (e) => {
    e.preventDefault();
    setError('');
    const path = isRegister ? '/auth/register' : '/auth/login';
    const body = isRegister ? { email, password, name, username: email } : { email, password };
    try {
      const r = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { setError((d && (d.detail || d.error)) || ('Error ' + r.status)); return; }
      const token = d.access_token || d.token || (d.item && (d.item.access_token || d.item.token));
      if (token) { localStorage.setItem('access_token', token); localStorage.setItem('token', token); }
      window.location.href = '/';
    } catch (err) { setError(String(err)); }
  };
  return (
    <div className="min-h-screen flex items-center justify-center bg-zinc-50">
      <form onSubmit={onSubmit} className="w-full max-w-sm space-y-4 rounded-xl border border-zinc-200 bg-white p-8 shadow-sm">
        <h1 className="text-2xl font-semibold text-zinc-900">{isRegister ? 'Create account' : 'Sign in'}</h1>
        {isRegister ? (
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name"
                 className="w-full rounded-lg border border-zinc-300 px-3 py-2" />
        ) : null}
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Email" required
               className="w-full rounded-lg border border-zinc-300 px-3 py-2" />
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Password" required
               className="w-full rounded-lg border border-zinc-300 px-3 py-2" />
        {error ? <p className="text-sm text-red-600">{error}</p> : null}
        <button type="submit" className="w-full rounded-lg bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700">
          {isRegister ? 'Create account' : 'Log in'}
        </button>
        <button type="button" onClick={() => setIsRegister(!isRegister)}
                className="w-full text-sm text-blue-600">
          {isRegister ? 'Have an account? Sign in' : 'New here? Create an account'}
        </button>
      </form>
    </div>
  );
}
"""


def _mark_fallback_page(src: str) -> str:
    """Prefix a framework-projected (fallback) page with _PAGE_MARKER so
    validation_runner.frontend_fallback_pages counts it AND the runtime page gate
    knows it is NOT a real lane-built page. Auth pages are framework-OWNED (the
    intended login/signup), NOT fallback, so they are NOT marked."""
    from .frontend_page_projector import _PAGE_MARKER
    if _PAGE_MARKER in src:
        return src
    return _PAGE_MARKER + "\n" + src


def _nav_links_jsx(nav_routes) -> str:
    """A full-bleed top-nav bar linking the app's main business routes, so the
    projected pages are NAVIGABLE — you can move between inbox/calendar/contacts/…
    instead of each page being a disconnected dead-end (the #1 'app isn't usable'
    symptom). Plain ``<a href>`` (router-agnostic) + a Sign out. Negative margins
    cancel the page's ``px-6 py-6`` padding so the bar is full width at the top.
    Returns '' when there are no other routes (single-page / auth / landing)."""
    routes = [(str(l).strip(), str(r).strip()) for (l, r) in (nav_routes or []) if str(r).strip()]
    if not routes:
        return ""
    links = "\n".join(
        f'        <a href="{r}" className="rounded-md px-3 py-1.5 text-sm font-medium '
        f'text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900">{l}</a>'
        for (l, r) in routes)
    return (
        '<nav className="-mx-6 -mt-6 mb-6 flex flex-wrap items-center gap-1 border-b '
        'border-zinc-200 bg-white px-6 py-2">\n'
        + links + "\n"
        "        <button onClick={() => { localStorage.clear(); window.location.href = '/login'; }} "
        'className="ml-auto rounded-md px-3 py-1.5 text-sm text-zinc-500 hover:bg-zinc-100 '
        'hover:text-zinc-900">Sign out</button>\n'
        "      </nav>")


def _project_page_component(name: str, page: Mapping[str, Any], nav_routes=None) -> str:
    """Project a MINIMALLY-FUNCTIONAL, data-driven page from the contract instead
    of an inert stub. Generic for ANY app: a page with a declared GET fetches it
    and renders the rows; a POST-only page renders a submit form; an api-less page
    is a clean static page. Uses bare ``fetch`` + the JWT from localStorage (no
    dependency on the lane's api.js export shape), so the page (a) carries a real
    handler/api call and no placeholder marker — passing the stub-detector — and
    (b) actually exercises its declared endpoint. ``nav_routes`` (list of (label,
    route)) injects a shared top-nav so the data pages are interconnected/navigable.
    The lane may still overwrite it with richer UI (this only runs when missing)."""
    _nav = _nav_links_jsx(nav_routes)
    # Auth pages get a REAL functional login/register form (framework owns
    # /auth/login + /auth/register) — never the generic single-input POST stub or
    # the inert no-api stub, which would ship a login page a user can't use.
    if _is_auth_page(name, page):
        return (_AUTH_PAGE_TEMPLATE.replace("__COMP__", name)
                .replace("__IS_REGISTER__", "true" if _is_register_mode(name, page) else "false"))
    label = re.sub(r"(?<!^)(?=[A-Z])", " ", name).replace("Page", "").strip() or name
    if _is_landing_page(name, page):
        # Real entry page: wordmark/hero + WORKING sign-in/create-account nav. Derive
        # the app name by stripping the landing/welcome words (OutlookLanding → Outlook;
        # a bare LandingPage → "Welcome"). Never the dead <h2>Landing</h2> stub again.
        app = re.sub(r"\b(landing|welcome|page)\b", "", label, flags=re.I).strip() or "Welcome"
        return _LANDING_TEMPLATE.replace("__COMP__", name).replace("__APP__", app)
    parsed = []
    for a in (page.get("apis_used") or []):
        parts = str(a).strip().split(None, 1)
        if len(parts) == 2 and str(parts[0]).isalpha():
            parsed.append((parts[0].upper(), parts[1].strip()))
        elif parts and str(parts[0]).startswith("/"):
            parsed.append(("GET", str(parts[0]).strip()))
    get_ep = next((p for (m, p) in parsed if m == "GET"), None)
    # ANY write verb (POST/PUT/PATCH/DELETE) renders a functional form — a page whose
    # apis_used are write-only (e.g. a settings page that only PUTs) must NOT degrade to
    # the inert no-api stub. POST is preferred (a create form), else the first write verb.
    write_ep = next(((m, p) for (m, p) in parsed if m == "POST"), None) \
        or next(((m, p) for (m, p) in parsed if m in ("PUT", "PATCH", "DELETE")), None)

    if get_ep:
        # LIST render (not a raw key:value dump, NOT a 16:9 video-card grid): a light,
        # neutral row list — leading avatar/thumbnail (or an initial), a title, a
        # snippet/sender subtitle, and a few scalar meta fields. This is the universal
        # business-app shape (email/message/contact/event lists, feeds) and reads as
        # human-usable for the MAJORITY of apps — a far better FLOOR than the old dark
        # aspect-video card grid (which only suited a video site and rendered emails as
        # blank 16:9 tiles on black). The lane authors the real themed page on top; this
        # only runs when the page file is missing. Fetches the page's OWN declared GET
        # endpoint (apis_used → __PATH__), never a hardcoded one. data-fallback marks it
        # framework-generated so the runtime page gate never counts it as 'implemented'.
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
                                   .replace("__PATH__", _api_path_to_js(get_ep))
                                   .replace("__NAV__", _nav))

    if write_ep:
        write_method, write_path = write_ep
        tpl = """import { useState } from 'react';

export default function __COMP__() {
  const [value, setValue] = useState('');
  const [status, setStatus] = useState('');
  const onSubmit = async (e) => {
    e.preventDefault();
    const token = (localStorage.getItem('access_token') || localStorage.getItem('token'));
    try {
      const r = await fetch('__POST__', {
        method: '__METHOD__',
        headers: Object.assign({ 'Content-Type': 'application/json' },
          token ? { Authorization: 'Bearer ' + token } : {}),
        body: JSON.stringify({ title: value, name: value, content: value, body: value }),
      });
      setStatus(r.ok ? 'Saved.' : ('Error ' + r.status));
    } catch (err) {
      setStatus(String(err));
    }
  };
  return (
    <div data-fallback="1" className="min-h-screen bg-zinc-50 text-zinc-900 px-6 py-6">
      __NAV__
      <div className="max-w-lg rounded-xl border border-zinc-200 bg-white shadow-sm px-8 py-8">
        <h2 className="text-xl font-semibold">__LABEL__</h2>
        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <input value={value} onChange={(e) => setValue(e.target.value)}
                 className="w-full rounded-lg border border-zinc-300 bg-white px-4 py-2 text-zinc-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                 placeholder="Enter a value" />
          <button type="submit" className="rounded-lg bg-blue-600 px-5 py-2 font-medium text-white hover:bg-blue-700">Submit</button>
        </form>
        {status ? <p className="mt-3 text-sm text-zinc-500">{status}</p> : null}
      </div>
    </div>
  );
}
"""
        return _mark_fallback_page(tpl.replace("__COMP__", name).replace("__LABEL__", label)
                                   .replace("__METHOD__", write_method)
                                   .replace("__POST__", write_path).replace("__NAV__", _nav))

    return _mark_fallback_page(_stub_page_component(name))


# <Route path="/x" element={<Comp .../>}> — used to recover the ROUTE a dangling
# page import is wired at, so a missing page can be projected as a REAL data page
# (matched to the registered ui_page at that route) instead of a dead heading.
_ROUTE_ELEMENT = re.compile(
    r'path\s*=\s*["\']([^"\']+)["\'][^>]*?element\s*=\s*\{\s*<\s*(\w+)')


def _route_apis_map(ui_pages) -> Dict[str, list]:
    """{normalized_route: apis_used} from the registered ui_pages, so a dangling page
    import can be matched to its contract endpoint by ROUTE (the lane's App.jsx
    component name often differs from the registered component name)."""
    out: Dict[str, list] = {}
    for pg in (ui_pages or []):
        if not isinstance(pg, dict):
            continue
        r = str(pg.get("route") or pg.get("path") or "").strip().rstrip("/").lower()
        if r and pg.get("apis_used"):
            out.setdefault(r, list(pg.get("apis_used") or []))
    return out


def scaffold_missing_local_pages(frontend_dir, ui_pages=None) -> Dict[str, object]:
    """Scaffold a valid component for any LOCAL default import whose target file is
    missing. Root fix for the frontend half of the hollow-release bug (instagram
    MM, 2026-06-08): the frontend lane wires a page import + route
    (``import MessagesInboxPage from './pages/MessagesInboxPage'``) but never
    creates the file, so ``npm run build`` fails ("Could not resolve") and the
    frontend container can't boot. Build-integrity is framework-owned.

    ROUTED-PAGE QUALITY (outlook run #8): the lane routinely routes App.jsx to a
    component name (``<Route path="/inbox" element={<OutlookInbox/>}>``) that is NOT
    its registered ui_page (the contract page is e.g. ``InboxPage``), so the good
    framework projection (light-list + nav) lands on the unrouted name while the
    ROUTED name fell here and got a dead ``<h2>`` heading — the user saw a bare
    stub at /inbox. Now: for a missing PAGE import we recover its ROUTE from the
    importing file's ``<Route>`` and project a REAL data page via
    ``_project_page_component`` (its apis_used matched to the registered ui_page at
    that route + the shared nav across the app's routes). Non-page components, or
    pages with no resolvable route, still get the minimal stub. Best-effort; never
    clobbers a real file."""
    try:
        frontend_dir = Path(frontend_dir)
        src_root = (frontend_dir / "src").resolve()
        if not src_root.exists():
            return {"scaffolded": []}
        route_apis = _route_apis_map(ui_pages)
        scaffolded: List[str] = []
        for f in src_root.glob("**/*"):
            if f.suffix.lower() not in _FRONT_EXTS or not f.is_file():
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except Exception:
                continue
            # comp -> route + the app's business routes (for the shared nav), recovered
            # from THIS file's <Route> table (App.jsx imports the page AND routes it).
            comp_route = {c: p for (p, c) in _ROUTE_ELEMENT.findall(text)}
            nav_routes = []
            _seen = set()
            for _p, _c in _ROUTE_ELEMENT.findall(text):
                _r = _p.strip().rstrip("/")
                low = _r.lower()
                if (":" in _r or "{" in _r or _r in ("", "/")
                        or low in ("/login", "/signup", "/signin", "/register")
                        or "landing" in low or "welcome" in low or _r in _seen):
                    continue
                _seen.add(_r)
                seg = _r.strip("/").split("/")[0]
                nav_routes.append((re.sub(r"[-_]+", " ", seg).title() or seg, _r))
            nav_routes = nav_routes[:7]
            for name, rel in _LOCAL_DEFAULT_IMPORT.findall(text):
                if not _COMPONENT_DIR.search(rel):
                    continue
                base = (f.parent / rel).resolve()
                if base.suffix:
                    target = base
                    if target.exists():
                        continue
                else:
                    if any(base.with_suffix(e).exists() for e in _FRONT_EXTS):
                        continue
                    if any((base / f"index{e}").exists() for e in _FRONT_EXTS):
                        continue
                    target = base.with_suffix(".jsx")
                try:
                    target.relative_to(src_root)
                except ValueError:
                    continue  # never write outside src/
                if target.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                # A missing PAGE wired at a known route → project a REAL page (light-list
                # + nav) keyed to the contract endpoint at that route, not a dead heading.
                route = (comp_route.get(name) or "").strip().rstrip("/")
                is_page = "/pages/" in rel.replace("\\", "/")
                page_spec = None
                if is_page and route:
                    apis = route_apis.get(route.lower())
                    page_spec = {"route": route, "id": name.lower(),
                                 "apis_used": apis or []}
                if page_spec is not None:
                    body = _project_page_component(name, page_spec, nav_routes=nav_routes)
                else:
                    body = _stub_page_component(name)
                target.write_text(body, encoding="utf-8")
                scaffolded.append(str(target.relative_to(frontend_dir)))
        return {"scaffolded": sorted(set(scaffolded))}
    except Exception as exc:  # never break generation/validation
        return {"scaffolded": [], "error": f"{type(exc).__name__}: {exc}"}


def _resolve_route_component(route: str, pages_dir: Path) -> Optional[str]:
    """Pick the REAL page component in src/pages/ that should serve ``route`` — auth
    routes → LoginPage/SignupPage; else the PascalCase page derived from the route's
    first segment (``/inbox`` → InboxPage), accepting the first existing candidate
    with non-trivial content (so a dead 8-line stub is never chosen over a real page)."""
    low = route.strip().rstrip("/").lower()
    seg = low.strip("/").split("/")[0] if low.strip("/") else ""
    if low in ("/login", "/signin"):
        cands = ["LoginPage"]
    elif low in ("/signup", "/register"):
        cands = ["SignupPage"]
    elif low in ("", "/"):
        # the root / landing route — point at the real landing/home page (the lane
        # leaves /  as `element={<div>Landing Page Stub</div>}` while LandingPage.jsx
        # sits unrouted; outlook run #9).
        cands = ["LandingPage", "HomePage", "Home", "Dashboard", "DashboardPage"]
    elif not seg:
        return None
    else:
        pasc = re.sub(r"[^a-z0-9]+", " ", seg).title().replace(" ", "")
        cands = [pasc + "Page", pasc, pasc + "List", pasc + "ListPage"]
    for c in cands:
        f = pages_dir / f"{c}.jsx"
        try:
            if f.exists() and (f.stat().st_size > 200
                               or "divide-y" in f.read_text(encoding="utf-8", errors="ignore")
                               or "onSubmit" in f.read_text(encoding="utf-8", errors="ignore")):
                return c
        except Exception:
            continue
    # fallback: any existing page whose name contains the segment
    if seg:
        for f in sorted(pages_dir.glob("*.jsx")):
            if seg in f.stem.lower() and f.stat().st_size > 200:
                return f.stem
    return None


def reroute_inline_stub_routes(frontend_dir) -> Dict[str, object]:
    """Re-point App.jsx routes whose element is an INLINE placeholder <div> (e.g.
    ``element={<div>Login Page Stub</div>}``) to the REAL page component that already
    exists in src/pages/ for that route. The lane sometimes inlines a stub div instead
    of importing the page the framework projected — outlook run #9 shipped
    ``/login -> <div>Login Page Stub</div>`` (login DEAD) and ``/inbox -> <div>Inbox
    Page Stub</div>`` (blank) while the functional LoginPage.jsx + InboxPage.jsx sat
    unrouted. Re-point each to its real component (+ import). Domain-agnostic; only
    touches routes whose element is a literal placeholder div. Best-effort; never raises."""
    try:
        frontend_dir = Path(frontend_dir)
        app = frontend_dir / "src" / "App.jsx"
        pages_dir = frontend_dir / "src" / "pages"
        if not app.exists() or not pages_dir.is_dir():
            return {"rerouted": []}
        src = app.read_text(encoding="utf-8")
        rerouted: List[str] = []
        needed_imports: Dict[str, str] = {}

        def _sub(m):
            route = m.group(2)
            comp = _resolve_route_component(route, pages_dir)
            if not comp:
                return m.group(0)  # no real page to point at — leave the stub
            needed_imports[comp] = f"./pages/{comp}"
            rerouted.append(f"{route} -> {comp}")
            return f"{m.group(1)}<{comp} />{m.group(3)}"

        new_src = _INLINE_STUB_ROUTE.sub(_sub, src)
        if not rerouted:
            return {"rerouted": []}
        # add any missing default imports at the top (after the last existing import)
        add = [f"import {c} from '{p}';" for c, p in needed_imports.items()
               if re.search(rf"\bimport\s+{re.escape(c)}\b", new_src) is None]
        if add:
            _imps = list(re.finditer(r"^import .*$", new_src, re.M))
            if _imps:
                at = _imps[-1].end()
                new_src = new_src[:at] + "\n" + "\n".join(add) + new_src[at:]
            else:
                new_src = "\n".join(add) + "\n" + new_src
        app.write_text(new_src, encoding="utf-8")
        return {"rerouted": sorted(set(rerouted))}
    except Exception as exc:  # never break generation/validation
        return {"rerouted": [], "error": f"{type(exc).__name__}: {exc}"}


def _pascal_case(name: str) -> str:
    """snake/kebab/space → PascalCase component name. ``youtube_home`` →
    ``YoutubeHome``; falls back to ``Page`` for empty input."""
    parts = re.split(r"[^A-Za-z0-9]+", str(name or ""))
    out = "".join(p[:1].upper() + p[1:] for p in parts if p)
    return out or "Page"


def _page_component_name(page: Dict[str, Any]) -> str:
    comp = str((page or {}).get("component") or "").strip()
    if comp and re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*$", comp):
        return comp
    return _pascal_case((page or {}).get("name"))


# Identifiers the framework-managed App.jsx already binds — a projected PAGE import
# must never reuse them or esbuild fails the whole build with "symbol X has already
# been declared" (smoke-notes 2026-06-19: an agent registered a ui_page named "App",
# so `import App from './pages/App.jsx'` collided with `export default function App()`
# → the frontend build failed every cycle → run wedged on docker_up).
_RESERVED_APP_IDENTS = frozenset({"App", "BrowserRouter", "Routes", "Route", "React"})


def _safe_import_alias(comp: str) -> str:
    """Local binding for a projected page import; aliased to ``<Comp>Page`` when the
    component name would collide with App.jsx's own identifiers (default import of
    the page file is unchanged — only the local name is aliased)."""
    return f"{comp}Page" if comp in _RESERVED_APP_IDENTS else comp


def _render_routed_app(entries: List[tuple]) -> str:
    """Generic React-Router App over the declared pages. DOMAIN-AGNOSTIC — no
    feed/login assumptions (unlike the social-shaped _BASELINE_APP_JSX it
    replaces). ``entries``: list of (component, route)."""
    imports = "\n".join(
        f"import {_safe_import_alias(c)} from './pages/{c}.jsx';" for c, _ in entries)
    routes = "\n".join(
        f'          <Route path="{r}" element={{<{_safe_import_alias(c)} />}} />'
        for c, r in entries)
    return (
        f"{_ROUTES_MARKER}\n"
        "// The orchestrator projects these routes from the registered ui_pages\n"
        "// contract so the app is navigable by construction. Filling page bodies?\n"
        "// Edit the files in ./pages/. Taking over routing yourself? Delete the\n"
        "// marker line above and this file becomes yours (never overwritten).\n"
        "import { BrowserRouter, Routes, Route } from 'react-router-dom';\n"
        f"{imports}\n\n"
        "export default function App() {\n"
        "  return (\n"
        "    <BrowserRouter>\n"
        "      <Routes>\n"
        f"{routes}\n"
        "      </Routes>\n"
        "    </BrowserRouter>\n"
        "  );\n"
        "}\n"
    )


def _dominant_route_wrapper(app_jsx: str) -> Optional[str]:
    """The component that wraps the MAJORITY of existing ``<Route element={<X…>}>``
    (e.g. ``ProtectedRoute``), or None. An injected route should wrap in the same
    guard its siblings use — wiring an auth-gated page bare, outside the wrapper
    every sibling has, is a latent correctness bug. Only returns a name used by
    ≥2 routes AND in-scope (imported or defined in App.jsx); else None → wire
    bare. (Captures the FIRST identifier after ``element={<`` — the wrapper, not
    the inner page — which is exactly what we want here.)"""
    from collections import Counter
    names = re.findall(r"element=\{\s*<\s*([A-Za-z_]\w*)", app_jsx)
    if not names:
        return None
    name, cnt = Counter(names).most_common(1)[0]
    in_scope = bool(
        re.search(r"(function|const|class)\s+" + re.escape(name) + r"\b", app_jsx)
        or re.search(r"import\b[^\n;]*\b" + re.escape(name) + r"\b", app_jsx))
    return name if cnt >= 2 and in_scope else None


def project_missing_ui_routes(app_jsx: str, ui_pages: List[Dict[str, Any]]
                              ) -> Tuple[str, List[str]]:
    """ADDITIVELY inject a ``<Route>`` (+ default import) for every declared
    ui_page whose route is NOT already wired in a (lane-authored) App.jsx — the
    frontend analogue of ``route_projector.project_missing_routes`` (additive:
    never removes/rewrites a lane route, only fills declared gaps). PROPOSAL #19.

    The route-identity test reuses #18's ``frontend_audit._canon_route`` /
    ``_wired_route_set`` (the single source of truth for "the same route", same
    rule as the backend ``_norm_route``), so a lane that wired the declared route
    under a different param NAME or shape is NOT double-wired. The injected route
    is wrapped in the dominant sibling wrapper (e.g. ``ProtectedRoute``) when one
    is detectable, else wired bare. Component file existence is the caller's job
    (``scaffold_pages_from_contract`` writes the stub only-if-missing first).

    Returns ``(new_text, injected_routes)``. Idempotent (a second call is a
    no-op). Best-effort: returns the input UNCHANGED (and ``[]``) if it cannot
    anchor confidently — NEVER raises, NEVER corrupts a lane file."""
    try:
        from .frontend_audit import _canon_route, _route_is_wired
        wrapper = _dominant_route_wrapper(app_jsx)
        new_routes: List[str] = []
        new_imports: List[str] = []
        injected: List[str] = []
        seen_canon = set()
        for page in ui_pages or []:
            if not isinstance(page, dict):
                continue
            route = str(page.get("route") or "").strip()
            if not route:
                continue
            canon = _canon_route(route)
            # decide "missing" with the EXACT gate predicate (#18 _route_is_wired:
            # normalized SET match + trailing-optional fallback) — NOT raw set
            # membership — so we inject ONLY what the delivery gate would flag as
            # unwired (e.g. /watch/:id, already satisfied by a wired /watch, is NOT
            # re-injected; a genuinely-absent /feed/library IS).
            if canon in seen_canon or _route_is_wired(route, app_jsx):
                continue
            seen_canon.add(canon)
            comp = _page_component_name(page)
            local = _safe_import_alias(comp)  # avoid colliding with App.jsx's own idents
            inner = f"<{local} />"
            elem = f"<{wrapper}>{inner}</{wrapper}>" if wrapper else inner
            new_routes.append(f'        <Route path="{route}" element={{{elem}}} />')
            if not re.search(r"import\s+" + re.escape(local) + r"\s+from", app_jsx):
                new_imports.append(f"import {local} from './pages/{comp}';")
            injected.append(route)
        if not injected:
            return app_jsx, []
        # ── route anchor: before the catch-all path="*" else before </Routes> ──
        text = app_jsx
        block = "\n".join(new_routes)
        m_star = re.search(r"""[ \t]*<Route\s+path=["']\*["']""", text)
        idx_close = text.find("</Routes>")
        if m_star:
            text = text[:m_star.start()] + block + "\n" + text[m_star.start():]
        elif idx_close != -1:
            text = text[:idx_close] + block + "\n" + text[idx_close:]
        else:
            return app_jsx, []  # no confident anchor → skip, never guess
        # ── imports: after the last top-of-file import line (positions above the
        # injected routes are unshifted, so re-scan is safe) ──
        if new_imports:
            imps = list(re.finditer(r"^import .*$", text, re.M))
            ins = "\n".join(new_imports)
            if imps:
                end = imps[-1].end()
                text = text[:end] + "\n" + ins + text[end:]
            else:
                text = ins + "\n" + text
        return text, injected
    except Exception:
        return app_jsx, []


def _ensure_framework_auth_pages(ui_pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The framework OWNS the auth UI: /auth/register + /auth/login are
    framework-scaffolded, and the frontend lane consistently ships a dead/unwired
    login (no submit, no API call) or omits /signup entirely (youtube run #20/#21:
    the test-user walkthrough can't register → can't log in → the whole UI is
    unusable). Force a functional /login AND /signup into the contract, DROPPING any
    lane-declared page on those routes so the framework's wired auth form always
    wins the route. Universal + deterministic; no app-specific assumptions."""
    auth_routes = {"/login", "/signup"}
    kept = [p for p in (ui_pages or [])
            if isinstance(p, dict)
            and str(p.get("route") or "").strip().rstrip("/").lower() not in auth_routes]
    auth = [
        {"id": "login_page", "route": "/login", "component": "LoginPage", "name": "Login"},
        {"id": "signup_page", "route": "/signup", "component": "SignupPage", "name": "Signup"},
    ]
    return auth + kept


def scaffold_pages_from_contract(frontend_dir, ui_pages: List[Dict[str, Any]]) -> Dict[str, object]:
    """Project one page-component STUB per registered ui_page + wire React-Router
    routes in App.jsx — the frontend analogue of the deterministic backend
    skeleton (models/db/schemas/main from the endpoint+table contract).

    Closes the build-asymmetry root cause (youtube run #13): the backend is
    framework-scaffolded from its contract so it completes reliably, but the
    frontend had to hand-author all N pages + routing from scratch — it built 1
    page, left 15 in_progress, and declared a hallucinated 'done' (blank shell →
    frontend_navigable gate = 0). With the contract projected to stubs + routes,
    the lane FILLS page bodies (write/edit) instead of authoring from nothing, and
    the app is navigable-by-construction the moment kickoff finalizes.

    Safety: page stubs are written ONLY when missing (never clobber a real page).
    App.jsx is (re)written ONLY when missing/empty or it still carries the
    ``@framework-managed-routes`` marker (the social-shaped baseline shell carries
    it; a lane that takes over routing deletes the marker → never overwritten).
    Idempotent + domain-agnostic. Best-effort; never raises."""
    try:
        frontend_dir = Path(frontend_dir)
        src = frontend_dir / "src"
        if not src.exists():
            return {"scaffolded": [], "routes": 0, "app_wired": False,
                    "skipped": "no src/ (baseline not scaffolded yet)"}
        pages_dir = src / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)

        # Framework OWNS the auth UI: force a functional /login + /signup (the lane
        # ships dead/unwired login pages or omits /signup → unusable app). Only when
        # there are pages to scaffold — an empty contract stays a no-op (don't write
        # a premature auth-only App.jsx before the contract is ready).
        if ui_pages:
            ui_pages = _ensure_framework_auth_pages(ui_pages)

        scaffolded: List[str] = []
        entries: List[tuple] = []
        plan: List[tuple] = []
        seen_components: Set[str] = set()
        used_routes: Set[str] = set()
        for i, page in enumerate(ui_pages or []):
            if not isinstance(page, dict):
                continue
            comp = _page_component_name(page)
            if comp in seen_components:
                continue
            seen_components.add(comp)
            route = str(page.get("route") or "").strip()
            if not route:
                nm = re.sub(r"[^a-z0-9]+", "-",
                            str(page.get("name") or comp).lower()).strip("-")
                route = "/" if not entries else f"/{nm or comp.lower()}"
            # de-dup routes so React-Router doesn't get two identical paths
            base_route, n = route, 2
            while route in used_routes:
                route = f"{base_route.rstrip('/')}/{n}"
                n += 1
            used_routes.add(route)
            entries.append((comp, route))
            plan.append((comp, route, page))

        # Shared top-nav for the data pages: the main business routes (skip auth /
        # landing / param-detail routes, dedup, cap), labelled from the route segment.
        # Built from ALL entries FIRST so every projected page links to the same set —
        # makes the app NAVIGABLE (the disconnected-pages symptom the user hit).
        nav_routes: List[tuple] = []
        _nav_seen: Set[str] = set()
        for _c, _r, _pg in plan:
            if (":" in _r or "{" in _r or _r in ("/", "")
                    or _is_auth_page(_c, _pg) or _is_landing_page(_c, _pg)):
                continue
            if _r in _nav_seen:
                continue
            _nav_seen.add(_r)
            _seg = _r.strip("/").split("/")[0]
            _lbl = re.sub(r"[-_]+", " ", _seg).strip().title() or _seg
            nav_routes.append((_lbl, _r))
        nav_routes = nav_routes[:7]

        for comp, route, page in plan:
            target = pages_dir / f"{comp}.jsx"
            # Auth pages are ALWAYS (over)written with the framework's wired auth
            # form — the lane consistently ships a dead/unwired login. Other pages
            # are projected only when missing (never clobber the lane's real UI).
            if _is_auth_page(comp, page) or not target.exists():
                # Project a minimally-FUNCTIONAL page from the contract (fetches the
                # declared endpoint + renders it), not an inert stub the audit then
                # blocks. The lane may still overwrite it with richer UI.
                target.write_text(_project_page_component(comp, page, nav_routes=nav_routes),
                                  encoding="utf-8")
                scaffolded.append(str(target.relative_to(frontend_dir)))

        app_wired = False
        injected_routes: List[str] = []
        if entries:
            app = src / "App.jsx"
            existing = ""
            if app.exists():
                try:
                    existing = app.read_text(encoding="utf-8")
                except Exception:
                    existing = ""
            # PROPOSAL #39 (G1): ALSO regenerate when App.jsx has NO router at all
            # (`</Routes>` absent). Run #36: the lane shipped a 24-line hand-rolled STUB
            # App.jsx — no <Routes>, marker dropped — so this branch fell to the additive
            # `project_missing_ui_routes` below, which needs an existing `</Routes>` to
            # inject before and thus NO-OPPED → every declared ui_page stayed orphaned →
            # /register,/notes rendered BLANK. A marker-less, router-less App.jsx is not a
            # legitimate "lane took over routing" — it's broken (guaranteed blank pages), so
            # regenerate the router (wiring every declared page). A real lane router HAS
            # `</Routes>` → preserved (additive path), so this never clobbers genuine custom
            # routing/layout.
            if (not existing.strip()) or (_ROUTES_MARKER in existing) or ("</Routes>" not in existing):
                app.write_text(_render_routed_app(entries), encoding="utf-8")
                app_wired = True
            else:
                # PROPOSAL #19: the lane took over App.jsx (dropped the marker) WITH a real
                # router. DON'T clobber its routing/bodies — but ADDITIVELY inject any
                # DECLARED route it omitted (the stubs above guarantee each component file
                # exists), so every declared ui_page is navigable-by-construction even when
                # the lane diverges (run #2: lane wired /feed/you, omitted declared
                # /feed/library → delivery hard-blocked forever). Frontend twin of the
                # backend's additive project_missing_routes. Idempotent; never clobbers.
                new_text, injected_routes = project_missing_ui_routes(existing, ui_pages)
                if injected_routes:
                    app.write_text(new_text, encoding="utf-8")
        return {"scaffolded": sorted(scaffolded), "routes": len(entries),
                "app_wired": app_wired, "injected_routes": injected_routes}
    except Exception as exc:  # never raise into the orchestrator
        return {"scaffolded": [], "routes": 0, "app_wired": False,
                "error": str(exc)}


# FIX #40: framework-owned frontend BASELINE. The frontend lane is the least
# reliable lane — it variably produces nothing (empty app/frontend/, no
# Dockerfile → docker build can't even start → docker_up FAIL → no delivery).
# The frontend INFRASTRUCTURE (Dockerfile/nginx/start.sh/package.json/vite/
# tailwind) is standard, not app-specific, so the framework owns it; we also ship
# a minimal but real login+feed UI that exercises the framework /auth/* + /api/*
# so an empty-frontend run still delivers a working app. Gap-filling: every file
# is written ONLY when missing/empty, so a lane that DID produce code is never
# clobbered (its api.js drift is still healed by repair_frontend_api_exports).

_BASELINE_DOCKERFILE = """FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
# --legacy-peer-deps: lane-authored package.json frequently mixes dev-tool
# versions with conflicting peer ranges (live 2026-06-10: eslint@9 vs
# eslint-plugin-react-hooks@4 wanting eslint<=8 → ERESOLVE → the whole
# frontend image failed). Peer strictness on dev tooling must never block
# the container build; the build's real arbiter is vite build below.
RUN npm install --legacy-peer-deps
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY start.sh /start.sh
RUN chmod +x /start.sh
EXPOSE 3000
CMD ["/start.sh"]
"""

_BASELINE_NGINX = """server {
    listen ${UI_PORT};
    root /usr/share/nginx/html;

    location /api          { proxy_pass ${API_URL}; proxy_http_version 1.1; proxy_set_header Host $host; }
    location /auth         { proxy_pass ${API_URL}; proxy_http_version 1.1; proxy_set_header Host $host; }
    location /oauth        { proxy_pass ${API_URL}; proxy_http_version 1.1; proxy_set_header Host $host; }
    location /.well-known  { proxy_pass ${API_URL}; proxy_http_version 1.1; proxy_set_header Host $host; }
    # Vite emits CONTENT-HASHED filenames under /assets (index-<hash>.js) — a new build gets a new
    # URL, so these are safe to cache forever. immutable stops needless refetches.
    location /assets/      { add_header Cache-Control "public, max-age=31536000, immutable"; }
    # index.html + every SPA route MUST NOT be cached: a browser that reuses a stale index.html
    # references an OLD JS hash, so a rebuilt app "doesn't show the change" — the #1 false bug
    # (PIPELINE.md §5.3/§9). no-store forces a fresh index (→ current bundle) on every load, which
    # eliminates the whole stale-tab / ?v=-bump class deterministically.
    location /             { try_files $uri $uri/ /index.html; add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0"; }
}
"""

_BASELINE_START = """#!/bin/sh
set -e
: "${UI_PORT:=3000}"
: "${API_URL:=http://backend:8081}"
envsubst '${UI_PORT} ${API_URL}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf
exec nginx -g 'daemon off;'
"""

_BASELINE_PACKAGE_JSON = """{
  "name": "app-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": { "dev": "vite", "build": "vite build", "preview": "vite preview" },
  "dependencies": { "react": "^18.3.1", "react-dom": "^18.3.1" },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.1",
    "autoprefixer": "^10.4.19",
    "postcss": "^8.4.38",
    "tailwindcss": "^3.4.4",
    "vite": "^5.3.1"
  }
}
"""

_BASELINE_VITE = r"""import { defineConfig } from 'vite'
// JSX via Vite's BUILT-IN esbuild automatic runtime — NOT @vitejs/plugin-react.
// Round 44 white-screen: plugin-react failed to install (ERESOLVE) → vite fell
// back to esbuild CLASSIC jsx (React.createElement) with no React import →
// "React is not defined" → every page blank. The automatic runtime compiles
// JSX to react/jsx-runtime (no React global needed) and depends on NO external
// plugin, so a missing plugin-react can never blank the UI again.

// safeIconImports: LLM frontends routinely import HALLUCINATED named icons from
// icon libraries (youtube 2026-06-20: `import { ClosedCaption } from
// 'lucide-react'` — not a real export → Rollup "is not exported" → vite build
// fails → docker_up FAILED → no delivery). Route every NAMED icon-lib import
// through a virtual module that re-exports the REAL icon when it exists and a
// generic SVG fallback when it does not, so a wrong icon name degrades to a
// placeholder instead of breaking the whole build. Fully general: no embedded
// list of valid names; real icons still render; only bad names degrade.
function safeIconImports() {
  const ICON_LIB = /^(lucide-react|@heroicons\/react(\/.*)?|react-icons\/.+|@tabler\/icons-react|@radix-ui\/react-icons)$/;
  const V = '\0safe-icon:';
  return {
    name: 'safe-icon-imports',
    enforce: 'pre',
    transform(code, id) {
      if (id.includes('node_modules') || !/\.(jsx?|tsx?)$/.test(id)) return null;
      if (code.indexOf('import') === -1) return null;
      let changed = false;
      const out = code.replace(
        /import\s*\{([^}]*)\}\s*from\s*['"]([^'"]+)['"]/g,
        (m, names, src) => {
          if (!ICON_LIB.test(src)) return m;
          changed = true;
          const enc = src + '::' + names.replace(/\s+/g, ' ').trim();
          return 'import {' + names + '} from ' + JSON.stringify(V + enc);
        });
      return changed ? { code: out, map: null } : null;
    },
    resolveId(id) { return id.startsWith(V) ? id : null; },
    load(id) {
      if (!id.startsWith(V)) return null;
      const body = id.slice(V.length);
      const sep = body.indexOf('::');
      const src = body.slice(0, sep);
      const specs = body.slice(sep + 2).split(',').map((s) => s.trim()).filter(Boolean);
      const lines = [
        "import React from 'react';",
        'import * as _real from ' + JSON.stringify(src) + ';',
        "const _F = React.forwardRef((p, r) => React.createElement('svg', Object.assign({ ref: r, width: 24, height: 24, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2 }, p), React.createElement('circle', { cx: 12, cy: 12, r: 10 })));",
      ];
      // The rewritten import KEEPS its `as` alias, so it references the REAL
      // export name (`import { Calendar as CalendarIcon }` asks the virtual
      // module for export `Calendar`, binding it locally as CalendarIcon). So
      // the module must export the REAL name — exporting the LOCAL (alias) name
      // here made every aliased icon import fail with "<real> is not exported"
      // → vite build fail → docker_up wedge → no delivery (outlook 2026-06-30).
      // Dedup so `{ X, X as Y }` (both reference export X) does not double-export.
      const _seen = {};
      for (const sp of specs) {
        const real = sp.split(/\s+as\s+/)[0].trim();
        if (!real || _seen[real]) continue;
        _seen[real] = 1;
        lines.push('export const ' + real + ' = _real[' + JSON.stringify(real) + '] || _F;');
      }
      return lines.join('\n') + '\n';
    },
  };
}

export default defineConfig({
  plugins: [safeIconImports()],
  esbuild: { jsx: 'automatic', jsxImportSource: 'react' },
  build: { outDir: 'dist' },
})
"""

# tailwind.config.js is framework-PINNED (FIX #44: lanes broke dep VERSIONS). But the
# THEME (design tokens — the colors the lane @apply's, e.g. `bg-ig-bg`) is legitimately
# the frontend's to own, and a pinned EMPTY theme made `@apply <custom-class>` fail the
# build with NO way for the lane to fix it (write to this file is denied → build fails
# forever; run v15/v16: index.css `@apply bg-ig-bg` → "class does not exist"). So this
# pinned config IMPORTS the theme tokens from a frontend-WRITABLE `tailwind.theme.js`
# (create-if-missing, never force-overwritten), separating locked tooling from the lane's
# design palette. Missing/empty theme → {} (no custom tokens; standard utilities still work).
_BASELINE_TAILWIND = """import theme from './tailwind.theme.js'
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: { extend: theme || {} },
  plugins: [],
}
"""

# Frontend-WRITABLE design tokens (NOT in _FRONTEND_FORCE_INFRA, NOT write-denied). The
# lane defines its palette here — e.g. `export default { colors: { 'ig-bg': '#000000',
# 'ig-text': '#f5f5f5', 'ig-blue': '#0095F6' } }` — and tailwind.config.js imports it,
# so `@apply bg-ig-bg` resolves. Projected empty once; the lane fills it; preserved.
_BASELINE_TAILWIND_THEME = "export default {}\n"

_BASELINE_POSTCSS = """export default { plugins: { tailwindcss: {}, autoprefixer: {} } }
"""

_BASELINE_INDEX_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>__APP_NAME__</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
"""

_BASELINE_INDEX_CSS = "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n"

_BASELINE_MAIN_JSX = """import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'
ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode><App /></React.StrictMode>
)
"""

_BASELINE_API_JS = """// Minimal API client. nginx proxies /api,/auth,/oauth to the backend (same-origin).
function authHeaders() {
  const t = localStorage.getItem('token')
  return t ? { Authorization: `Bearer ${t}` } : {}
}
export async function register({ username, email, password, full_name }) {
  const r = await fetch('/auth/register', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, email, password, full_name }),
  })
  const d = await r.json().catch(() => ({}))
  if (d.access_token) localStorage.setItem('token', d.access_token)
  return d
}
export async function login({ email, username, password }) {
  const r = await fetch('/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, username, password }),
  })
  const d = await r.json().catch(() => ({}))
  if (d.access_token) localStorage.setItem('token', d.access_token)
  return d
}
export function logout() { localStorage.removeItem('token') }
// Generic fixed-envelope CRUD helpers (the projector returns {item}/{items}); pages may
// import these by name OR use the default `api` object (api.get/post/...).
async function request(path, { method = 'GET', body } = {}) {
  const r = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  })
  const d = await r.json().catch(() => ({}))
  if (!r.ok) throw Object.assign(new Error(d.detail || r.statusText), { status: r.status, data: d })
  return d
}
export const get = (path) => request(path)
export const post = (path, body) => request(path, { method: 'POST', body })
export const put = (path, body) => request(path, { method: 'PUT', body })
export const del = (path) => request(path, { method: 'DELETE' })
// #41: default export so `import api from '../services/api'` (a common lane style) yields a
// usable object — without it the module resolves but `api` is undefined → runtime crash.
const api = { register, login, logout, get, post, put, del, request }
export default api
"""

_ROUTES_MARKER = "// @framework-managed-routes"

_BASELINE_APP_JSX = """// @framework-managed-routes
import React, { useState } from 'react'
import { register, login, logout } from './services/api.js'

export default function App() {
  const [token, setToken] = useState(localStorage.getItem('token'))
  const [mode, setMode] = useState('login')
  const [form, setForm] = useState({ username: '', email: '', password: '' })

  async function submit(e) {
    e.preventDefault()
    const fn = mode === 'register' ? register : login
    const d = await fn(form)
    if (d.access_token) setToken(d.access_token)
  }
  function doLogout() { logout(); setToken(null) }

  if (!token) {
    return (
      <div className="min-h-screen bg-zinc-50 text-zinc-900 flex items-center justify-center">
        <form onSubmit={submit} className="w-80 space-y-3 p-6 border border-zinc-200 bg-white rounded-xl shadow-sm">
          <h1 className="text-3xl font-bold text-center mb-2">__APP_NAME__</h1>
          <input className="w-full p-2 bg-white rounded border border-zinc-300 focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="username" value={form.username}
            onChange={e => setForm({ ...form, username: e.target.value })} />
          <input className="w-full p-2 bg-white rounded border border-zinc-300 focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="email" value={form.email}
            onChange={e => setForm({ ...form, email: e.target.value })} />
          <input className="w-full p-2 bg-white rounded border border-zinc-300 focus:outline-none focus:ring-2 focus:ring-blue-500"
            type="password" placeholder="password" value={form.password}
            onChange={e => setForm({ ...form, password: e.target.value })} />
          <button className="w-full p-2 bg-blue-600 hover:bg-blue-700 text-white rounded font-semibold">
            {mode === 'register' ? 'Sign up' : 'Log in'}
          </button>
          <button type="button" className="w-full text-sm text-blue-600"
            onClick={() => setMode(mode === 'register' ? 'login' : 'register')}>
            {mode === 'register' ? 'Have an account? Log in' : 'New? Sign up'}
          </button>
        </form>
      </div>
    )
  }
  return (
    <div className="min-h-screen bg-zinc-50 text-zinc-900">
      <header className="flex justify-between items-center p-4 border-b border-zinc-200 sticky top-0 bg-white">
        <h1 className="text-xl font-bold">__APP_NAME__</h1>
        <button className="text-sm text-blue-600" onClick={doLogout}>Log out</button>
      </header>
      <main className="max-w-xl mx-auto p-8 text-center text-zinc-500">
        <p>You are signed in.</p>
      </main>
    </div>
  )
}
"""

_BC_AUTH_GUARD_JS = """// Global auth guard: any /api/ 401 redirects to /login. Patches BOTH fetch and
// XMLHttpRequest — lanes write their api layer with either (axios uses XHR).
function _bcOn401(url) {
  if (String(url).includes('/api/')
      && !['/login', '/register', '/signup'].includes(window.location.pathname)) {
    localStorage.removeItem('token');
    window.location.assign('/login');
  }
}
const _origFetch = window.fetch.bind(window);
window.fetch = async (input, init) => {
  const res = await _origFetch(input, init);
  if (res.status === 401) _bcOn401(typeof input === 'string' ? input : (input && input.url) || '');
  return res;
};
const _origOpen = XMLHttpRequest.prototype.open;
XMLHttpRequest.prototype.open = function (method, url, ...rest) {
  this.addEventListener('load', () => { if (this.status === 401) _bcOn401(url); });
  return _origOpen.call(this, method, url, ...rest);
};
"""

_BASELINE_FILES = {
    "Dockerfile": _BASELINE_DOCKERFILE,
    "nginx.conf.template": _BASELINE_NGINX,
    "start.sh": _BASELINE_START,
    "package.json": _BASELINE_PACKAGE_JSON,
    "vite.config.js": _BASELINE_VITE,
    "tailwind.config.js": _BASELINE_TAILWIND,
    "tailwind.theme.js": _BASELINE_TAILWIND_THEME,
    "postcss.config.js": _BASELINE_POSTCSS,
    "index.html": _BASELINE_INDEX_HTML,
    "src/index.css": _BASELINE_INDEX_CSS,
    "src/main.jsx": _BASELINE_MAIN_JSX,
    "src/services/api.js": _BASELINE_API_JS,
    "src/App.jsx": _BASELINE_APP_JSX,
}


# FIX #44: the frontend BUILD TOOLING is infra, not app code — but the lane writes
# it, and writes it badly (5.5 pinned every dep to "latest", so tailwindcss=latest
# pulled v4 while the postcss config is v3-style → `npm run build` dies). The
# framework owns the tooling: force the pure-infra config files to known-good and
# PIN the build-tooling deps to compatible versions, while preserving the lane's
# src/ + any extra app deps (lucide-react, etc.). Guarantees the frontend builds.
_FRONTEND_TOOLING_PINS = {
    "react": "^18.3.1", "react-dom": "^18.3.1",
    "vite": "^5.3.1", "@vitejs/plugin-react": "^4.3.1",
    "tailwindcss": "^3.4.4", "postcss": "^8.4.38", "autoprefixer": "^10.4.19",
}

# Common, REAL frontend libraries a lane may import that aren't in the baseline
# package.json (which the lane can't edit — it's framework-owned). A bare import
# of one of these used to fail the vite/Rollup build → docker_up FAILED forever →
# no release (live smoke-notes 2026-06-20: `import "date-fns"` in NoteCard.jsx →
# "Rollup failed to resolve import 'date-fns'"). Auto-adding the imported ones
# from THIS curated, version-pinned set makes the build resolve. Only known-real
# packages are added (a hallucinated import is left to fail honestly rather than
# breaking `npm install`).
_COMMON_FRONTEND_LIBS = {
    "date-fns": "^3.6.0", "dayjs": "^1.11.11", "moment": "^2.30.1",
    "axios": "^1.7.2", "clsx": "^2.1.1", "classnames": "^2.5.1",
    "lodash": "^4.17.21", "lodash-es": "^4.17.21", "zustand": "^4.5.4",
    "react-icons": "^5.2.1", "uuid": "^9.0.1", "nanoid": "^5.0.7",
    "react-hook-form": "^7.52.1", "zod": "^3.23.8", "yup": "^1.4.0",
    "recharts": "^2.12.7", "chart.js": "^4.4.3", "react-chartjs-2": "^5.2.0",
    "@tanstack/react-query": "^5.51.1", "swr": "^2.2.5",
    "framer-motion": "^11.3.2", "react-hot-toast": "^2.4.1",
    "react-toastify": "^10.0.5", "qs": "^6.12.1", "js-cookie": "^3.0.5",
    # icon / UI / animation libs LLM frontends reach for constantly
    "lucide-react": "^0.408.0", "@heroicons/react": "^2.1.4",
    "@headlessui/react": "^2.1.2", "react-router": "^6.26.0",
}

# Roots the framework already provides (declared as deps by construction) — never
# re-add or "latest"-pin these.
_FRAMEWORK_FRONTEND_ROOTS = {"react", "react-dom", "react-router-dom"}

# import X from 'pkg'  /  import 'pkg'  /  } from "pkg"  — captures the bare
# specifier; relative ('./', '../', '/') imports are ignored by the caller.
_BARE_IMPORT_RE = re.compile(
    r"""(?:from|import)\s+['"]([^'"]+)['"]""")

# A real, installable npm package root: optional @scope/, lowercase name. Rejects
# virtual/protocol specifiers (node:fs, virtual:uno.css) and anything that isn't a
# plain package name, so the general "latest" fallback never feeds npm garbage.
_INSTALLABLE_PKG_RE = re.compile(
    r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$")


def _is_installable_pkg(root: str) -> bool:
    return bool(root) and ":" not in root and bool(_INSTALLABLE_PKG_RE.match(root))


def _pkg_root(spec: str) -> str:
    """The installable package name from an import specifier: 'date-fns/format'
    -> 'date-fns'; '@scope/pkg/sub' -> '@scope/pkg'."""
    parts = spec.split("/")
    if spec.startswith("@"):
        return "/".join(parts[:2])
    return parts[0]


def _scan_bare_imports(src_dir) -> set:
    """All bare (non-relative) package roots imported under src_dir."""
    found: set = set()
    try:
        root = Path(src_dir)
        if not root.exists():
            return found
        for f in root.rglob("*"):
            if f.suffix not in (".js", ".jsx", ".ts", ".tsx") or not f.is_file():
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except Exception:
                continue
            for spec in _BARE_IMPORT_RE.findall(text):
                if spec and not spec.startswith((".", "/")):
                    found.add(_pkg_root(spec))
    except Exception:
        pass
    return found
_FRONTEND_FORCE_INFRA = {
    "postcss.config.js": _BASELINE_POSTCSS,
    "tailwind.config.js": _BASELINE_TAILWIND,
    "vite.config.js": _BASELINE_VITE,
    "Dockerfile": _BASELINE_DOCKERFILE,
    "nginx.conf.template": _BASELINE_NGINX,
    "start.sh": _BASELINE_START,
}


def pin_frontend_build_tooling(frontend_dir) -> Dict[str, object]:
    """Force the frontend build tooling to known-good versions/configs so the
    image always builds. Overwrites the pure-infra config files and pins the
    build-tooling deps in package.json; preserves src/ + the lane's app deps."""
    try:
        fe = Path(frontend_dir)
        if not fe.exists():
            return {"pinned": False, "reason": "no frontend dir"}
        changed: List[str] = []
        for rel, content in _FRONTEND_FORCE_INFRA.items():
            p = fe / rel
            if (not p.exists()) or p.read_text(encoding="utf-8", errors="ignore") != content:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
                changed.append(rel)
        # The pinned tailwind.config.js IMPORTS ./tailwind.theme.js — guarantee that
        # frontend-writable token file EXISTS (create-if-missing) so the config never
        # fails to load on a fresh tree. Do NOT overwrite it: the lane owns its palette.
        _theme_p = fe / "tailwind.theme.js"
        if not _theme_p.exists():
            _theme_p.write_text(_BASELINE_TAILWIND_THEME, encoding="utf-8")
            changed.append("tailwind.theme.js (created)")
        # CSS wiring is infra too: a lane-written src/main.jsx that omits
        # ``import './index.css'`` ships a bundle with NO stylesheet at all —
        # Tailwind never runs and every page renders as plain links on white
        # (instagram 2026-06-10 08:25). Enforce the import + the directives file.
        main_jsx = fe / "src" / "main.jsx"
        if main_jsx.exists():
            try:
                mtxt = main_jsx.read_text(encoding="utf-8")
                if "index.css" not in mtxt:
                    main_jsx.write_text("import './index.css';\n" + mtxt,
                                        encoding="utf-8")
                    changed.append("src/main.jsx (+index.css import)")
            except Exception:
                pass
        idx_css = fe / "src" / "index.css"
        try:
            if not idx_css.exists() or "@tailwind" not in idx_css.read_text(encoding="utf-8"):
                idx_css.parent.mkdir(parents=True, exist_ok=True)
                idx_css.write_text(_BASELINE_INDEX_CSS, encoding="utf-8")
                changed.append("src/index.css (tailwind directives)")
        except Exception:
            pass
        # Auth UX is infra too: every /api/ route is auth-gated by construction,
        # so an unauthenticated visit must land on /login — not an empty page
        # with a console full of 401s. A global fetch guard guarantees this
        # regardless of how the lane wrote its api helpers.
        try:
            bc_auth = fe / "src" / "bc_auth.js"
            if not bc_auth.exists() or bc_auth.read_text(encoding="utf-8") != _BC_AUTH_GUARD_JS:
                bc_auth.write_text(_BC_AUTH_GUARD_JS, encoding="utf-8")
                changed.append("src/bc_auth.js (401 → /login guard)")
            if main_jsx.exists():
                mtxt = main_jsx.read_text(encoding="utf-8")
                if "bc_auth" not in mtxt:
                    main_jsx.write_text("import './bc_auth.js';\n" + mtxt,
                                        encoding="utf-8")
                    changed.append("src/main.jsx (+bc_auth import)")
        except Exception:
            pass
        import json as _json
        pj = fe / "package.json"
        if pj.exists():
            try:
                data = _json.loads(pj.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            if isinstance(data, dict):
                for sect in ("dependencies", "devDependencies"):
                    d = data.get(sect)
                    if isinstance(d, dict):
                        for pkg, ver in _FRONTEND_TOOLING_PINS.items():
                            if pkg in d:
                                d[pkg] = ver
                dd = data.setdefault("devDependencies", {})
                if isinstance(dd, dict):
                    for pkg in ("tailwindcss", "postcss", "autoprefixer"):
                        if pkg not in (data.get("dependencies") or {}):
                            dd.setdefault(pkg, _FRONTEND_TOOLING_PINS[pkg])
                # Runtime deps the PROJECTED code requires (round 22: a lane
                # that skipped routing shipped no react-router-dom → projected
                # pages' imports failed the vite build).
                deps = data.setdefault("dependencies", {})
                if isinstance(deps, dict):
                    deps.setdefault("react-router-dom", "^6.26.0")
                    # AUTO-ADD EVERY imported third-party lib so the vite build can
                    # resolve it. The lane can't edit package.json (framework-owned),
                    # and a curated allowlist can NEVER cover every lib an app
                    # legitimately uses (youtube 2026-06-20: lucide-react not listed
                    # → Rollup "failed to resolve import" → docker_up FAILED → no
                    # release). Pin the known-common ones for reproducibility; fall
                    # back to "latest" for anything else so NO app is allowlist-
                    # limited. Skip framework-provided roots + already-declared deps;
                    # the installable-name guard keeps node:/virtual: specifiers out.
                    try:
                        _declared = set(deps) | set(data.get("devDependencies") or {})
                        for imp in _scan_bare_imports(fe / "src"):
                            if (imp in _declared or imp in _FRAMEWORK_FRONTEND_ROOTS
                                    or not _is_installable_pkg(imp)):
                                continue
                            ver = _COMMON_FRONTEND_LIBS.get(imp, "latest")
                            deps[imp] = ver
                            _declared.add(imp)
                            changed.append(f"package.json (+{imp}@{ver})")
                    except Exception:
                        pass
                # SCRIPTS are build INFRASTRUCTURE, not lane content (round 46:
                # a lane overwrote package.json with no "scripts" at all →
                # `npm run build` had no build script → docker build failed →
                # docker_up FAILED forever → no release). The Dockerfile runs
                # `vite build`, so force it regardless of what the lane wrote;
                # dev/preview are setdefault so a lane custom is kept.
                if not isinstance(data.get("scripts"), dict):
                    data["scripts"] = {}
                _scripts = data["scripts"]
                _scripts.setdefault("dev", "vite")
                _scripts["build"] = "vite build"
                _scripts.setdefault("preview", "vite preview")
                pj.write_text(_json.dumps(data, indent=2) + "\n", encoding="utf-8")
                changed.append("package.json")
        return {"pinned": bool(changed), "changed": changed}
    except Exception as exc:
        return {"pinned": False, "error": f"{type(exc).__name__}: {exc}"}


def stage_design_assets(output_dir) -> List[str]:
    """Copy the Design-Prep staged real assets ``<output_dir>/design/assets/*`` into the served
    frontend ``<output_dir>/app/frontend/public/assets/`` (Vite serves + bundles ``public/``), so
    the frontend can reference them at ``/assets/<file>``. Preserves icons/ logos/ grouping.
    Returns the copied relative paths; ``[]`` when there is no design/assets. Best-effort."""
    out = Path(output_dir)
    src = out / "design" / "assets"
    if not src.is_dir():
        return []
    dest = out / "app" / "frontend" / "public" / "assets"
    copied: List[str] = []
    for p in sorted(src.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(src)
        try:
            d = dest / rel
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, d)
            copied.append(rel.as_posix())
        except Exception:
            continue
    return copied


def scaffold_frontend_baseline(frontend_dir) -> Dict[str, object]:
    """Gap-fill a minimal buildable Vite+React+Tailwind+nginx frontend. Writes
    each standard file ONLY when missing/empty, so a lane that produced code is
    never clobbered. An empty-frontend run gets a complete login/register auth
    shell that builds + serves and hits the framework /auth/*; declared pages are
    projected functionally from the contract elsewhere. Best-effort."""
    try:
        frontend_dir = Path(frontend_dir)
        frontend_dir.mkdir(parents=True, exist_ok=True)
        written: List[str] = []
        # Design-Prep: stage the real assets (design/assets/) into public/assets/ so the
        # frontend serves them. frontend_dir is <output>/app/frontend → output = parents[1].
        try:
            stage_design_assets(frontend_dir.parent.parent)
        except Exception:
            pass
        # GENERALITY: baseline copy derives the display name from the project
        # directory — the templates carry __APP_NAME__, never a real brand.
        try:
            _app_name = frontend_dir.parent.parent.name.replace("_", " ").replace("-", " ").title() or "App"
        except Exception:
            _app_name = "App"
        for rel, content in _BASELINE_FILES.items():
            content = content.replace("__APP_NAME__", _app_name)
            p = frontend_dir / rel
            try:
                if p.exists() and p.read_text(encoding="utf-8", errors="ignore").strip():
                    continue
            except Exception:
                pass
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            written.append(rel)
        return {"scaffolded": bool(written), "written": written}
    except Exception as exc:
        return {"scaffolded": False, "error": f"{type(exc).__name__}: {exc}"}


__all__ = [
    "repair_frontend_api_exports",
    "scaffold_frontend_baseline",
    "stage_design_assets",
    "pin_frontend_build_tooling",
]
