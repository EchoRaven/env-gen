"""Deterministic api_smoke validation runner (§6, framework-driven).

The verifier used to drive validation as a free-agentic multi-step LLM loop
(docker_up → test_api per endpoint → judge) and reliably STALLED before reaching
the runtime checks (smoke #7). This module is the ``[P]`` (procedural) form from
the §0.5 execution model: ONE deterministic procedure that brings the env up
clean, exercises the embedded-AS auth + every business endpoint, and returns a
structured verdict. The verifier LLM's role shrinks to "call it + record the
verdict" — no multi-step orchestration to drift through.

What it checks (the api_smoke contract):
  1. ``docker compose down -v && up -d --build`` — a CLEAN boot (no stale pg vol).
  2. backend ``/health`` reachable (else the backend crashed → FAIL, with logs).
  3. ``POST /auth/register`` mints an access token (embedded AS works).
  4. every business endpoint is REACHABLE with the token (status < 500 — a 4xx is
     a validation/shape response, NOT a crash; a 5xx or connection error IS a
     failure: the endpoint isn't wired or the handler throws) AND — GATE-C1 —
     actually IMPLEMENTED when its registration says so: a 404/405 from a
     ``status=implemented`` endpoint is a contract lie, not a pass (a 404 on a
     path WITH params stays soft — the probe substitutes dummy ids; endpoints
     not yet claiming implemented, i.e. later-milestone work, stay soft too).
  5. a business endpoint WITHOUT a token returns 401 (auth enforced).

Pure stdlib (subprocess + urllib) so it has no extra deps and runs anywhere the
generator runs. Returns a report; never raises (failures are recorded, not thrown).
"""

from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


def _compose(compose_file: Path, *args: str, cwd: Path, timeout: int = 300) -> subprocess.CompletedProcess:
    # Pin the CLASSIC builder (DOCKER_BUILDKIT=0), matching every other compose-build
    # path (tools/docker_tools._run_compose, tools/_runtime_env, runhub/compose.py).
    # BuildKit's progress writer ELIDES per-step log lines when stdout/stderr is a
    # non-TTY pipe (capture_output=True), so a frontend `[vite:esbuild] Transform
    # failed with 1 error` was captured WITHOUT its file:line code-frame — every lane
    # saw a useless truncated head and re-ran the build blindly until the run wedged
    # on docker_up (smoke-notes 2026-06-19). The classic builder streams full step
    # logs, so the real esbuild error reaches the repair agent.
    import os as _os
    return subprocess.run(
        ["docker", "compose", "-f", str(compose_file), *args],
        cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
        env={**_os.environ, "DOCKER_BUILDKIT": "0", "COMPOSE_DOCKER_CLI_BUILD": "0"},
    )


def _service_host_port(compose_file: Path, cwd: Path, service: str) -> Optional[int]:
    """Resolve the published host port of a compose service."""
    try:
        cid = _compose(compose_file, "ps", "-q", service, cwd=cwd, timeout=30).stdout.strip()
        if not cid:
            return None
        ports = subprocess.run(["docker", "port", cid], capture_output=True, text=True, timeout=30).stdout
        m = re.search(r"(?:0\.0\.0\.0|127\.0\.0\.1|\[::\]):(\d+)", ports)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def _backend_host_port(compose_file: Path, cwd: Path) -> Optional[int]:
    """Resolve the published host port of the ``backend`` service."""
    return _service_host_port(compose_file, cwd, "backend")


def _http(method: str, url: str, *, token: Optional[str] = None,
          body: Optional[dict] = None, timeout: int = 10) -> Dict[str, Any]:
    """One HTTP call → {status, body_text, error}. Never raises."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method.upper())
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"status": r.status, "body_text": r.read(2048).decode("utf-8", "replace"), "error": None}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "body_text": (e.read(2048).decode("utf-8", "replace") if e.fp else ""), "error": None}
    except Exception as e:
        return {"status": None, "body_text": "", "error": f"{type(e).__name__}: {e}"}


def _expected_shape(method: str, path: str) -> Optional[str]:
    """The response-contract shape an endpoint MUST return, derived deterministically
    from method+path (mirrors route_projector's single-vs-collection split):
      - ``"item"`` (single resource → ``{"item": {...}}``): any write
        (POST/PUT/PATCH/DELETE), a GET ending in ``/me``, or a GET ending in a path
        param (``/{id}``).
      - ``"items"`` (collection → ``{"items": [...]}``): any other GET.
    Returns ``None`` when the shape is genuinely ambiguous → skip the assertion."""
    m = method.upper()
    if m in ("POST", "PUT", "PATCH", "DELETE"):
        return "item"
    if m != "GET":
        return None
    last = next((s for s in reversed(path.split("/")) if s), "")
    if last == "me" or (last.startswith("{") and last.endswith("}")) or last.startswith(":"):
        return "item"
    return "items"


def _shape_violation(method: str, path: str, status: Optional[int],
                     body_text: str) -> Optional[str]:
    """Return a violation message if a 2xx response's shape contradicts the contract
    for its path-type, else None. Conservative — only a clear single↔collection
    mismatch is flagged; a custom/other shape (no item/items key) is left alone."""
    expected = _expected_shape(method, path)
    if not expected or not status or not (200 <= status < 300):
        return None
    try:
        payload = json.loads(body_text or "{}")
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if expected == "item" and "items" in payload and "item" not in payload:
        return f"{method} {path} → returns a list (items) but the contract is a single item"
    if expected == "items" and "item" in payload and "items" not in payload:
        return f"{method} {path} → returns a single item but the contract is a list (items)"
    return None


def _path_with_params(path: str, sample: str = "1") -> str:
    """Substitute path params ({id}/:id/${id}) with a sample value for smoke."""
    path = re.sub(r"\$\{[^}/]+\}", sample, path)
    path = re.sub(r"\{[^}/]+\}", sample, path)
    path = re.sub(r":[A-Za-z_]\w*", sample, path)
    return path


def _unimplemented_route(method: str, path: str, ep_status: Any,
                         status_code: Optional[int]) -> Optional[str]:
    """Return a violation message when an endpoint REGISTERED as
    ``status=implemented`` answers 404/405 — the route isn't actually wired, a
    contract lie the bare <500 rule counted as a pass (GATE-C1: the single
    trigger that lit ``functionally_validated`` and degraded the coverage/seed/
    visual/ui_flow delivery gates to warnings).

    Calibrated on generated/instagram round47 (768 contract-test records of the
    released app):
      * a 404 on a path WITH params stays soft — the probe substitutes dummy
        ids ("1"), so the parent resource may legitimately not exist (GET
        /api/users/{username}/posts 404s because user "1" is absent; the
        exemption is contains-a-param, NOT ends-with-param — that endpoint ends
        in /posts and would otherwise be a false FAIL).
      * a 404 on a param-less path = the route is not registered → FAIL.
      * a 405 = the path matched but the METHOD isn't wired → FAIL, params or
        not (never appears on a working app).
    Endpoints not yet claiming implemented (defined/implementing/revising —
    later-milestone or in-revision work) keep the soft <500 rule."""
    if status_code not in (404, 405):
        return None
    if str(ep_status or "").lower() != "implemented":
        return None
    if status_code == 404 and _path_with_params(path) != path:
        return None
    why = ("route not registered" if status_code == 404
           else "path matched but the method is not wired")
    return (f"{method} {path} → {status_code} but registered status=implemented "
            f"({why}) — implement the route or deprecate the registration")


def _frontend_navigable(project_dir: Any) -> "tuple[bool, str]":
    """The frontend gate's predicate: the shipped UI must have at least one page
    component AND at least one <Route> in the app shell — else it renders a blank
    page no matter how healthy the backend is."""
    fe_src = Path(project_dir) / "app" / "frontend" / "src"
    # GENERALITY (round 34): with no framework templates the lane chooses its
    # own layout (components/, views/, features/...) — counting only
    # src/pages/*.jsx failed a working app that kept page components in
    # components/. A "page" here is ANY .jsx component file under src/
    # besides the entry files.
    n_pages = len([f for f in fe_src.rglob("*.jsx")
                   if f.name not in ("App.jsx", "main.jsx")]) if fe_src.is_dir() else 0
    app_jsx = fe_src / "App.jsx"
    n_routes = 0
    if app_jsx.exists():
        try:
            n_routes = len(re.findall(r"<Route\s", app_jsx.read_text(encoding="utf-8")))
        except Exception:
            n_routes = 0
    ok = n_pages >= 1 and n_routes >= 1
    detail = f"{n_pages} page component(s), {n_routes} route(s)" + (
        "" if ok else " — the frontend is a blank shell; pages/routes must exist before release")
    return ok, detail


def _probe_body(ep: Any) -> dict:
    """Build a create-probe request body from the endpoint's REGISTERED request
    schema — domain-agnostic. Sends exactly the fields the contract declares, with
    type-appropriate placeholders, so the persistence probe works for ANY app (a
    task app's ``{title, description}``, a docs app's ``{title, body}``), not only
    social/instagram-shaped create endpoints. Falls back to common generic text
    fields when no request schema is registered (still NOT app-specific)."""
    req = (ep.get("schema") or {}).get("request") if isinstance(ep, dict) else None
    body: dict = {}
    if isinstance(req, dict):
        for field, typ in req.items():
            t = str(typ).lower().strip().rstrip("?").strip()
            if t.endswith("[]") or t.startswith("list") or "array" in t:
                body[field] = []
            elif t.startswith("{") or "dict" in t or "object" in t:
                body[field] = {}
            elif "bool" in t:
                body[field] = True
            elif "float" in t or "decimal" in t or "double" in t:
                body[field] = 1.0
            elif "int" in t or t in ("number", "integer"):
                body[field] = 1
            else:
                body[field] = "persist-probe"
    if not body:
        # no registered request schema → generic best-effort, domain-agnostic
        body = {"name": "persist-probe", "title": "persist-probe",
                "description": "persist-probe", "text": "persist-probe",
                "content": "persist-probe"}
    return body


def run_smoke_validation(
    project_dir: Any,
    business_endpoints: List[Mapping[str, Any]],
    *,
    up_timeout: int = 300,
    health_timeout: int = 90,
    teardown: bool = True,
) -> Dict[str, Any]:
    """Run the deterministic api_smoke. Returns a structured report:

        {"passed": bool, "summary": str, "checks": [{name, status, detail}],
         "backend_port": int|None}

    ``business_endpoints`` is a list of ``{method, path}`` (business only — the
    caller filters via ``lifecycle.business_endpoints``)."""
    project_dir = Path(project_dir).resolve()  # absolute → -f path can't double against cwd
    compose_file = project_dir / "docker" / "docker-compose.yml"
    cwd = project_dir / "docker"
    checks: List[Dict[str, Any]] = []
    endpoint_results: List[Dict[str, Any]] = []
    chain_results: List[Dict[str, Any]] = []

    def _add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "status": "pass" if ok else "fail", "detail": detail})

    if not compose_file.exists():
        return {"passed": False, "summary": f"no compose file at {compose_file}",
                "checks": [{"name": "compose_present", "status": "fail", "detail": str(compose_file)}],
                "backend_port": None, "endpoints": []}

    # FRONTEND GATE — a release must ship a NAVIGABLE UI, not a blank shell. The
    # backend has 6 checks below; the frontend previously had ZERO, so an app whose
    # frontend lane authored nothing (0 pages, 0 routes) sailed through api_smoke and
    # released a blank page (instagram 1.0.0, 2026-06-09 — "打不开"). Static + cheap.
    _fe_ok, _fe_detail = _frontend_navigable(project_dir)
    _add("frontend_navigable", _fe_ok, _fe_detail)

    # VISIBILITY (informational): how much of the UI is framework FALLBACK vs lane-authored.
    # The HARD enforcement of "a page the references DEPICT must ship REAL, not the fallback"
    # lives in the reference-aware page_build_gate (pages_release_decision: referenced-unbuilt
    # never escapes), so this check stays informational to avoid double-gating a page that
    # legitimately has no reference to match (its fallback is acceptable).
    try:
        from .frontend_page_projector import _PAGE_MARKER
        _pages_dir = project_dir / "app" / "frontend" / "src" / "pages"
        _total = _fallback = 0
        _fb_names = []
        for _pf in sorted(_pages_dir.glob("*.jsx")) if _pages_dir.is_dir() else []:
            _total += 1
            try:
                if _PAGE_MARKER in _pf.read_text(encoding="utf-8", errors="ignore"):
                    _fallback += 1
                    _fb_names.append(_pf.stem)
            except Exception:
                pass
        _add("frontend_fallback_pages", True,
             f"{_fallback}/{_total} pages are framework fallback ({', '.join(_fb_names[:8])})")
    except Exception:
        pass

    backend_port: Optional[int] = None
    # FIX #36: serialize docker validations. Concurrent boots of the SAME compose
    # project (orchestrator framework-validation + verifier `run_validation`
    # api_smoke) share container names + host ports, so they tear each other down
    # → BOTH report docker_up FAIL ("not yet passing"), and a perfectly
    # deliverable app never validates in-run (confirmed: two concurrent
    # run_smoke_validation calls both fail docker_up). A cross-thread/process file
    # lock makes validations run strictly one-at-a-time.
    import fcntl as _fcntl
    import time as _time
    _lock_fh = None
    _lock_acquired = False
    try:
        cwd.mkdir(parents=True, exist_ok=True)
        _lock_fh = open(cwd / ".smoke_validation.lock", "w")
        _wait_start = _time.time()
        while True:
            try:
                _fcntl.flock(_lock_fh.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                _lock_acquired = True
                break
            except OSError:
                if _time.time() - _wait_start > 600:
                    break  # gave up waiting (do NOT proceed unlocked — see guard below)
                _time.sleep(2)
    except Exception:
        _lock_fh = None
    # FIX #36-bis: if we could NOT acquire the lock within the wait window, another
    # validation has held it that whole time and is presumably mid `down -v`/`up`.
    # Proceeding here would run `down -v && up` CONCURRENTLY against the SAME compose
    # project → both tear each other's containers down → both report docker_up FAIL
    # (the exact race FIX #36's lock exists to prevent). Trading a hang for a race is
    # worse. Defer instead: surface a non-fatal lock_timeout so the framework retries
    # this validation once the lock frees, rather than corrupting a deliverable app.
    if not _lock_acquired:
        _add("docker_up", False,
             "smoke-validation lock not acquired within 600s — another validation is "
             "holding it; deferring to avoid a concurrent docker down/up race (will retry).")
        return _finalize(checks, None, endpoint_results)
    try:
        # 1. Clean boot (no stale postgres volume — see DockerUpTool fresh=True).
        _compose(compose_file, "down", "-v", "--remove-orphans", cwd=cwd, timeout=120)
        up = _compose(compose_file, "up", "-d", "--build", "--remove-orphans", cwd=cwd, timeout=up_timeout)
        if up.returncode != 0:
            # S1 (PROPOSAL #3): `docker compose up`'s OWN stderr is often just a
            # benign warning (e.g. "attribute `version` is obsolete") while the REAL
            # failure is a container that crashed during init — e.g. postgres exit 3
            # on a malformed DDL (youtube run #16: the truncated up-stderr surfaced
            # ONLY the version warning and HID the exit-3 crash for many rounds).
            # Also capture the per-container logs (mirrors backend_health at the
            # /health-timeout branch) so the failure detail shows the ROOT, not the
            # warning. Service-agnostic: `logs` with no service = every container.
            # CLASS A (#36): on a BUILD failure (e.g. apt exit 100) the root cause is in
            # the build transcript, NOT the brief "failed to solve … exit code N" summary,
            # and `compose logs` is empty (no container booted). A 400-char tail of ONE
            # stream hid the apt error in run #34 → agents re-ran validation blindly ("the
            # output got truncated … I need the full stack trace"). Capture a generous
            # tail of BOTH streams so the lane sees the actual error.
            _up_detail = (((up.stdout or "") + "\n" + (up.stderr or "")).strip())[-3000:]
            try:
                _clogs = _compose(compose_file, "logs", "--tail", "40", cwd=cwd, timeout=30)
                _ctail = (_clogs.stdout or _clogs.stderr or "")[-1500:]
            except Exception:
                _ctail = ""
            _detail = _up_detail + (
                "\n--- container logs (tail) ---\n" + _ctail if _ctail else "")
            _add("docker_up", False, _detail)
            return _finalize(checks, backend_port, endpoint_results)
        _add("docker_up", True)

        backend_port = _backend_host_port(compose_file, cwd)
        if not backend_port:
            _add("backend_port", False, "could not resolve backend published port")
            return _finalize(checks, backend_port, endpoint_results)

        base = f"http://localhost:{backend_port}"

        # 2. /health (backend actually serves — catches boot crashes).
        healthy = False
        deadline = time.monotonic() + health_timeout
        while time.monotonic() < deadline:
            h = _http("GET", f"{base}/health", timeout=5)
            if h["status"] == 200:
                healthy = True
                break
            time.sleep(3)
        if not healthy:
            logs = _compose(compose_file, "logs", "--tail", "30", "backend", cwd=cwd, timeout=30)
            _add("backend_health", False, "/health not 200 within timeout. logs:\n" + (logs.stdout or logs.stderr)[-1200:])
            return _finalize(checks, backend_port, endpoint_results)
        _add("backend_health", True)

        # 3. Register via the embedded AS → token. FIX #33: send a COMPLETE
        #    common registration payload. username-based auth is the dominant web
        #    convention (social apps, etc.), and Pydantic ignores extra fields
        #    while accepting the ones the app's model requires — so a single
        #    superset payload satisfies both email-only and username-requiring
        #    register models. The old {email,password,name}-only body made the
        #    gate 422 ("missing username") on any app whose register needs a
        #    username, blocking delivery of an otherwise-working app.
        def _tok(txt: str) -> Optional[str]:
            try:
                d = json.loads(txt)
            except Exception:
                return None
            if not isinstance(d, dict):
                return None
            return d.get("access_token") or d.get("token") or d.get("accessToken")

        _cred = {
            "username": "smoke_user", "email": "smoke@virtueai.com",
            "password": "smoke-pw-12345", "name": "Smoke", "full_name": "Smoke User",
        }
        reg = _http("POST", f"{base}/auth/register", body=_cred)
        token = _tok(reg["body_text"]) if reg["status"] in (200, 201) else None
        if not token:
            # register may not mint a token, or the user already exists → login.
            # Send username + email both so username- or email-login both resolve.
            login = _http("POST", f"{base}/auth/login",
                          body={"username": "smoke_user", "email": "smoke@virtueai.com",
                                "password": "smoke-pw-12345"})
            token = _tok(login["body_text"])
        _add("auth_register_login", bool(token),
             "" if token else f"register={reg['status']} + login; no access_token ({reg['body_text'][:200]})")
        if not token:
            return _finalize(checks, backend_port, endpoint_results)

        # 4. Every business endpoint reachable (status < 500 = no crash) AND —
        #    GATE-C1 — actually implemented when its registration claims so:
        #    a 404/405 from a status=implemented endpoint fails the smoke (see
        #    _unimplemented_route for the round47-calibrated exemptions).
        #    Collect a per-endpoint result so the caller can emit one
        #    contract-test record per endpoint (the delivery-gate evidence) —
        #    ``reachable`` stays the transport fact (<500); ``passed`` is the
        #    verdict the probe/contract-test records consume.
        unreachable: List[str] = []
        unimplemented: List[str] = []
        shape_violations: List[str] = []
        for ep in business_endpoints or []:
            method = str(ep.get("method") or "GET").upper()
            path = str(ep.get("path") or "")
            if not path:
                continue
            url = base + _path_with_params(path)
            body = {} if method in ("POST", "PUT", "PATCH") else None
            res = _http(method, url, token=token, body=body)
            reachable = res["status"] is not None and res["status"] < 500
            _ur = _unimplemented_route(method, path, ep.get("status"), res["status"])
            endpoint_results.append({
                "id": ep.get("id"),
                "method": method,
                "path": path,
                "status_code": res["status"],
                "reachable": reachable,
                "passed": reachable and not _ur,
                "error": res["error"],
                "trace": f"{method} {url} -> {res['status'] or res['error']}",
            })
            if not reachable:
                unreachable.append(f"{method} {path} → {res['status'] or res['error']}")
            if _ur:
                unimplemented.append(_ur)
            # gate C — behavioral COMPLETENESS: a 2xx response MUST match the contract
            # shape for its path-type (catches the real instagram bug where GET
            # /api/users/me returned {"items":[all users]} — reachable but semantically
            # wrong). Conservative: only a clear single↔collection mismatch is flagged.
            _sv = _shape_violation(method, path, res["status"], res["body_text"])
            if _sv:
                shape_violations.append(_sv)
        _add("business_endpoints_reachable", not unreachable,
             ("; ".join(unreachable))[:800] if unreachable else f"{len(business_endpoints or [])} endpoint(s) reachable")
        _add("business_endpoints_implemented", not unimplemented,
             ("; ".join(unimplemented))[:800] if unimplemented
             else f"{len(business_endpoints or [])} registered-implemented endpoint(s) serve their route")
        _add("business_endpoints_correct_shape", not shape_violations,
             ("; ".join(shape_violations))[:800] if shape_violations
             else f"{len(business_endpoints or [])} endpoint(s) match the item/items contract")

        # gate C (persistence): a parameterless POST collection endpoint must REALLY
        # persist — POST it, then GET the same path and require the new id to appear.
        # "201 but nothing stored" (in-memory handler, dropped txn) passed every
        # earlier gate. Conservative: only asserted for the first POST /api/<col>
        # whose POST returned 2xx with an {item:{id}} and whose GET returns a list.
        # §2 gate-hardening: the FIRST verifiable POST still drives the BLOCKING gate exactly
        # as before (no new hard blocks). Additionally, probe the OTHER parameterless POSTs and
        # surface non-blocking WARNINGS — a 2xx create whose collection GET is EMPTY or doesn't
        # contain the new id (the "201 but nothing stored" / 200-but-empty class), or a skip
        # that used to pass silently — so they're visible in the report instead of invisible.
        post_eps = [e for e in (business_endpoints or [])
                    if str(e.get("method", "")).upper() == "POST" and "{" not in str(e.get("path", ""))]
        persist_detail = "no parameterless POST endpoint to probe"
        persist_ok = True
        persist_warnings: list = []
        _first_scored = False
        for post_ep in post_eps[:8]:  # cap to bound probe time
            ppath = str(post_ep["path"])
            pres = _http("POST", base + ppath, token=token, body=_probe_body(post_ep))
            if not (pres["status"] and 200 <= pres["status"] < 300):
                persist_warnings.append(f"POST {ppath} → {pres['status'] or pres['error']} — write not verified")
                continue
            try:
                new_id = (json.loads(pres["body_text"]) or {}).get("item", {}).get("id")
            except Exception:
                new_id = None
            back = _http("GET", base + ppath, token=token)
            try:
                payload = json.loads(back["body_text"] or "{}")
                rows = payload.get("items") if isinstance(payload, dict) else None
            except Exception:
                rows = None
            if not isinstance(rows, list):
                persist_warnings.append(f"POST {ppath} ok but GET readback is not an items[] list — persistence not verifiable")
                continue
            if new_id is not None:
                contains = any(isinstance(r, dict) and r.get("id") == new_id for r in rows)
                if not _first_scored:
                    # FIRST verifiable POST = the blocking gate (byte-identical to prior behavior).
                    persist_ok = contains
                    persist_detail = (
                        f"POST {ppath} → id={new_id}; GET readback "
                        + ("contains it" if contains else
                           f"does NOT contain it ({len(rows)} row(s)) — write not persisted"))
                    _first_scored = True
                elif not contains:
                    persist_warnings.append(
                        f"POST {ppath} → id={new_id} NOT in readback ({len(rows)} row(s)) — possible non-persist")
            else:
                if len(rows) == 0:
                    persist_warnings.append(
                        f"POST {ppath} returned 2xx but the collection GET is EMPTY — possible non-persisting write")
                elif not _first_scored:
                    persist_detail = f"POST {ppath} 2xx ({len(rows)} row(s)); no item.id to match — skipped"
        if persist_warnings:
            persist_detail += " | warnings: " + "; ".join(persist_warnings)
        _add("business_writes_persist", persist_ok, persist_detail)

        # 5. Auth enforced: a business endpoint without a token → 401.
        get_ep = next((e for e in (business_endpoints or []) if str(e.get("method", "GET")).upper() == "GET"), None)
        if get_ep:
            url = base + _path_with_params(str(get_ep.get("path")))
            noauth = _http("GET", url)
            _add("auth_enforced_401", noauth["status"] == 401,
                 "" if noauth["status"] == 401 else f"GET {get_ep.get('path')} no-token → {noauth['status']} (expected 401)")

        # 5.5 VERIFIER CHAIN TEST (user decision 2026-06-11): real API-chain
        # coverage belongs to the VERIFIER's validation, not post-release
        # reporting — register → login → authed me → create → read-back →
        # cross-user interactions, driven by the registered contract. Any
        # step that is BROKEN (5xx / auth failure / wrong data) fails the
        # gate; "missing" (404/405 — later-milestone endpoints) stays soft.
        try:
            from .chain_executor import run_chains
            _chain = run_chains(base, project_dir, list(business_endpoints or []))
            # Surface the PER-CHAIN results so the run_validation tool can sync each
            # chain's verdict back through the LIVE registryhub (record_chain_result)
            # to the MAIN registry the delivery gate reads. run_chains' own status
            # write-back goes to project_dir's hub file — which, when validation runs
            # inside a lane WORKTREE, is NOT the registry the gate audits (run v20:
            # chains pass live but the gate sees stale 'registered' → deadlock).
            chain_results = _chain.get("chains") or []
            _add("business_chain", not _chain["broken"],
                 ("; ".join(_chain["broken"]))[:800] if _chain["broken"]
                 else f"{_chain['total_steps']} step(s) across "
                      f"{len(_chain['chains'])} verifier-authored chain(s) pass")
        except Exception as _chain_exc:
            _add("business_chain", False, f"chain runner crashed: {_chain_exc}")

        # 5.6 DEAD-CONTROL RULE (user decision 2026-06-11): page-type-agnostic
        # — a page that renders interactive markup (<form>, submit buttons)
        # must BIND it somewhere in the file (onSubmit/onClick/fetch/api use).
        # The 1.4.0 signup page was a pixel-perfect <form> with zero handlers;
        # every HTTP probe passed while no human could use it. Conservative
        # rules to avoid false positives: only flag files that have a <form>
        # or a submit-typed button AND contain NO handler/API token at all.
        try:
            _src_dir = Path(project_dir) / "app" / "frontend" / "src"
            _dead: list = []
            if _src_dir.is_dir():
                for _pf in sorted(_src_dir.rglob("*.jsx")):
                    try:
                        _txt = _pf.read_text(encoding="utf-8", errors="ignore")
                    except Exception:
                        continue
                    _interactive = ("<form" in _txt) or ('type="submit"' in _txt)
                    _bound = any(tok in _txt for tok in (
                        "onSubmit", "onClick", "fetch(", "apiGet", "apiPost",
                        "apiPut", "apiDelete", "axios"))
                    if _interactive and not _bound:
                        _dead.append(_pf.name)
            _add("frontend_dead_controls", not _dead,
                 ("interactive markup with NO bound handler/API call — a user "
                  "clicking these gets nothing: " + ", ".join(_dead))[:800]
                 if _dead else "all interactive pages bind their controls")
        except Exception as _dc_exc:
            _add("frontend_dead_controls", True, f"scan skipped: {_dc_exc}")

        # 6. Frontend HTTP reachable: the UI container must actually SERVE. docker_up
        #    passes even when the frontend container crashes right after start (the
        #    nginx env-var crash shipped exactly that way), and frontend_navigable is
        #    a static file check — this closes the runtime gap.
        fe_port = _service_host_port(compose_file, cwd, "frontend")
        if fe_port:
            fe = _http("GET", f"http://localhost:{fe_port}/", timeout=20)
            ok = fe["status"] is not None and 200 <= fe["status"] < 400
            _add("frontend_reachable", ok,
                 f"GET :{fe_port}/ → {fe['status'] or fe['error']}"
                 + ("" if ok else " — the frontend container is not serving (crashed after start?)"))
        else:
            _add("frontend_reachable", False,
                 "could not resolve the frontend service's published port "
                 "(container not running?)")

        return _finalize(checks, backend_port, endpoint_results, chain_results)
    except Exception as exc:
        _add("runner_error", False, f"{type(exc).__name__}: {exc}")
        return _finalize(checks, backend_port, endpoint_results, chain_results)
    finally:
        if teardown:
            try:
                _compose(compose_file, "down", "-v", "--remove-orphans", cwd=cwd, timeout=120)
            except Exception:
                pass
        # FIX #36: release the validation lock so the next validator can boot.
        if _lock_fh is not None:
            try:
                _fcntl.flock(_lock_fh.fileno(), _fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                _lock_fh.close()
            except Exception:
                pass


def _finalize(checks: List[Dict[str, Any]], backend_port: Optional[int],
              endpoint_results: Optional[List[Dict[str, Any]]] = None,
              chain_results: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    passed = bool(checks) and all(c["status"] == "pass" for c in checks)
    fails = [c["name"] for c in checks if c["status"] != "pass"]
    summary = "all api_smoke checks passed" if passed else f"FAILED: {', '.join(fails)}"
    return {"passed": passed, "summary": summary, "checks": checks,
            "backend_port": backend_port, "endpoints": endpoint_results or [],
            "chains": chain_results or []}


__all__ = ["run_smoke_validation"]
